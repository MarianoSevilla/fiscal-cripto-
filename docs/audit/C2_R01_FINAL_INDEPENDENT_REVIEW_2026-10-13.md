# C2-R01 — Revisión independiente final de la implementación y dependencias S01

**Fecha:** 13/10/2026 · **Tipo:** auditoría de solo lectura en GitHub; cambios documentales únicamente.  
**Veredicto:** **CORRECCIONES C2-01 A C2-05 ACEPTABLES BAJO ALCANCE C1 / NO-GO PARA MERGE Y PRODUCCIÓN**.

## 1. Fuentes y SHA certificados

- `main` GitHub consultada: `56882073295faae3bd1bc3632288a970acb330da` (sin cambios observados). **No se ha comprobado Railway en esta revisión**.
- PR #56 C1: `598bb0912ad0dc4521aaba881512b13aa268b4eb`, draft, sin fusionar.
- PR #57 C2-R01: `3945a97eac76451579c95e90fe571bbdf1f7c05e`, draft, base PR #56, sin fusionar.
- Diff específico #57 sobre #56: **3 commits, 8 archivos**, incluido paso CI PG18. Sin migración, Procfile, secretos, cuenta bancaria o código de proveedor externo nuevos.
- Diferencial acumulado respecto a `main`: **77 commits y 72 archivos** (incluye todas las capas apiladas entre retirada PayPal, migraciones S01, prefessure/PREFREEZE, G04, G06, G07, tests y C1/C2). No es una PR autónoma desplegable sobre el esquema viejo.
- CI **#86**: https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38411560214 · status **SUCCESS** en el SHA exacto anterior; **1.556 passed, 63 skipped** en Python, PostgreSQL 18 SUCCESS y browser-navigation SUCCESS.
- Logs PostgreSQL 18: import/arranque sin DDL e inspección READ ONLY PASS, Alembic un solo head PASS; `C2-R01 PG18`: bloqueo de fila real en dos procesos PASS, rechazo con evidencia parcial comprometida PASS, rollback y posterior transición PASS; sin proveedores/ emails/cargos en esa prueba.

## 2. Evaluación de cada remediación

| Hallazgo original | Resultado de revisión de #57 | Alcance/límite |
|---|---|---|
| C2-01 — evidencia histórica incompleta | **RESUELTO para cambios internos C1** | `advisory_s01_c2_management.py` comprueba 19 campos principales/secundarios; intentos Stripe; estados previos no internos y acciones financieras de auditoría. Sin borrar ni reescribir historial. |
| C2-02 — sin bloqueo PG18 específico | **RESUELTO para la carrera sintética probada** | `qa_s01_c2_management_pg18.py` usa dos procesos y conexiones sobre DB efímera; no es prueba de todos los futuros escritores Stripe ni de una BD real. |
| C2-03 — panel y backend en desacuerdo | **RESUELTO** | Detalle retorna `c1_state_editable` y el panel lo usa. POST recalcula el criterio bajo `SELECT FOR UPDATE` sin confiar en UI. |
| C2-04 — importes fijos publicados | **PARCIAL** | No hay importes nuevos en la landing; `/api/asesoramiento/precios` ahora responde 503/no-store. Quedan mensajes contradictorios de plazos/confirmación; ver C2-F01. |
| C2-05 — estados que suponen mensaje enviado | **RESUELTO para transiciones nuevas** | Solo se puede pasar a `submitted` o `under_review`; estados previos `pendiente_info` y `waiting_user_info` se conservan y pueden volver a revisión. La ruta de mensaje externo sigue en PREFREEZE. |
| C2-06 — evidencia de información legal | **PENDIENTE (privacidad)** | Flujo heredado de checkbox cliente no prueba/versiona aceptación en servidor; no presumir infracción ni añadir PII sin análisis jurídico. |

**No se identifica una nueva ruta C2 de creación/captura de PayPal, aceptación/cobro Stripe, emisión de presupuesto ni envío de email de cambio de estado.** La admisión `/api/asesoramiento/solicitar` conserva emails de recepción/aviso interno (C1 los permite); la nueva nota y estado no generan emails. Las rutas heredadas de presupuesto, mensajes externos, capturas, webhooks y pago siguen suspendidas mediante `advisory_financial_prefreeze`. La retirada ejecutable de PayPal persiste en el árbol.

## 3. Hallazgos nuevos/remanentes: impiden certificar experiencia S01 completa

### C2-F01 — MEDIA · Mensajes públicos contradictorios durante C1

1. `fiscal_app_export/static/asesoramiento-fiscal.html`, línea 415: «Rafael te dará respuesta en 2–3 días hábiles». La misma página afirma que se han suspendido presupuestos y pagos y no existe canal automático para valorar plazo real de respuesta.
2. `fiscal_app_export/static/asesoramiento-confirmado.html`, línea 99: «Hemos recibido tu solicitud y tu pago». Sigue disponible desde una ruta GET `/asesoramiento-fiscal-confirmado` sin comprobación de pago en `fiscal_app_export/app.py` (aprox. 4706–4709). **No se ha detectado creación de cobro por esta vía**: es un mensaje de confirmación antiguo accesible directamente, que puede inducir a error.
3. El panel del asesor incluye textos de prioridad heredados como «Pendiente de presupuesto» y «Esperando pago» (aprox. líneas 401–405) y CSS de respuestas presupuestarias no usadas. Son problemas de coherencia visual, no evidencia de cobros activos.

**Cierre:** actualizar copia pública/promesas, retirar o neutralizar confirmación de pago sin verificación, revisar microcopy de panel, ensayar enlaces directos y vistas móvil/escritorio. No permitir una nueva URL/operación de pago.

### C2-F02 — MEDIA · E2E del frontend C1 no demostrado

- `tests/test_s01_c1_management.py` verifica APIs mediante cliente Flask y aserciones estáticas del HTML, con casos de roles, CSRF, históricos parciales y admisión. Esa evidencia es válida para backend.
- El job `browser-navigation` ejecuta `tests/qa_responsive_nav.py`, cuyo navegador automatizado cubre navegación principal, menú responsive y autenticación sintética, **no** la secuencia de panel asesor `gestion-token → gestion/nota/estado` ni la UI financiera suspendida.
- La CI verde **no equivale** a cobertura de cliente real, sesión, responsive y ausencia de enlaces de cobro en todas las pantallas de asesoramiento.

**Cierre:** E2E aislado con navegador real y datos ficticios: login asesor/admin, formulario, ficha editable/protegida, token CSRF, nota, cambio de estado, bloqueo de presupuesto/enlaces/PayPal, vistas móvil/escritorio; sin red externa ni datos de clientes.

### C2-F03 — SEGUIMIENTO · Verificaciones de edición futura y semántica interna

- `c2_change_internal_state` permite `under_review → submitted`. Es una transición exclusivamente interna y no reabre cobros, pero conviene precisar si es una marcha atrás válida o si la revisión debe avanzar en un solo sentido.
- `c2_can_change_state` asume que futuros escritores de evidencia financiera respetarán el bloqueo por la misma fila padre. Es correcto dentro del PREFREEZE actual; su garantía **no se extiende automáticamente** a una nueva arquitectura Stripe Connect aún no integrada.
- El frontend cachea token CSRF hasta recarga; las pruebas cubren rechazo de token inválido, no un flujo completo de cierre de sesión/reautenticación en navegador. De bajo riesgo mientras el backend ligue token a sesión/usuario, pero probar el caso real.

## 4. Auditoría de cadena y gates operativos

### G04 — esquema/arranque

- `Procfile` prepara `python startup_schema_gate.py && gunicorn ...`.
- `startup_schema_gate.py` exige PostgreSQL, revisión exacta `z9a0b1c2d3e4` y constraints/índices. No hace DDL; falla cerrado si la DB conserva un head previo.
- `bootstrap_db.py` es entrada administrativa separada. **Nunca** desplegar código con gate nuevo antes de verificar y aplicar las migraciones S01 autorizadas, bajo corte operativo y controles de respaldo/rollback.
- La PR #49 registra un **segundo ensayo G04 PASS reportado por el propietario en su Mac** sobre respaldo privado de 10/10/2026 y SHA `b19cb1030e2ff5c5f9e297311af6661e34075e62`. Esta evidencia mejora la confianza técnica pero **no es verificación independiente del estado actual de producción ni autorización de migración**.
- La documentación de la rama #49 conserva el primer NO-GO histórico; el PASS posterior consta en el **cuerpo de la PR**, no reescribir retroactivamente el incidente.

### G05 — legado PayPal

- PayPal S01 está retirado como método futuro; PR #29 U04 conciliación PayPal alternativa y su head Alembic `w6x7y8z9a0b1` NO deben fusionarse en la cadena S01.
- En PR #47/#48 se registra, por comunicación del propietario, inventario offline del backup 10/10/2026 con **6 expedientes, 0 señales de orden/captura PayPal**. El propietario declaró que no se realizaron cobros PayPal mediante marianosevilla.com.
- Se acordó un cierre **proporcional**, no exigir por defecto exportar todos los movimientos históricos de todas las cuentas personales PayPal. **Sigue pendiente** una comprobación limitada, agregada y autorizada de la **BD actual** antes de producción para detectar novedades posteriores al backup; contrastar con proveedor **solo si aparecen indicios contradictorios o inciertos**. No convertir ausencia de registros históricos en certeza de ausencia de operaciones externas.

### Dependencias, staging y Connect

- Las PR de la cadena S01 revisadas continúan abiertas y draft, sin fusionar. #57 depende directamente de #56, que depende de #53, y de una larga secuencia que modifica migraciones/arranque. No fusionar PR por separado ni hacer fast-forward de la cabeza completa sin plan de incorporación lineal.
- #54 Connect con reparto 50/50 de costes es **obsoleta** y está excluida del árbol #57. El acuerdo indicado por el propietario es comisión del 30 % **sobre honorarios Rafa**, y procesamiento de Stripe 30 % propietario / 70 % Rafa. Esto todavía necesita implementación posterior válida, no inferir que la rama C2 activa pagos.
- El staging aislado anterior y la CI sintética no constituyen un ensayo autorizado con datos operativos ni un switch de pagos Live.
- Debe prepararse un plan de corte por SHA, backup actualizado, revisión agregada de migraciones/estado, mecanismo de reversión del aplicativo sin deshacer evidencia o cambios financieros y autorización separada explícita para cada escritura productiva.

## 5. Dictamen y trabajos propuestos

**C2-R01: aprobado como corrección técnica aislada de C2-01, C2-02, C2-03 y C2-05; C2-04 parcial por microcopy heredada; C2-06 sigue en seguimiento legal.**
**NO-GO para merge, staging operativo, producción y pagos:** permanecen C2-F01/F02 y los gates G04/G05/chain/deploy.

Orden seguro:
1. Remediación acotada **C2-R02** de mensajes públicos/confirmación sin pago y E2E navegador sintético C1, y prueba de semántica de transiciones, en **otra rama apilada** (no reescribir SHA #57).
2. CI completa + PG18 y browser C1 sobre SHA final; auditoría de diff nueva.
3. Inventariar dependencias/colisiones y preparar secuencia de integración y plan operativo de migración/backup.
4. Solo con permiso separado, verificar metadatos agregados de Railway, ensayar staging y autorizar integración/despliegue en orden seguro.

**Este informe:** documenta únicamente lectura GitHub/CI y dictamen. No cambia la PR funcional #57, `main`, Railway, esquema, claves, Stripe, PayPal, MERU, datos de clientes, emails, facturas o pagos.
