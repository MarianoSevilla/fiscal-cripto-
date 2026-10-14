# S01 — Etapa 2 · Contrato Checkout y registro de intentos (solo TEST)

**DRAFT / NO MERGE / NO DEPLOY / NO PAGOS / NO LLAMADAS EXTERNAS.**
Base: PR #33, commit `831107d996d7b3ee0fb8c978f84028898e9a8b70`.
Esta rama es **dependiente** de #33. La PR apunta a `main` únicamente para ejecutar la CI configurada para esa base: el diff incluirá los cambios acumulados de #33 hasta que esta última sea integrada. **No fusionar #34 antes de #33.**

## Qué se añade

- `advisory_s01_checkout.py`: constructor puro de parámetros de Stripe Checkout
  `mode=payment`, EUR, importe exacto en céntimos, `client_reference_id`,
  metadatos sin PII y expiración entre 30 min y 24 h. Solo `card`:
  Apple Pay / Google Pay dependen de elegibilidad en Stripe-hosted Checkout.
- `verify_test_checkout_paid`: valida sesión de Stripe **ya verificada por firma**
  y correlacionada con el intento reservado: `cs_test_`, `livemode=False`,
  `payment_status=paid`, importe/moneda, referencia, huella, PaymentIntent.
  **No** autoriza por sí mismo el cambio de estado financiero.
- Tabla `s01_stripe_checkout_attempts`: un intento por expediente
  (`UNIQUE(advisory_id)`) con importe, hash del token, clave de idempotencia,
  estado reservado/incierto y referencias del proveedor. Conserva los casos
  de respuesta ambigua incluso si hay caída después del POST.
- Tabla `s01_stripe_event_receipts`: base para deduplicar webhooks por ID.
- Migración Alembic aditiva `y8z9a0b1c2d3`; sin backfill ni migraciones reales.
- Tests offline: sin red, tarjetas reales, claves, cobros ni transferencias.

## Protocolo pendiente ANTES de conectar los endpoints

1. **PREFREEZE obligatorio** y retirada/drenaje certificado de procesos U03.
2. El código que prepara la orden futura debe efectuar COMMIT de la reserva
   duradera en PostgreSQL 18 **antes** de POST a Stripe. No mantener
   transacción SQL durante la petición de red.
3. Solo un proceso concurrente podrá solicitar Checkout para ese expediente.
   Cualquier timeout, fallo de ACK o pérdida de sesión tras el POST queda en
   estado `uncertain` hasta reconciliar la misma reserva, **sin crear otra**.
4. La idempotencia Stripe API v1 es finita (>=24h); **nunca** se reintenta
   ciegamente una creación después de 24 horas. Buscar/reconciliar el objeto
   original; si no hay prueba, mantener bloqueo.
5. El webhook futuro debe verificar firma (PR #32), `event.id` único y
   `payment_status='paid'`, `amount_total`, divisa, huella de presupuesto,
   ID de intento, sesión almacenada y `PaymentIntent`. Recibo e impacto
   financiero se COMMITAN atómicamente y con bloqueo de fila.
6. Los correos de pago se emitirán desde una cola transaccional/outbox,
   nunca duplicados desde múltiples callbacks.
7. El enlace `/pagar/<token>` de la web no se reutilizará automáticamente
   si hay intención financiera incierta. No genera Checkout ahora.
8. Reemitir presupuesto sobre el mismo expediente con intento existente
   permanece bloqueado; requiere futura resolución auditada.
9. Reconciliar `#29` U04, `#30` PREFREEZE y `#32` firma Stripe,
   y resolver ramas Alembic, antes de integración o de lanzar Stripe Test.
10. Resolver con Rafa fiscalidad, emisor de factura y precio final con IVA
    antes de crear sesiones reales y antes de envíos de email.

## Contratos relevantes

- [Stripe Checkout Sessions](https://docs.stripe.com/payments/checkout-sessions)
- [Stripe idempotency API v1](https://docs.stripe.com/api/idempotent_requests)
- [Stripe wallets Checkout](https://docs.stripe.com/payments/wallets)

No se cambia `app.py`, rutas, `static/pagar.html`, credenciales, botones
ni panel de administración; no hay entrypoint de pago activable.
Este entregable **no termina S01**: es la infraestructura segura previa
a la orquestación HTTP, webhooks y email.
