# S01 · Auditoría independiente previa a integración — NO-GO

**Fecha:** 13 de octubre de 2026 (Europa/Madrid)  
**Repositorio:** `MarianoSevilla/fiscal-cripto-`  
**Rama auditada:** `integration/s01-paypal-retirement-alembic-gate`  
**SHA auditado:** `8133e6615654c690a04585b1b59ff59b23ddc461` (PR #41)  
**`main` verificado:** `56882073295faae3bd1bc3632288a970acb330da`  
**Ámbito:** PR #33 → #34 → #35 → #36 → #37 → #39 → #40 → #41, dependencias PREFREEZE #30 y firma Stripe #32; revisión de U04 PayPal #29 en lectura.  
**Resultado:** **NO-GO para MERGE y DEPLOY; NO-GO para cobros reales.**  
**Naturaleza:** auditoría estática del código + revisión de Git y de CI ya ejecutada. **No se accedió a la BD productiva, Stripe Live, PayPal, Railway, MERU ni expedientes reales.**

## 1. Resumen y distinción de amenazas

Los componentes S01 están aislados para pruebas sintéticas, sin rutas públicas operativas para cobrar. La suspensión PREFREEZE responde 503 en el webhook Stripe y los endpoints legacy. La CI de la PR #41 es **verde**: [Required CI #51](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38315552501), **1.413 passed / 63 skipped**, PostgreSQL 18 y navegador aprobados.

**No se ha constatado ninguna explotación activa ni un cobro duplicado real.** Las debilidades de abajo son riesgos **de futura habilitación**. Nunca eliminar PREFREEZE ni fusionar/desplegar el conjunto simplemente porque la CI sea verde. La aplicación mantiene su objetivo de **NO emitir facturas fiscales**: las administra Rafa externamente; el análisis fiscal/contractual del destinatario del cobro queda fuera de este cambio de software.

## 2. Hallazgos bloqueantes (orden de resolución)

### S01-AUD-001 — CRÍTICO: reemitir presupuesto borra evidencia PayPal

**Evidencia:** `fiscal_app_export/app.py:4901–4964`; dentro de `advisory_enviar_presupuesto` se permite estado `quote_sent` y se ejecuta `advisory.paypal_order_id = None` y `advisory.paypal_capture_id = None` en líneas ~4941–4942. Aunque PayPal se haya retirado como proveedor, puede existir evidencia histórica o resultado incierto vinculado a esos campos. `advisory_s01_test_orchestrator.py:83–87` y `advisory_s01_stripe_test_events.py:145–148` bloquean basándose en dichas referencias.

**Situación actual:** no explotable mediante ruta pública: PREFREEZE bloquea el handler antes de ejecutarlo. **Riesgo de reactivación:** si se libera envío/renovación de presupuestos sin corregir ese código, la web podría borrar referencias financieras y permitir un intento Stripe que debió quedar retenido para conciliación.

**Exigencia:** eliminar esa limpieza; hacer la sustitución de presupuestos **fail-closed** si hubo orden/captura, intento incierto, Checkout o pago de cualquier proveedor; preservar snapshot y rastro de auditoría inmutable. Añadir pruebas de reemisión, rollback y concurrencia. Mantener congelada la ruta hasta entonces.

### S01-AUD-002 — CRÍTICO: desplegar puede ejecutar DDL antes del gate

**Evidencia:** `fiscal_app_export/Procfile:1` ejecuta `python bootstrap_db.py && gunicorn …`; `fiscal_app_export/app.py:273–279` invoca `db.create_all()` al importar; `bootstrap_db.py` importa `app` antes de consultar revisión Alembic. Las revisiones S01 `x7...`, `y8...`, `z9...` usan `ADD COLUMN IF NOT EXISTS` y `CREATE TABLE IF NOT EXISTS`.

**Riesgo:** desplegar el código puede crear tablas/columnas reales en producción **antes** de validar la revisión o de completar el plan de migración. `IF NOT EXISTS` no prueba que tablas existentes tengan las constraints e índices esperados. Una ejecución CI sobre PostgreSQL sintético no equivale al esquema/data de Railway.

**Exigencia:** copia/restauración verificada y **aislada** de la BD; comparar schema y `alembic_version`, contadores no identificativos y constraints; ensayo real de upgrade, rollback operativo del despliegue y comprobación postmigración. Para el paso Live, desacoplar DDL de importación/arranque o introducir un gate de despliegue que impida DDL no autorizado. **No desplegar #41 antes.**

### S01-AUD-003 — ALTO: Checkout TEST podría rechazar el objeto real del SDK

**Evidencia:** `fiscal_app_export/advisory_s01_test_orchestrator.py:132–140` convierte objetos de sesión mediante **solo** `to_dict_recursive()`. En el mismo proyecto, `advisory_s01_stripe_test_events.py:43–54` corrigió expresamente la compatibilidad con Stripe Python 16 usando `to_dict()` antes de `to_dict_recursive()`. `test_advisory_s01_test_orchestrator.py:59–91` utiliza un proveedor que devuelve **dict**, no `StripeObject` real.

**Riesgo:** sesión remota creada correctamente pero respuesta considerada incierta; intento `uncertain`, imposible reintentar sin conciliación. La CI actual no detecta ese contrato de objeto. **No implica por sí mismo un doble cargo**, pero impide el flujo y puede producir sesiones huérfanas.

**Exigencia:** adaptar el conversor a la versión fijada del SDK, añadir fixture `StripeObject` de dicha versión y prueba de que el objeto pasa todas las validaciones; mantener bloqueo si falta respuesta. Revisión independiente antes de usar un adaptador real de Stripe Test.

### S01-AUD-004 — ALTO: el webhook público sigue siendo legacy, no el consumidor S01

**Evidencia:** `app.py:5122–5175` conserva `stripe_webhook` antiguo; PREFREEZE lo bloquea con 503. Bajo ese bloqueo hay lógica heredada que busca por `stripe_checkout_session_id` y llama a `_on_payment_completed` sin la correlación completa de S01; dicho finalizador está retirado y arrojaría 503/500. El consumidor seguro de `advisory_s01_stripe_test_events.py` no está conectado a `app.py`; `advisory_s01_test_http.py:21–70` solo monta una ruta sintética en Flask testing.

**Riesgo:** retirar el decorador sin sustituir el handler no habilita pagos correctos. Además, el handler legacy podría perder eventos distintos de `checkout.session.completed` respondiendo 200.

**Exigencia:** crear/revisar ruta HTTP Stripe específica de S01 que use cuerpo bruto, firma, estado y montos, recibos, transacción única y política de errores; conservar bloqueado el endpoint anterior y no redirigir automáticamente tráfico de Stripe Test/Live. Ensayo end-to-end **sin cobros reales**, con autorización específica del entorno.

### S01-AUD-005 — ALTO: cierre financiero PayPal no verificado externamente

**Evidencia:** PR #41 desactiva el código PayPal manteniendo columnas históricas `paypal_order_id`, `paypal_capture_id` y proveedor. La PR #29 U04, con conciliación de pagos potencialmente cobrados, permanece abierta y no integrada. La auditoría actual **no ha consultado** la cuenta PayPal ni una copia actualizada de producción.

**Riesgo:** una orden autorizada, captura o reembolso pendiente debe poder documentarse sin resucitar endpoints PayPal ni eliminar IDs. El histórico de BD por sí solo tampoco prueba el estado del proveedor.

**Exigencia:** cierre firmado/registrado de **solo metadatos no personales**: conteos de órdenes, capturas y estados inciertos en BD, contraste autorizado con operaciones del proveedor y procedimiento manual de discrepancias. No afirmar cero operaciones sin esa evidencia contemporánea. Mantener la PR #29 sin fusionar/cerrar hasta decisión específica.

### S01-AUD-006 — ALTO: rutas de presupuesto y consentimiento sin transición S01 completa

**Evidencia:** `app.py:4901–4979` permanece PREFREEZE, crea presupuesto y puede enviar correo si algún día se reabre; `/api/pago/iniciar/<token>` (líneas 5098–5103) es ahora un stub siempre denegado. El orquestador TEST crea una reserva pero **no registra** `quote_accepted_at` ni prueba aceptación expresa del cliente (`models.py:248–250`). La página `/pagar/<token>` continúa en mantenimiento.

**Exigencia:** diseñar un endpoint nuevo, autenticado o validado por token, para aceptación explícita del precio total, expiración, acceso sin sesión, rate limits y registro de consentimiento; evitar retorno de éxito como fuente de verdad del pago. Reintroducir solo tras las correcciones #001–#005 y tests de abuso.

## 3. Pendientes relevantes antes de Live

- **S01-AUD-007 — Emails:** `S01StripeNotificationOutbox` garantiza dos **registros** pendientes por pago en la transacción, no la entrega exactamente una vez. No hay worker ni política de reenvíos, errores y recuperación entre envío y ACK; no afirmar notificaciones enviadas. `models.py:361–387`.
- **S01-AUD-008 — Incidencias financieras:** falta cobertura completa de `refund`, `dispute`/`chargeback`, conciliación de sesiones `creating/uncertain`, timeout de idempotencia, eventos fuera de orden y caídas tras COMMIT del proveedor. La prueba multiproceso PG18 verifica carreras, pero no todos estos escenarios.
- **S01-AUD-009 — Distinción TEST/Live:** `FLASK_ENV=testing`, `is_test=True` y `cs_test_` hacen que el código actual sea deliberadamente NO apto para producción. No convertirlo en Live eliminando simples prefijos o guards; crear adaptador de producción con su propia revisión.
- **S01-AUD-010 — Operativa de fondos:** el IBAN virtual de MERU figura registrado previamente en Stripe, pero **no hay evidencia en esta auditoría de payout recibido**, compatibilidad definitiva, límites ni conciliación EUR→USDC; verificar esos aspectos antes de cobros Live con autorización explícita.
- **S01-AUD-011 — Facturación externa:** la aplicación no factura, conforme a la decisión del propietario. Fuera del código, Rafa y el titular de Stripe deben aclarar su respectiva responsabilidad contractual/fiscal cuando la cuenta Stripe cobre el **total** y después se abone a Rafa. No añadir módulo de facturación a S01 sin nuevo encargo.
- **S01-AUD-012 — Disponibilidad:** PREFREEZE bloquea también tareas administrativas de presupuestos, cambios de estado y notas. No retirar el bloqueo de todas las rutas en una sola operación; restaurarlas de forma granular tras una matriz de permisos/estados.

## 4. Evidencias positivas — lo que SÍ se ha verificado

| Área | Evidencia revisada | Resultado |
| --- | --- | --- |
| Git | `main = 56882073295faae3bd1bc3632288a970acb330da`; todas las PR auditadas abiertas, DRAFT y sin merge | Conforme |
| Dependencias | PR #41 desciende linealmente de #40, y las etapas S01 encadenan sus cambios | Conforme, no integradas |
| CI | Run #51, head `8133e6615654c690a04585b1b59ff59b23ddc461`; 1.413 passed, 63 skipped | Conforme (sintético) |
| Postgres 18 | Carreras simultáneas sobre eventos firmados, deduplicación, outbox y rollback | Conforme en CI |
| Alembic | Un solo head S01 `z9a0b1c2d3e4`, sin rama #29; DDL sintético conserva referencias PayPal | Conforme en CI |
| PREFREEZE | Stripe webhook, PayPal legacy, páginas de cobro y administración crítica quedan congelados | Conforme en árbol auditado |
| Datos de pago | Sin eliminación deliberada de columnas PayPal ni backfill ficticio de comisiones | Conforme en migraciones |

**Importante:** el gate de migración CI ensaya una **tabla histórica mínima sintética**; no certifica ni restaura una copia productiva completa.

## 5. Secuencia propuesta de remediación

1. **No tocar producción.** Mantener PREFREEZE, PR #29 sin alterar y PR #41 en DRAFT.
2. Corregir **#001** antes de restaurar emisión/renovación de presupuestos; probar que nunca se borran IDs de proveedor.
3. Corregir **#003** con StripeObject real del SDK y caso de respuesta incierta.
4. Diseñar e implementar **#004 + #006** como ruta Stripe nueva y aislada, sin reutilizar el finalizador legacy.
5. Completar el cierre documental **#005** y el ensayo desde copia restaurada **#002**, sin datos reales en los informes.
6. Implementar outbox dispatcher y reconciliación de incidentes **#007–#008** y pruebas end-to-end de S01 TEST con autorización delimitada.
7. Revisión independiente de seguridad, titularidad de cobro y matriz de release; solo después solicitar autorización **separada** para merge, cambios de variables, migración, deploy y cualquier transacción real.

## 6. Veredicto y límites del encargo

- **Aprobado para:** análisis, correcciones aisladas y tests CI sin servicios reales.
- **NO aprobado para:** merge, migraciones en Railway, despliegue, alteración de secrets/webhooks, Checkout real/TEST externo, emails reales ni pagos/capturas/payouts.
- **Próxima implementación aconsejada:** PR de remedio de **S01-AUD-001** y **S01-AUD-003**, seguidas de pruebas de regresión. Sin tocar producción.
- **Condición de reapertura:** todos los hallazgos bloqueantes resueltos y comprobados, evidencia PayPal externa y ensayo de migración restaurada.

**Dictamen final: NO-GO.** Este dictamen **no declara un incidente financiero**, sino insuficiencia de evidencia y controles para el paso de prototipo TEST a integración productiva.
