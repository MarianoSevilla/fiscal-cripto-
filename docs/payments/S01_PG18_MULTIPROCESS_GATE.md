# S01 — Validación de concurrencia real PostgreSQL 18 (etapa 6)

**SOLO CI / PR DRAFT / NO MERGE / NO DEPLOY / NO STRIPE / NO RAILWAY.**

Base exacta: PR #37 SHA `9a6e674de7f61f610bcc5f27aaebd91d57a5e21f`.
Rama nueva `test/s01-stripe-pg18-multiprocess`, encadenada sobre #37.
La aplicación no factura; la facturación la gestiona Rafa externamente.

## Alcance de esta etapa

Archivo `fiscal_app_export/tests/qa_s01_pg18_multiprocess.py`, ejecutado
en el job `postgres-bootstrap` de Required CI **después** de bootstrap
y QA PREFREEZE. No se toca código de endpoints, pagos ni esquema.

1. Crea `s01_pg18_multiprocess_ci` **únicamente dentro de GitHub Actions**.
   Requiere `GITHUB_ACTIONS=true`, `CI=true`, `FLASK_ENV=testing`,
   usa únicamente `127.0.0.1:5432`, PostgreSQL de CI, usuario ficticio
   y password estática de CI ya existente. La cadena de conexión nunca
   se obtiene de Railway ni variables externas.
2. Registra expediente y reserva sintéticos, exclusivamente `is_test=True`,
   Checkout `cs_test_`, EUR, honorarios 200,00 €, comisión 60,00 €,
   total 260,00 € y `PaymentIntent` ficticio. Nunca llama Stripe.
3. Arranca **dos procesos independientes** usando `spawn`, cada uno con
   su conexión propia, comprobando sus sesiones reales en `pg_stat_activity`.
4. El coordinador bloquea la fila del expediente con `SELECT FOR UPDATE`;
   espera a observar **dos backends en `wait_event_type='Lock'`**,
   libera el bloqueo y comprueba respuesta e invariantes SQL.
5. Cuatro escenarios independientes:
   - **Mismo evento Stripe dos veces:** `paid` + `duplicate`,
     un recibo, una transición de historial.
   - **Dos IDs de evento distintos, mismo pago/PI:** `paid` +
     `already_paid`, dos recibos, un solo historial.
   - **Evento correcto vs importe incorrecto:** una confirmación y
     un rechazo sin efecto adicional.
   - **PaymentIntent preconciliado correcto vs contradictorio:**
     una confirmación y un rechazo sin reemplazar el PI.
6. Quinta prueba: trigger SQL de PostgreSQL fuerza error al insertar
   el historial del pago. Comprueba que recibo, estado e intento **no
   se escriben parcialmente**, elimina el trigger, reenvía idéntico
   evento firmado y confirma **una sola vez**.
7. El runner elimina su propia base efímera con `DROP DATABASE ... FORCE`
   incluso ante fallo. Los trabajadores tienen timeout y terminación
   en el bloque final. Solo se usa una base que nace en la propia prueba.

## Qué valida y qué NO valida

Se confirma la atomicidad e idempotencia de
`process_signed_s01_test_webhook` sobre PostgreSQL 18 con procesos
**realmente concurrentes**, no solo SQLite ni threads.

NO certifica pérdida de ACK del commit tras respuesta del proveedor,
fallo SIGKILL del proceso justo antes/durante/tras commit, caída de red
real, reintentos fuera del período de idempotencia Stripe, duplicaciones
de mensajes en una futura cola outbox, webhooks PayPal U04 ni la
conciliación de todas las ramas Alembic. Deben investigarse antes de
activar cobros públicos.

El nuevo consumidor S01 continúa sin estar conectado al endpoint Flask:
PREFREEZE sigue respondiendo 503 sin procesar los eventos entrantes.
Ninguna cuenta Stripe o banco de MERU se modifica.

## Puertas de integración

- Required CI: `backend-tests`, `postgres-bootstrap` con el runner
  nuevo (4 escenarios multiproceso + 1 rollback), `browser-navigation`.
- Revisión independiente de resultados e invariantes, sin fusiones.
- La posible retirada PayPal y la resolución de migraciones paralelas
  siguen pendientes de decisión separada; #29 intacta.
- No ofrecer una ruta de pago hasta completar consumidor HTTP nuevo,
  autenticación/conciliación, outbox idempotente, autorizaciones
  administrativas y pruebas de staging.

**Criterio NO-GO:** cualquier resultado ambiguo, fallo de conexión,
integridad parcial, pago duplicado, cobertura incompleta o
comportamiento inesperado obliga a detener integración y mantener
los cobros inactivos.
