# Cierre de seguridad previo al rediseño UX/UI — Auditoría técnica y propuesta de consolidación

**Fecha:** 13/10/2026 · **Resultado:** INVENTARIO CON EVIDENCIA / NO-GO para integración o despliegue sin autorización específica.
**Objetivo:** terminar la fase de endurecimiento sin perder código en ramas, dejar un `main` conocido y estable para Codex, separar claramente seguridad operativa S01 y futuras funcionalidades Stripe Connect/S02.
**Método:** inspección GitHub (PR, SHA, archivos, CI, ancestros) y Railway (identificación de entornos, ramas, despliegues, nombres de variables **sin leer valores**). **No se han ejecutado SELECT en bases**, consultas de pedidos al proveedor, HTTP financiero, cambios de configuración, migraciones, cierres de PR, merges ni despliegues.

## 1. Verificación de producción y staging, 13/10/2026

| Parámetro | Producción | Staging |
| --- | --- | --- |
| Proyecto Railway | `fiscal-cripto` | `fiscal-cripto` |
| Environment | `production` | `staging` |
| Servicio web | `fiscal-cripto-` | `fiscal-cripto-staging` |
| Rama desplegada | `main` | `security/staging-preflight-isolation-20261012` |
| SHA de despliegue | `56882073295faae3bd1bc3632288a970acb330da` | `f421a9c21f99267eb0aedf05705c93b62fba3ba9` |
| Despliegue web | `SUCCESS` 11/10/2026 17:03 UTC | `SUCCESS` 12/10/2026 18:06 UTC |
| Base de datos | `Postgres`, PostgreSQL 18 | `Postgres-zZky`, PostgreSQL 18 |
| Staged Railway patch | Ninguno | Ninguno |
| Coincide con `main` actual | Sí | No, por diseño de aislamiento |

**Hecho crítico:** la PR #31 `STG-LOCK-001` sigue `draft / unmerged` en GitHub **pero su SHA está desplegado en staging**. Tener PR en borrador no significa que ese código no esté desplegado en ningún entorno. **El staging actual está dedicado al aislamiento y rechaza operaciones según su diseño; no está preparado por sí mismo para probar pagos S01 reales/simulados desde navegador**. Un futuro staging operativo requiere una intervención específica, respaldos y validación de aislamiento, sin alterar producción.

Railway presenta **nombres** `FLASK_ENV`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `PAYPAL_ENVIRONMENT` en la web de ambos entornos; **no se han leído sus valores**, ni se afirma que los secretos sean correctos, que Stripe Test/Live esté activo o que PayPal esté desactivado. `ENABLE_ADVISORY_UPLOADS` no aparece en la lista y en el código su valor por defecto es `false`; verificar valores efectivos antes de declararlo certificado.

**Límite:** un deployment `SUCCESS` acredita ejecución del contenedor, **no** ausencia de operaciones financieras, firma/configuración efectiva del webhook, versión Alembic ni inexistencia de datos sensibles. No se consulta ningún fichero CSV ni se revelan credenciales o usuarios.

## 2. Qué está integrado y qué no

**En `main`, incorporadas y desplegadas:** PR #23 CI requerida, #24 actualización de GitHub Actions, #25 runtime Python bloqueado, #26 U01 logging PayPal seguro, #27 U02 secretos/cookies fail-closed, #28 U03 validación identidad Google OIDC. También hay anteriores mejoras responsive ya fusionadas; comprobar comportamiento visual en pruebas antes de cambiar frontend.

**NO integradas en `main`:** #19, #22 y todas las PR #29–#55 relevantes: PayPal U04, PREFREEZE, firma Stripe, staging lockdown (aunque deployed a staging), S01 synthetic, G04, G06, Connect, auditorías. Sus resultados de CI corresponden a SHA de ramas, **no a la web en producción**.

**Riesgos del código productivo aún visibles por lectura de `main`:**
- `Procfile` sigue iniciando `python bootstrap_db.py` antes de Gunicorn. La corrección #49 elimina DDL de startup, pero exige head Alembic correcto y puede impedir arranque hasta migración administrada y ensayada.
- `app.py` conserva rutas de creación/captura PayPal y webhook Stripe, cuyo antiguo código contempla alternativa `json.loads` si falta el secreto de firma. **No se ha probado si el caso de secreto faltante sucede en producción**. No afirmar explotación ni cobros.
- `/api/admin/asesoramiento/solicitudes/<id>/enviar-presupuesto` en `main` aún emite `/pagar/<token>` sin la secuencia final acordada. El futuro S01 cambia UX: presupuesto → aceptación → enlace Stripe Connect → cobro confirmado.
- Los sistemas de bloqueo financiero de PR #30 y #41 **alteran deliberadamente el comportamiento del producto S01**, aunque conservan la captación inicial. No llamarlos “cambios sin efecto funcional”.

## 3. Topología de ramas, solapamientos y alternativas excluyentes

### Ruta S01 de Stripe-only propuesta anteriormente (en código, no autorizada para merge)

```text
main (56882073)
  └─ PR #33 → #34 → #35 → #36 → #37 → #38 → #39 → #40 → #41
                                                   └─ #43 → #44 → #45 → #49
                                                                      └─ #50 → #51 → #52 → #53 → #54
```

La representación anterior recoge relaciones de ascendencia y trabajo sucesivo; **las bases actuales de algunas PR siguen siendo `main` por fines históricos de CI**, por lo que no se debe fusionar ciegamente usando solo el `base` de GitHub. La cadena está orientada a **PayPal ejecutable retirado y Stripe sintético**, NO a la nueva arquitectura final de Stripe Connect y gastos 30/70. #54 calcula **50/50 y está declarada obsoleta**. #42 y #46 son auditorías documentales; #47/#48 son evidencia opcional PayPal.

### Incompatibilidades / repetición comprobada

| PR / paquete | Relación confirmada | Acción propuesta, NO ejecutada |
| --- | --- | --- |
| **#29** (U04 PayPal activo seguro) vs **#41** (PayPal retirado) | `compare` marca `diverged`, merge base `56882073`; ambos intervienen en `app.py` y comportamiento de cobro; diseños diferentes | **Elegir uno solo**: para Stripe Connect futuro y sin pagos PayPal documentados, estudiar #41 previa comprobación agregada G05; conservar #29 en histórico, no integrar ambos |
| **#30** (PREFREEZE) vs **#41** (incluye PREFREEZE) | `diverged` desde main; `app.py` y `pagar.html` solapados | No aplicar PR #30 nuevamente sobre un árbol que ya incorpora las mismas barreras; usar prueba de equivalencia y decidir si es necesario un hito corto independiente |
| **#32** (firma Stripe) vs **#41** (incluye código de firma) | `diverged`, archivos `app.py` / tests solapados | Verificar que la firma obligatoria permanezca antes de liberar un handler futuro; no duplicar cambios |
| **#31** (staging) | Aislada desde `main` y **desplegada en staging** mientras sigue draft | Mantener staging protegido; no usar esta PR como prueba de que las PR financieras estén en ese entorno |
| **#41 → #49** | Comparación de SHAs da `ahead 37, behind 0`; G04 incorpora código sobre la ruta de #41 | No desplegar #49 aislada, porque gate READ ONLY requiere migraciones S01 explícitas en esquema compatible |
| **#49 → #52** | `ahead 13, behind 0`; consentimiento/reserva sintética extendida | Técnicamente probado solo en TEST; secuencia real y contrato Connect por revisar |
| **#54** | Implementa reparto del gasto 50/50, supersedido por decisión 30 % Mariano / 70 % Rafa | Mantener evidencia histórica, **NO FUSIONAR SU FÓRMULA** |

**Colisiones de alto riesgo:** `fiscal_app_export/app.py` (#29/#30/#31/#32/#41/#43/#49), `fiscal_app_export/models.py` (#29/#41), `fiscal_app_export/Procfile` (#49), `bootstrap_db.py`, migraciones Alembic (ramas U04 vs Stripe-only), `static/pagar.html`, `.github/workflows/required-ci.yml`, tests HTTP/PG18. La etiqueta GitHub `mergeable=true` si apareciera no demostraría compatibilidad semántica, ni estabilidad operativa.

## 4. Pruebas disponibles verificadas por SHA

| Paquete | Commit | CI Required | Alcance |
| --- | --- | --- | --- |
| #30 PREFREEZE | `90519912…` | #23 `SUCCESS` | Backend/PG18/navegación, suspensión financiera |
| #31 staging lockdown | `f421a9c2…` | #30 `SUCCESS` | Staging aislamiento, NO validación financiera |
| #32 Stripe firma obligatoria | `530a32de…` | #33 `SUCCESS` | Webhook legacy, firma obligatoria |
| #41 retirada PayPal + S01 synthetic | `8133e661…` | #51 `SUCCESS` | 1.413 backend, PG18, navegador |
| #49 G04 | `b19cb103…` | #71 `SUCCESS` | 1.457 backend, gate schema READ ONLY, no DDL startup |
| #49 Mac restauración real | mismo SHA | `S01 REHEARSAL: PASS`, comunicado por el propietario | **Copia privada restaurada localmente**, no Railway prod |
| #52 AUD-001/002 | `e2953d11…` | #75 `SUCCESS` | 1.482 backend, 0 xfailed, concurrencia PG18 sintética |
| #53 contrato G06 | `4b02ebfc…` | #76 `SUCCESS` | 1.535 backend, pruebas puras; sin aprobación comercial |
| #54 Connect 50/50 **superado** | `f653f6a1…` | #78 `SUCCESS` | 1.564 backend, pero fórmula económica antigua |
| #55 auditoría de negocio | commit documental precedente | #81 `SUCCESS` | Documentación, no seguridad integrada |

**Interpretación:** CI verde por rama no acredita que una futura combinación de PR sea equivalente o segura para desplegar en Railway. Habrá que reproducir Required CI, migraciones y verificación de rutas con el **SHA compuesto final**.

## 5. Cinco fases ejecutables de cierre, con puertas y permisos separados

### C0 — Fijar baseline y no perder nada — **AHORA, sin cambiar runtime**

- Registrar SHA exacto de `main`, último deployment en Railway y cadenas de PR existentes en este archivo.
- **No cerrar ni borrar ramas/PR todavía**. Antes de clausurarlas se debe decidir, en una tabla, si su código se incorpora en la rama canónica, se sustituye por otra versión o se conserva como evidencia. No hacer squash ciego ni merge múltiple.
- Proteger la cadena #41→#49→#53 como referencia histórica y evitar que Codex para UX trabaje sobre una rama de pagos. Cualquier cambio de `main` requerirá actualizar la línea base y revalidar impacto.
- Este archivo queda en la PR #55 (sin abrir otra PR). Ningún tag ni cierre administrativo automáticos.

### C1 — Elegir estrategia PayPal / definir primer cambio seguro — **PENDIENTE DE APROBACIÓN**

- Distinguir **endurecimiento sin cambio visible significativo** (por ejemplo firma obligatoria de webhook) y **suspensión deliberada del negocio S01** (PREFREEZE bloquea envío de presupuestos, acciones administrativas y ruta de pago, aunque mantiene solicitud).
- Decidir expresamente **retirada PayPal (#41)** frente a mantener motor U04 (#29). La decisión de producto apunta a Stripe Connect y Rafa como comerciante, pero no equivale a autorización técnica de retiro; verificar antes el inventario actual agregado de órdenes y capturas.
- Para minimizar riesgo inmediato, evaluar un *paquete mínimo* sin DDL: firma fail-closed #32 + barrera S01 #30, **si se acepta que parte del panel quede temporalmente suspendido**. Si la política exige mantenerlo íntegramente, no presentar ese paquete como “sin cambio funcional”. No fusionar ambas PR independientes sin revisar `app.py`.
- Criterio de cierre: DIFF unificado auditado, sin credenciales, sin pagos, sin nuevos heads Alembic, CI backend/PG18/navegador, prueba de 503 sin accesos a proveedor y rollback no financiero. Autorizar por separado merge y deploy.

### C2 — Certificar producción para migraciones S01 y staging de ensayos — **PENDIENTE**

- Obtener **metadatos mínimos de solo lectura** de Railway variables mediante salida booleana en entorno seguro (valores de secretos no deben salir al chat). Comprobar `PAYPAL_ENVIRONMENT`, presencia y no-vaciedad de `STRIPE_WEBHOOK_SECRET` solo mediante comparación protegida, sin filtrar valores.
- En BD producción solo `SELECT` de `alembic_version`, existencia de tablas/constraints y **conteos agregados** por referencias financieras, sin nombres, email, CSV, orden completa, claves ni importes por expediente. No ejecutar migraciones en producción durante esta lectura.
- Confirmar aislamiento real de staging (base distinta, DNS/URL distinto, credenciales y webhook separados, sin datos de clientes). El staging actual bloqueado **no se puede tratar como banco de pruebas de pagos**.
- Restaurar backup verificado en PG18 privado y ejecutar migración administrativa propuesta con `G04`, luego gate read-only, dos veces y prueba de fallo pre/post COMMIT. Controlar despliegue sin DDL.
- Todos estos accesos/cambios operativos requieren autorización separada según alcance. La copia histórica del 10/10 y rehearsal G04 PASS **no prueban los datos actuales**.

### C3 — Integración final de seguridad con SHA nuevo — **PENDIENTE**

- Preparar una **única rama de integración** desde `main` actualizado que contenga solo funciones autorizadas para esta versión. Resolver solapamientos por diseño, no por precedencia accidental de merges.
- Mantener componentes validados: bloqueo de escrituras, firma obligatoria, no reemitir/capturar pagos inciertos, no DDL en startup, control de esquema, rechazo de rutas legadas, contabilidad histórica e idempotencia.
- **Excluir del release de seguridad** el modelo económico Connect obsoleto (#54), SDK externo Stripe y UI de cobros no aprobada; las PR de laboratorio #50–#53 se conservan como referencias, no como compromiso de release.
- Ejecutar Required CI completa sobre SHA final, PG18 multiworker/rollback, secuencia de arranque y QA responsive de rutas afectadas; comparar el listado total de archivos y las migraciones con el plan aprobado.
- Antes del merge: informe de revisión independiente, plan de rollback *compatible con migraciones aditivas*, sin eliminar historial ni restaurar binarios viejos que puedan aceptar pagos inciertos.

### C4 — Desplegar, comprobar y cerrar PR **por autorización expresa**

- Deploy a entorno staging realmente certificado con sus propias credenciales/datos ficticios, smoke test de salud + rutas financieras bloqueadas, revisión de logs minimizados, pruebas UI y no egress a PayPal/Stripe.
- Solo entonces elevar a producción con ventana controlada, backup reciente restaurable, migración administrativa si se requiere, publicación de SHA con procedencia probada y verificación posterior. **No realizar ninguna de estas acciones con la autorización genérica de auditoría.**
- Confirmado el release en producción: decidir cierre administrativo de PR históricas redundantes, manteniendo SHAs/referencias y, cuando proceda, ramas. **Cerrar una PR no borra necesariamente su historial; borrar la rama sí puede perjudicar recuperación.** Documentar de dónde provino cada defensa integrada.
- **Condición para entregar a Codex UX/UI:** `main` y Railway production en mismo SHA estable, sin despliegue en curso, sin PR de seguridad pendientes para fusión, sin cambios staged, CI verde de main, y ventana de cambios financieros congelada. Unas PR históricas cerradas/conservadas no ponen en peligro al rediseño si Codex crea rama limpia desde el SHA fijado.

## 6. Tabla de decisiones GO/NO-GO

| Gate | Estado hoy | Evidencia necesaria |
| --- | --- | --- |
| C0 baseline GitHub/Railway | **PASS INVENTARIO** | SHAs y deployment enumerados arriba |
| C1 elección PayPal: retirado vs U04 | **NO-GO** | decisión explícita + conteos actuales limitados |
| C1 cambio mínimo de firma/PREFREEZE | **NO-GO** | aceptar comportamiento funcional de mantenimiento; integración y CI |
| C2 valores efectivos de secretos sin revelar | **PENDIENTE** | prueba booleana solo lectura, salida anonimizada |
| C2 Alembic prod y G05 contadores actuales | **PENDIENTE** | SELECT de metadatos, sin PII |
| C2 staging apto para QA financiero | **NO-GO** | certificar aislamiento, adaptar política de lockdown con permiso |
| C3 rama de seguridad final | **NO INICIADA** | autorización de alcance, CI y revisión |
| C4 merge / deploy / migración / rollback | **NO AUTORIZADO** | autorizaciones y verificación por hito |
| UX/UI Codex baseline estable | **PENDIENTE** | C1–C4 terminados o cambio de alcance aprobado para separar la seguridad |

### Resumen operativo

**No falta trabajo técnico por defecto: falta elegir, consolidar, certificar e integrar el código ya escrito.** No cerrar PR en masa ni desplegar #49 directamente. La primera decisión de seguridad es si suspender temporalmente las operaciones S01 hasta que Stripe Connect esté auditado, y si retirar PayPal ejecutable de la nueva línea. Es preferible una consolidación por dos releases controlados que una mezcla de todas las PR y la reforma UX.
