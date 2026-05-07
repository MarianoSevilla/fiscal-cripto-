# Plan de desarrollo — Fiscal Cripto SaaS

Documento de referencia para el desarrollo de la plataforma. Refleja las decisiones de diseño tomadas y el orden de implementación acordado.

---

## Visión del producto

Plataforma SaaS de procesamiento fiscal de criptomonedas para el mercado español (IRPF, método FIFO, art. 37.2 LIRPF).

El sistema no es "una app que genera informes" — es una **infraestructura de datos financieros con control de acceso basado en consumo**.

---

## Decisiones de arquitectura tomadas

- El usuario **no tiene un plan** — tiene suscripciones a planes
- Los límites del plan se **congelan en el momento de la suscripción** (snapshot), para que cambios futuros de pricing no afecten a usuarios existentes
- Los PDFs **no se almacenan** — se generan en tiempo real. Solo se registra metadata de actividad (quién, qué exchange, cuándo, si descargó)
- **Solo Stripe** como pasarela de pago en v1
- **Supabase Auth** para autenticación (evita construir OAuth + email/password desde cero)
- Email verificado obligatorio antes de contratar cualquier plan de pago

---

## Esquema de base de datos (versión final)

### users
```sql
CREATE TABLE users (
    id                  BIGSERIAL PRIMARY KEY,
    email               TEXT UNIQUE NOT NULL,
    password_hash       TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    email_verified_at   TIMESTAMP,            -- NULL = no verificado
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),
    last_login          TIMESTAMP,
    deleted_at          TIMESTAMP
);
```

### user_auth_providers
```sql
CREATE TABLE user_auth_providers (
    id               BIGSERIAL PRIMARY KEY,
    user_id          BIGINT REFERENCES users(id) ON DELETE CASCADE,
    provider         TEXT NOT NULL,           -- google, email, apple
    provider_user_id TEXT NOT NULL,
    created_at       TIMESTAMP DEFAULT NOW(),
    UNIQUE(provider, provider_user_id)
);
```

### plans
```sql
CREATE TABLE plans (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    description     TEXT,
    price_cents     INTEGER NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'EUR',
    billing_period  TEXT NOT NULL,            -- monthly, yearly
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);
```

### plan_limits
```sql
CREATE TABLE plan_limits (
    id           BIGSERIAL PRIMARY KEY,
    plan_id      BIGINT REFERENCES plans(id) ON DELETE CASCADE,
    limit_key    TEXT NOT NULL,               -- fifo_reports_per_month, imports_per_month...
    limit_value  INTEGER NOT NULL,
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW(),
    UNIQUE(plan_id, limit_key)
);
```

### subscriptions
```sql
CREATE TABLE subscriptions (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT REFERENCES users(id) ON DELETE CASCADE,
    plan_id      BIGINT REFERENCES plans(id),
    status       TEXT NOT NULL,               -- pending, active, expired, canceled
    starts_at    TIMESTAMP,
    ends_at      TIMESTAMP,
    activated_at TIMESTAMP,
    canceled_at  TIMESTAMP,
    auto_renew   BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_subscriptions_user_status ON subscriptions(user_id, status);
```

### subscription_limits_snapshot
```sql
CREATE TABLE subscription_limits_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    subscription_id BIGINT REFERENCES subscriptions(id) ON DELETE CASCADE,
    limit_key       TEXT NOT NULL,
    limit_value     INTEGER NOT NULL
);
```
Se rellena automáticamente al activar la suscripción.

### payments
```sql
CREATE TABLE payments (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT REFERENCES users(id),
    subscription_id     BIGINT REFERENCES subscriptions(id),
    provider            TEXT NOT NULL DEFAULT 'stripe',
    provider_payment_id TEXT,
    amount_cents        INTEGER NOT NULL,
    currency            TEXT NOT NULL,
    status              TEXT NOT NULL,        -- pending, paid, failed, refunded
    paid_at             TIMESTAMP,
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
```

### exchanges
```sql
CREATE TABLE exchanges (
    id   BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL             -- binance, bitvavo, bit2me, kraken, coinbase, nexo, cryptocom...
);
```

### data_imports
```sql
CREATE TABLE data_imports (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT REFERENCES users(id),
    exchange_id    BIGINT REFERENCES exchanges(id),
    status         TEXT NOT NULL,             -- processing, completed, failed
    file_name      TEXT,
    rows_total     INTEGER,
    rows_processed INTEGER,
    error_log      JSONB,
    created_at     TIMESTAMP DEFAULT NOW(),
    completed_at   TIMESTAMP
);
```

### transactions
```sql
CREATE TABLE transactions (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id) ON DELETE CASCADE,
    import_id   BIGINT REFERENCES data_imports(id),
    exchange_id BIGINT REFERENCES exchanges(id),

    -- Clasificación
    category TEXT NOT NULL,
    -- compraventa | swap | rendimiento | movimiento | desconocida

    subtype  TEXT NOT NULL,
    -- compraventa:  COMPRA, VENTA
    -- swap:         crypto_to_crypto
    -- rendimiento:  earn_interest, trading_rebate, staking_reward, ...
    -- movimiento:   earn_allocation, earn_withdrawal, deposit, withdrawal, ...

    -- Activo principal
    asset  TEXT    NOT NULL,
    amount NUMERIC NOT NULL,

    -- Contraparte (EUR en compraventas, otro coin en swaps)
    counterpart_asset  TEXT,
    counterpart_amount NUMERIC,
    price_eur          NUMERIC,

    -- Comisiones
    fee_asset  TEXT,
    fee_amount NUMERIC,

    -- Valor EUR del rendimiento (staking, rebates)
    value_eur NUMERIC,

    -- Timestamp original de la operación en el exchange
    operated_at TIMESTAMP NOT NULL,

    -- Datos específicos del exchange que no encajan en el esquema
    metadata JSONB,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_transactions_user_exchange ON transactions(user_id, exchange_id);
CREATE INDEX idx_transactions_category ON transactions(user_id, category, operated_at);
```

### fifo_reports
```sql
CREATE TABLE fifo_reports (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT REFERENCES users(id),
    exchange_id  BIGINT REFERENCES exchanges(id),
    fiscal_year  INTEGER,                     -- 2024, 2025...
    status       TEXT NOT NULL,               -- generated, failed
    rows_count   INTEGER,
    created_at   TIMESTAMP DEFAULT NOW(),
    downloaded_at TIMESTAMP                   -- NULL hasta que el usuario descarga
);
```
**Los PDFs no se almacenan.** Este registro solo existe para analítica de uso.

### usage_events
```sql
CREATE TABLE usage_events (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT REFERENCES users(id),
    event_type   TEXT NOT NULL,               -- fifo_generated, fifo_downloaded, csv_imported...
    resource_key TEXT NOT NULL,
    quantity     INTEGER DEFAULT 1,
    metadata     JSONB,
    created_at   TIMESTAMP DEFAULT NOW()
);
```

### usage_counters
```sql
CREATE TABLE usage_counters (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT REFERENCES users(id),
    resource_key TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end   DATE NOT NULL,
    used         INTEGER DEFAULT 0,
    UNIQUE(user_id, resource_key, period_start)
);
```

### user_activity
```sql
CREATE TABLE user_activity (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT REFERENCES users(id),
    entity_type TEXT,
    entity_id   BIGINT,
    action_type TEXT,
    metadata    JSONB,
    created_at  TIMESTAMP DEFAULT NOW()
);
```

---

## Reglas de negocio clave

### Activación de suscripción
1. Crear `subscription` con `status = pending`
2. Crear `payment` vinculado
3. Stripe webhook confirma pago → `payment.status = paid`
4. Actualizar `subscription.status = active`, rellenar `activated_at`
5. Copiar límites del plan a `subscription_limits_snapshot`

### Suscripción activa de un usuario
```sql
SELECT * FROM subscriptions
WHERE user_id = ? AND status = 'active'
ORDER BY activated_at DESC
LIMIT 1;
```

### Validar límite antes de generar informe
1. Obtener límite del snapshot de la suscripción activa
2. Obtener contador actual del período en `usage_counters`
3. Si `used >= limit_value` → bloquear

### Registrar uso
```sql
INSERT INTO usage_events (user_id, event_type, resource_key, ...) VALUES (...);
-- Actualizar o insertar contador:
INSERT INTO usage_counters (user_id, resource_key, period_start, period_end, used)
VALUES (?, ?, DATE_TRUNC('month', NOW()), ..., 1)
ON CONFLICT (user_id, resource_key, period_start)
DO UPDATE SET used = usage_counters.used + 1;
```

---

## Roadmap de implementación

### Fase 1 — Autenticación y usuarios (ACTUAL)
- [ ] Añadir `email_verified_at` a la tabla `users`
- [ ] Flujo de verificación para **nuevos registros**: al registrarse reciben email con enlace, acceso completo solo tras verificar
- [ ] Flujo de verificación para **usuarios existentes**: email informativo con enlace de verificación, sin bloqueo inmediato
- [ ] Página de aviso "Verifica tu email" tras el registro
- [ ] Endpoint de confirmación (`/verify-email?token=...`)
- [ ] Reenvío de email de verificación

### Fase 2 — Planes y suscripciones (MVP SaaS)
- [ ] Tablas: `plans`, `plan_limits`, `subscriptions`, `subscription_limits_snapshot`
- [ ] Página de precios
- [ ] Lógica de plan gratuito con límites
- [ ] Integración Stripe (checkout + webhooks)
- [ ] Activación automática de suscripción al confirmar pago

### Fase 3 — Control de uso y límites
- [ ] Tablas: `usage_events`, `usage_counters`, `fifo_reports`
- [ ] Validación de límites antes de generar informe
- [ ] Registro automático de uso al generar/descargar
- [ ] Dashboard de uso para el usuario

### Fase 4 — Importación y almacenamiento de transacciones
- [ ] Tablas: `exchanges`, `data_imports`, `transactions`
- [ ] Adaptar clasificadores para escribir en BD además de procesar en memoria
- [ ] Deduplicación por `import_id + operated_at + asset + amount`
- [ ] Posibilidad de deshacer una importación

### Fase 5 — Analítica y administración
- [ ] Panel de administración con métricas de uso por plan
- [ ] `user_activity` para trazabilidad completa
- [ ] Alertas de uso elevado

---

## Errores a evitar
- No guardar `plan_id` directamente en `users`
- No modificar límites de suscripciones ya activas (siempre snapshot)
- No cachear PDFs — se generan en tiempo real
- No soportar múltiples pasarelas de pago en v1
- No bloquear usuarios existentes al activar verificación de email

---

## Stack técnico
- **Backend**: Flask (Python) — mantener el stack actual
- **Base de datos**: PostgreSQL (JSONB, índices compuestos)
- **Auth**: Supabase Auth (evita construir OAuth desde cero)
- **Pagos**: Stripe
- **Almacenamiento de ficheros**: no requerido (PDFs en tiempo real, CSVs no se persisten)

---

*Última actualización: 2026-05-07*
