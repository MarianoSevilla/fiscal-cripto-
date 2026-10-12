# S01 · Etapa 5 — consumidor Stripe TEST firmado y contabilidad transaccional

**Estado: DRAFT · SIN WEBHOOK PÚBLICO NUEVO · SIN COBROS · NO MERGE · NO DEPLOY.**

Base: PR #36, SHA `a91a1f4d6b8252c6c5be8930d8f389479f9d3783`.
Esta PR incluye por dependencia los cambios previos S01, PREFREEZE #30 y firma Stripe #32, manteniendo sus PR originales intactas.

## Producto confirmado

Los honorarios son fijados por Rafa. El cliente paga el total de honorarios más la comisión comercial del 30 % del propietario mediante Stripe Checkout; tarjetas, Apple Pay y Google Pay según elegibilidad.

**La aplicación no genera, emite, almacena ni envía facturas fiscales; Rafa se encarga de la facturación fuera de la aplicación.** Solo se conserva un historial técnico de pagos y estados de expediente.

## Implementación exclusivamente en pruebas sintéticas

El módulo `advisory_s01_stripe_test_events.py` recibe **bytes de evento + cabecera Stripe-Signature + secreto**, utiliza el SDK para verificar firma y vigencia. Rechaza entornos distintos de `FLASK_ENV=testing`, eventos Live, tipos distintos de `checkout.session.completed` e importes/estados dudosos. No consulta servicios externos.

Bajo una transacción de BD y `SELECT FOR UPDATE` sobre el expediente y el intento, valida:

- Estado `quote_sent`, marca `is_test=True`, token/huella del presupuesto y `30 %` exacto, monto en céntimos y EUR.
- `cs_test_` en el evento, en el intento y en el expediente; mismo PaymentIntent esperado sin contradicciones; estado `ready` de intento previo.
- Sin orden/captura PayPal anterior; sin reemisión ni modificación del expediente.
- Estado Stripe `complete` y `paid`, `livemode=False` a nivel de evento y sesión.
- `event.id` único: reenvío exacto no duplica historial. Evento distinto para el mismo pago confirmado se recibe de modo idempotente.

**Una sola transacción** inserta `s01_stripe_event_receipts`, cambia a `paid_received` el expediente, marca `paid` el intento y registra el historial. Fallos de almacenamiento hacen ROLLBACK de todos los efectos. No envía emails antes de confirmar la transacción ni incluye facturas.

## Límites de esta entrega

- **La ruta `/api/webhooks/stripe` permanece incondicionalmente PREFREEZE 503.** El consumidor S01 no se invoca desde Flask, tareas ni UI; solo tests sintéticos con firmas HMAC.
- No existen pagos ni sesiones creadas en Stripe Test/Live ni transferencias a MERU; no hay claves nuevas.
- La implementación no sustituye todavía el handler HTTP completo con outbox de notificaciones, alertas de conciliación, reembolsos, disputas ni pagos de finalización asíncrona (S01 prevé solo tarjeta).
- Al estar en TEST, el entorno `FLASK_ENV=testing` no debe ser considerado habilitación productiva; antes de autorizar una futura vía de cobro se necesitará un módulo de producción nuevo, revisado por separado, con configuración de cuenta firmada y controles sin posibilidad de bypass.
- **Pendiente de ejecutar prueba real en PostgreSQL 18 con dos procesos concurrentes sobre el mismo evento y con eventos distintos del mismo PaymentIntent.** La batería de tests ORM SQLite comprueba los caminos secuenciales y el rollback. El CI actual valida el esquema y PREFREEZE en PostgreSQL.
- No hay invocación al viejo `_on_payment_completed`: queda congelado y sigue enviando correos fuera de transacción. Antes de habilitar avisos de pago debe existir una cola outbox con envío único.
- #29 U04 PayPal introduce migración paralela `w6x7y8z9a0b1` desde `v5w6x7y8z9a0`; S01 tiene `x7y8z9a0b1c2` -> `y8z9a0b1c2d3`. Ninguna migración U04 se ha integrado. **No ejecutar upgrade en producción ni unir heads mediante stamp.**
- #29 también reemplaza auxiliares y modifica `app.py`; antes de una integración conjunta PayPal/Stripe requieren revisión de estado financiero y que PREFREEZE nunca quede sin proteger una ruta.
- Dado que el propietario ha elegido Stripe como proveedor principal y no se han cobrado operaciones históricas, la posibilidad de **retirar definitivamente la integración PayPal legacy** merece decisión separada antes de integrar U04. No se ha eliminado PayPal en esta fase.

## Gate para entrega

Backend tests completos,  PostgreSQL 18 bootstrap/PREFREEZE, Playwright navegador, firma Stripe, eventos duplicados, manipulación de importe, estado de pago y errores transaccionales. Ningún resultado se asume aprobado antes de CI terminal.

**Prohibido:** merge, cambios en Railway o configuración Stripe/PayPal/MERU, credenciales, transferencias, facturas, datos reales, emails y cobros reales o TEST.
