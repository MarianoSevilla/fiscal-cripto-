# S01 · Etapa 7 — HTTP sintético Stripe y outbox transaccional

**SOLO PR EN BORRADOR. NO MERGE / NO DEPLOY / NO COBROS / NO WEBHOOK REAL.**

Repositorio `MarianoSevilla/fiscal-cripto-`. Base exacta PR #39:
`2371d884ffa319c978cd12224c6a31b9f98254c6`.
`main` esperado: `56882073295faae3bd1bc3632288a970acb330da`.

## Alcance aprobado

- S01: Rafa estudia cada expediente e introduce sus honorarios. La web
  calcula el suplemento del 30 % y, una vez autorizado el producto, facilitará
  cobrar el total mediante Stripe Checkout.
- **La web no crea ni envía facturas fiscales. Rafa se ocupa de la facturación
  fuera de la aplicación.** El outbox contiene únicamente tipos de aviso
  y IDs internos, no facturas, datos fiscales, destinatarios ni cuerpo email.
- Apple Pay y Google Pay quedan sujetos a elegibilidad del navegador/wallet
  en el Checkout alojado por Stripe. S02 suscripciones queda excluido.

## Qué cambia en esta etapa

1. `S01StripeNotificationOutbox` y migración aditiva Alembic
   `z9a0b1c2d3e4` desde `y8z9a0b1c2d3`. Cada intento puede contener
   exactamente una fila `customer_payment_confirmed` y una
   `advisor_payment_confirmed`, ambas `pending`. Restricciones UNIQUE
   `(attempt_id,kind)` y `delivery_key` impiden duplicar avisos.
2. `process_signed_s01_test_webhook`: conserva la firma obligatoria,
   correlación exacta y locks de PR #37/#39. En **una sola transacción**
   inserta dos avisos pendientes junto al recibo, historial y cambio
   del expediente. Si falla el outbox hace rollback también del pago.
   Repetir evento o recibir un segundo event.id del mismo PaymentIntent
   no crea nuevas filas de aviso.
3. `advisory_s01_test_http.py`: fábrica de Blueprint independiente. Exige
   `FLASK_ENV=testing` en su creación y **también en cada petición**,
   `Flask.testing`, secreto `whsec_` y carga limitada a 64 KiB.
   Expone exclusivamente `/__synthetic__/s01/stripe/webhook` dentro
   de una aplicación Flask construida por los tests. **No se importa,
   registra ni monta en `app.py`.**
4. Contrato HTTP local: firma inválida 400; caso no conciliable 409;
   BD indisponible 503; carga excesiva 413; pago confirmado o
   reenvío verificado 200. Ningún HTTP 200 si la transacción falla.
5. Pruebas nuevas de HTTP, invalidación de firma, outbox idempotente,
   rechazo de Live, falta de secreto, rollback de avisos, y barreras
   de no exposición. Se amplían las carreras multiproceso reales
   PostgreSQL 18 para comprobar que quedan exactamente **dos avisos
   pendientes** y ninguna duplicación incluso con webhooks simultáneos.
6. Bootstrap PostgreSQL 18 valida la nueva revisión Alembic en su base
   efímera; ninguna migración se ejecuta contra Railway.

## Qué NO está implementado

- No se generan Checkout Sessions reales ni de Stripe Test externo.
- No existe consumidor HTTP público operativo; el endpoint antiguo
  `/api/webhooks/stripe` permanece bajo PREFREEZE y responde 503.
- No existe worker que envíe emails, correos reales, ni nuevas opciones
  administrativas. **Exactly once en BD no garantiza exactly once en
  Resend**: queda pendiente usar una clave de idempotencia admitida por
  el proveedor (si está disponible) o semántica de entrega/documentación
  que gestione caídas entre envío y ACK; no prometer email único antes.
- No se fusiona ni retira código PayPal U04 (#29), no se borran
  identificadores antiguos y no se permiten capturas PayPal. El historial
  se preserva para conciliación y auditoría.
- La migración PayPal #29 `w6x7y8z9a0b1` diverge de la cadena S01
  `x7y8z9a0b1c2` -> `y8z9a0b1c2d3` -> `z9a0b1c2d3e4`.
  No ejecutar `stamp`, `upgrade` productivo ni combinar heads
  sin reconciliación revisada.
- No se procesan devoluciones, contracargos, cobros asíncronos ni
  incidencias de conectividad Stripe->MERU.
- No se modifica Stripe, MERU, PayPal, Railway, credenciales, staging,
  producción, datos de clientes ni PR anteriores.

## Condiciones de aprobación

- CI `backend-tests`, `postgres-bootstrap` con concurrencia PG18
  y `browser-navigation`, todos verdes **sobre el SHA final exacto**.
- Review independiente antes de cualquier merge. El código test-only no
  tiene permiso para activarse en producción.
- Pendiente: estrategia de retirada de PayPal con prueba de ausencia
  de órdenes cobradas o inciertas, política de reconciliación y plan
  auditable de migraciones antes de la integración HTTP real.
