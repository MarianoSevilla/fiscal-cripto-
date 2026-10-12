# S01 — Etapa 8 · Retirada ejecutable de PayPal y puerta de migraciones

**ESTADO: PR DRAFT / NO MERGE / NO DEPLOY / NO PAGOS / NO BORRADOS DE DATOS.**

Base exacta: PR #40, `2b0717040f39ba9d0f5303e132d63b178219582b`.
Objetivo: dejar el runtime PayPal físicamente inerte y documentar la decisión
de NO incorporar la migración divergente de U04 #29 en la cadena Stripe S01.

## Qué se ha hecho

1. En `app.py`, las funciones `_paypal_get_access_token`,
   `_paypal_create_order`, `_paypal_capture_order` y
   `_on_payment_completed` quedan como símbolos históricos que
   únicamente invocan `refuse_advisory_financial_operation()`.
   **Se elimina el código de llamadas HTTP a PayPal, de OAuth, de órdenes,
   de capturas y del finalizador legacy que marcaba pagos y enviaba emails.**
2. Las rutas existentes `/api/pago/iniciar/<token>`,
   `/api/pago/paypal/capture` y `/api/webhooks/paypal` preservan
   método y decoradores PREFREEZE, pero su cuerpo es inerte: siempre rechaza
   también cualquier llamada directa sin el decorador. No leen payload,
   token, expediente ni base de datos. El webhook PayPal **no hace ACK 2xx**.
3. `_PAYPAL_ENABLED` es constante `False` para compatibilidad de tests
   legacy. No se cargan `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`,
   `PAYPAL_WEBHOOK_ID` ni se construyen URLs del API PayPal. No existe
   interruptor de entorno que reactive PayPal. No se modifican las variables
   de entorno existentes en Railway: simplemente ya no se leen.
4. La página de mantenimiento `/pagar/<token>` sigue sin botón PayPal.
   La ruta genérica `/api/pago/iniciar/<token>` queda retirada también:
   Stripe tendrá en una etapa futura una **ruta nueva específica**, sujeta
   a una revisión y gate de seguridad independiente, sin reutilizar
   automáticamente la antigua.
5. Se mantienen `FiscalAdvisoryRequest.paypal_order_id`,
   `paypal_capture_id`, `payment_provider`, `amount_paid` y los
   estados/historial legacy. No se realiza eliminación, anonimización,
   reescritura ni backfill de cobros anteriores.

## Historial Alembic y PR #29

- `main` actual y producción auditada en la etapa previa usan
  `v5w6x7y8z9a0`; la PR #29 propone `w6x7y8z9a0b1`
  **desde ese mismo head**. Es un árbol paralelo, actualmente no integrado.
- La línea S01 presenta **un único head**:
  `v5w6x7y8z9a0` -> `x7y8z9a0b1c2` ->
  `y8z9a0b1c2d3` -> `z9a0b1c2d3e4`.
- **Decisión de esta rama**: no fusionar #29 ni su migración PayPal;
  no añadir `merge revision` artificial ni aplicar `stamp`.
  Conservar #29 abierta como evidencia de la revisión bloqueada
  hasta que el propietario decida su cierre. No alterarla.
- Si otro cambio hubiese introducido `w6x7y8z9a0b1`, una revisión
  distinta de Alembic o datos financieros que deban reconciliarse,
  detener la integración. No cambiar el head mediante atajos.
- El script CI `qa_s01_paypal_retirement_pg18.py` usa PostgreSQL 18
  efímero; valida que el repositorio tenga un solo head y excluya U04,
  ejecuta el DDL **de las tres migraciones S01** sobre una tabla histórica
  **mínima y sintética**, y verifica que sobrevivan order/capture,
  proveedor, importe, estado y token originales. También verifica que
  no se inventen honorarios/comisiones históricas y que existan las
  nuevas tablas de pagos Stripe. No usa Railway y no ejecuta upgrades
  de la base de datos real.
- Esta prueba DDL sintética **NO equivale a ensayar una actualización
  real del esquema de producción completo desde su backup**. Antes de
  cualquier merge/deploy se requiere restauración íntegra aislada de
  producción, plan de migración reconciliado y autorización específica.

## Restricciones y pendientes

- NO se toca producción, Railway, Stripe, PayPal, MERU, credenciales,
  suscripciones, correos, facturas, webhooks configurados ni otras PR.
- La aplicación **NO genera facturas fiscales**: Rafa se encarga de ello
  externamente.
- El historial PayPal continúa para lectura y conciliación. Antes de
  retirar en producción deben verificarse **sin datos personales** los
  registros con orden/captura o resultado incierto y los movimientos
  reales en el proveedor, si los hay. Las declaraciones previas de que
  no se cobró a ningún cliente NO sustituyen un cierre financiero
  documentado cuando se vaya a habilitar Stripe Live.
- PR #30 mantiene PREFREEZE: **todos los endpoints financieros públicos
  siguen suspendidos**; la PR no habilita cobros de Stripe.
- Hay que decidir cómo conservar y consultar auditoría de cobros
  históricos si se retira U04 #29, y cubrir eventual reembolso
  excepcional sin revivir el API PayPal legacy.
- Las PR S01 siguen encadenadas, todas en borrador. Esta etapa NO autoriza
  su integración, ni decide el tratamiento contractual o fiscal externo.

## Condiciones de CI

`backend-tests`: tests AST de retirada y tests históricos;
`postgres-bootstrap`: nuevo gate de migraciones, arranque PG18, PR #39
concurrencia; `browser-navigation`: página de mantenimiento.
Verificar los tres resultados sobre el SHA exacto antes de dar esta
etapa por validada.
