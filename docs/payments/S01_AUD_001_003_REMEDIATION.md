# S01 · Reparación focalizada S01-AUD-001 y S01-AUD-003

**13/10/2026 · SOLO PR EN BORRADOR · NO MERGE · NO DEPLOY · NO COBROS.**

- Repositorio: `MarianoSevilla/fiscal-cripto-`.
- Base exacta: PR #41, SHA `8133e6615654c690a04585b1b59ff59b23ddc461`.
- Contexto: informe de auditoría PR #42, SHA `a9274f3115b7f5660f9d012d7432ddddc78c0074`, revisión en lectura y **sin incorporar modificaciones de esa PR**.
- `main` esperado: `56882073295faae3bd1bc3632288a970acb330da`.

## S01-AUD-001: nunca borrar referencias financieras al reenviar presupuestos

`app.py` elimina la asignación `paypal_order_id = None` y `paypal_capture_id = None` en `advisory_enviar_presupuesto`, preservando la evidencia histórica.

Antes de modificar el presupuesto, el handler usa `SELECT FOR UPDATE` sobre la fila del expediente. Con el bloqueo tomado, rechaza (409) cualquier reemisión si hay una referencia `paypal_order_id`, `paypal_capture_id`, `stripe_checkout_session_id`, `stripe_payment_intent_id`, `payment_provider`, `amount_paid` (incluso cero), `paid_at`, `quote_accepted_at` o **cualquier** fila en `S01StripeCheckoutAttempt` (incluyendo `creating`, `uncertain`, `ready`, `paid`, `closed` o `reserved`). Se hace rollback explícito antes de responder.

La consulta comparte el orden de bloqueo **expediente → intento** con `_reserve` del orquestador S01, impidiendo que un intento concurrente se reserve justo durante el cambio de token. Los presupuestos nunca intentados/aceptados pueden seguir revisándose al autorizar la funcionalidad en una fase posterior.

Se cubre con tests ORM SQLite sintéticos que ejecutan el cuerpo real del handler, sin decorar y sin montar el resto de la app, con proveedor de correo simulado. Validan **409 sin modificación de importe, referencias PayPal/Stripe, token, estado, historia ni auditoría**; contemplan todo estado de intento. Un test AST verifica que el `FOR UPDATE` y guard precedan a las escrituras; los tests PREFREEZE existentes siguen verificando 503 en rutas públicas.

**Límite:** el comportamiento es seguro con el mismo PostgreSQL transaccional; las pruebas nuevas directas SQLite son secuenciales. Sigue pendiente una prueba de carrera entre dos sesiones que compitan por reserva S01/actualización del presupuesto en PostgreSQL y un ensayo desde backup de producción. No retirar PREFREEZE por esta corrección.

## S01-AUD-003: objeto del SDK Stripe Python v16

`advisory_s01_test_orchestrator._session_mapping()` ahora admite primero `StripeObject.to_dict()`, usando `to_dict_recursive()` como alternativa para implementaciones antiguas. Cualquier conversión inválida o excepción hace **fail-closed** y mantiene el intento en estado `uncertain` tras el resultado ambiguo del proveedor.

Pruebas que construyen un `stripe.StripeObject` mediante **el SDK instalado por `requirements.txt`** comprueban que una sesión sintética correcta permite completar la **reserva TEST local** y que importe incorrecto o excepción dejan el intento incierto sin registrar una sesión como válida. No se contacta con Stripe ni con PayPal.

## No cambia

- El webhook público Stripe sigue con PREFREEZE 503; el consumidor seguro sigue solo en TEST sintético.
- La ruta PayPal está retirada ejecutablemente en PR #41; no se borran órdenes ni capturas.
- No se envían emails reales, no se crean pagos de prueba o reales, no se emiten facturas.
- No cambian Alembic, modelos, índices, Railway, Stripe, MERU, secrets, PR anteriores ni producción.
- Rafa gestiona la facturación externamente; la app solo facilitará pagos cuando esté autorizada.

## Verificación requerida

1. **Required CI** de este commit: backend-tests, postgres-bootstrap PG18 y browser-navigation.
2. Revisar expresamente los nuevos tests SDK + evidencia histórica; ninguna afirmación de CI verde antes de terminar.
3. PR **encadenada** sobre #41 y pendiente de revisión independiente; incluso con CI verde continúa el veredicto global **NO-GO** de la PR #42 por migración desde restauración íntegra, conciliación externa PayPal, receptor Stripe real y notificaciones.
