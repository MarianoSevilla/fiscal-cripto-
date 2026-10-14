# S01 G07 — Remediación AUD-001 / AUD-002 · Consentimiento y reserva atómicos

**13/10/2026 · Rama aislada apilada sobre la auditoría PR #51 `a28c44476d5a04f5e44cbcf8a5232e66fff6ca72`.**

**NO MERGE · NO DEPLOY · NO STRIPE REAL O TEST EXTERNO · NO CAMBIAR RAILWAY/PRODUCCIÓN · SIN COBROS.**

## 1. Dictamen y alcance

PR #51 demostró dos fallos de contrato en la simulación HTTP S01 G07/G08: **AUD-001 (ALTO)** el servicio aceptaba crear Checkout sin aceptación almacenada, y **AUD-002 (ALTO)** HTTP guardaba la aceptación mediante un COMMIT antes de reservar Checkout, permitiendo aceptaciones huérfanas tras errores. Esas pruebas eran `xfail(strict=True)` en CI #73 (1.477 passed, 2 xfailed). Estos hechos describían solo el *harness* ficticio no registrado en `app.py`, no una vulnerabilidad explotada en producción.

Esta remediación cambia **solo** el flujo de pruebas y su contrato transaccional; no introduce rutas Live, claves de proveedor, modificaciones de DB productiva, imports de pago en `app.py`, llamadas HTTP ni endpoints de factura.

## 2. Diseño del servicio

`advisory_s01_test_orchestrator._reserve` conserva el `SELECT ... FOR UPDATE` por expediente, bloqueo de órdenes anteriores, `UNIQUE(advisory_id)`, cálculo/precio/vencimiento, Stripe `cs_test_` e idempotencia.

- Si `quote_accepted_at` **no** existe y no se ha recibido un contexto `S01AcceptanceIntent` validado previamente por HTTP sintético, aborta con `S01CheckoutBlocked`, **antes de tocar el proveedor**. La protección es del servicio, no solo del endpoint.
- Si existe contexto de aceptación nueva, `_reserve` exige entero exacto en céntimos, coincidencia con importe presente bajo el lock, timestamp y `quote_accepted_at IS NULL`, ausencia de órdenes, IDs, proveedor, montos pagados o intento previo. La aceptación queda registrada en el mismo ámbito transaccional que el `S01StripeCheckoutAttempt(status='creating')`. **Un solo COMMIT** guarda ambas cosas, **antes** de llamar al fake proveedor.
- Cualquier error **anterior** al COMMIT hace rollback de aceptación e intento; el cliente puede obtener nuevo CSRF y volver a confirmar el *mismo* presupuesto si sigue vigente, sin reemitir una orden.
- Si la transacción se confirma, el intento único persiste incluso cuando el fake proveedor falla. Estado `creating/uncertain`, **sin segundo intento**, hasta conciliación autorizada. Nunca marcar `paid_at` por aceptación o enlace.
- Los tests históricos del servicio crean un presupuesto **ya aceptado explícitamente** en su fixture ficticia. Los nuevos ensayos HTTP son los que verifican el camino de **aceptación nueva + reserva en una sola transacción**.

**Limitación asumida**: `S01AcceptanceIntent` es un contexto interno de confianza solo en TEST local. La futura aceptación real requiere snapshot inmutable de términos, identidad, control anti-CSRF y auditoría legal G06/G07; no puede considerarse una prueba jurídica definitiva de consentimiento. El flujo antiguo de expedientes *ya aceptados* se sigue permitiendo para los tests de servicio: su eventual habilitación en Live exigirá snapshot/versionado y reglas más estrictas de elegibilidad.

## 3. Pruebas de cierre de los dos hallazgos altos

- `test_s01_g07_g08_independent_audit.py`: se retiran **ambos `xfail(strict=True)`**. AUD-001 exige que el servicio bloquee reserva directa sin consentimiento; AUD-002 simula fallo de preparación y exige que no persista aceptación huérfana.
- `test_s01_synthetic_acceptance_http.py`: confirma desglose, importe, CSRF, single-use, bloqueo por token y vencimiento; prueba revalidación en servicio, fallo de construcción de parámetros antes de COMMIT, excepción de COMMIT/rollback y posterior reaceptación sin inventar nuevo intento; comprueba fallo ambiguo **posterior** con intento `uncertain`.
- `qa_s01_quote_reservation_pg18.py`: ejecuta dos procesos Python con dos conexiones PostgreSQL 18 ficticias compitiendo por el lock de expediente. Añade **dos reservas concurrentes con aceptación nueva**, resultado esperado: `reserved` y `blocked`, **1 intento `creating`**, aceptación persistida, cero `paid_at`. Mantiene carreras previas reemisión/Checkout y barrera de salida, usando solo base CI y proveedor no invocado.

## 4. Invariantes aún pendientes

Los controles ALTO solo se podrán marcar PASS en **CI exacta** sin `xfail` de AUD-001/002 y PG18 SUCCESS; si falla alguna prueba, mantener NO-GO y corregir sin rebajar aserciones.

Esto **no** cierra G07/G08 de cara a clientes: falta snapshot legal de importe, impuestos, término/consentimiento, actor, rate-limiting y protección antiabuso, pruebas de HTTP con dos procesos sobre PG18 en un futuro servicio real, adaptación de errores operativos/recuperación e integración Stripe Test externo autorizada separadamente.

**NO-GO GLOBAL** para merge, despliegue y pagos reales se mantiene. Rafa gestiona exclusivamente la facturación externa; esta app no genera facturas ni impone decisiones fiscales sobre IVA.
