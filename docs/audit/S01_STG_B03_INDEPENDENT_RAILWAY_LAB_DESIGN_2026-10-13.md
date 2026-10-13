# S01 · STG-B03 — Diseño técnico del laboratorio Railway independiente

**Preparación de arquitectura · 13/10/2026 · DOCUMENTACIÓN EXCLUSIVAMENTE.**
**ESTADO: PREPARADO PARA REVISIÓN / NO-GO PARA CREAR O DESPLEGAR.**
Esta autorización **NO** incluye crear proyectos, entornos, servicios, volúmenes, dominios, costes recurrentes, variables, tokens, despliegues, migraciones, dumps ni transacciones. No existe un laboratorio Railway S01 creado por esta fase.

## 1. Evidencia fijada para no perder el trabajo existente

| Objeto | Identidad / estado verificado |
|---|---|
| Producción Railway, GitHub main | `56882073295faae3bd1bc3632288a970acb330da`; web online y PostgreSQL 18 independiente, no modificar |
| Staging Railway existente | Rama `security/staging-preflight-isolation-20261012`, pin / deployment `f421a9c21f99267eb0aedf05705c93b62fba3ba9`; no modificar |
| Candidato S01 + STG-LOCK | PR **#61**, SHA `e4b8fdec505f0893ec7f61bc89d7febc28e6d6a3`, DRAFT apilada sobre #60 |
| CI candidata | GitHub Actions `38437503533` SUCCESS: 1.812 Python PASS, 63 skipped; PG18 y arranque fail-closed PASS; 26 checks Chromium |
| BD staging existente | Servidor `postgres-zzky.railway.internal:5432/railway`, Alembic `v5w6x7y8z9a0`; 15 tablas (14 de aplicación + alembic_version) |
| Datos staging existente | 13 tablas de aplicación vacías, **1 fila en `resources`**; activa, con solicitud previa, sin `storage_key`. Ninguna fila registrada en usuarios/informes/contactos/asesoría/errores/comunicaciones/recursos solicitados/archivos/nota/auditoría. No borrar ni reproducir la fila como si fuera ficticia |

El host y la referencia de staging se confirmaron visualmente por el propietario, sin revelar secretos. El listado de 15 tablas y contadores corresponde a consultas **de solo lectura** realizadas en `Postgres-zZky`. Estos resultados **no otorgan autorización de escritura** sobre staging. La verificación de no existencia de registros en tablas específicas no prueba que no haya archivos u otras fuentes externas; no reutilizar su BD.

## 2. Arquitectura propuesta y topología de confianza

**Opción preferida: crear un proyecto Railway totalmente nuevo**, no clonar el proyecto actual ni crear otro servicio dentro de `production` o `staging`. Nombre humano propuesto: `fiscal-cripto-s01-lab`. Aislar proyecto, grupos de variables, permisos, redes y costes. La plataforma asignará IDs nuevos; **no inventar ni precargar IDs**. Si se plantea un ambiente dentro del proyecto actual, requerirá una nueva evaluación de propagación de referencias, red y permisos antes de cambiar este diseño.

Recursos a considerar **solo tras aprobación explícita de costes y alta de infraestructura**:

1. Servicio **PostgreSQL 18 propio** `s01-lab-postgres` y **volumen nuevo**, sin clonar volúmenes, backups o datos de producción/staging. Solo privado, sin exposición TCP pública. Base inicialmente sin tablas.
2. Servicio de aplicación **`s01-lab-web`**, desde rama independiente y SHA fijo, raíz `fiscal_app_export`, un único proceso/replica, comando de inicio `python startup_schema_gate.py && gunicorn ...` conforme al `Procfile` del candidato. **NUNCA** desplegar PR #61 tal cual: la protección `STG-LOCK-001` exige actualmente los identificadores de staging y no acepta la identidad del proyecto nuevo.
3. **Ejecutor de pruebas efímero** (o mecanismo equivalente dentro de la red del laboratorio, sujeto a viabilidad del proveedor), con Chromium/Flask y datos inventados. No tendrá acceso a las redes ni BD de otros proyectos. Debe poder hablar por red privada con web y BD *únicamente* para diagnósticos autorizados. No dejar ejecutores permanentes tras finalizar pruebas.

**Topología exigida:** usuario/ejecutor de laboratorio → web privada → DB privada y nueva. Sin dominios custom ni redirecciones hacia `marianosevilla.com`; no conectar proveedores externos ni reutilizar claves de Google/Resend/PayPal/Stripe. Evitar exponer dominio web público; si el procedimiento de pruebas necesita dominio, preparar previamente acceso restringido al banco de pruebas y verificar el bloqueo. No afirmar que Railway ofrece un cortafuegos de salida configurable sin evidencia documental/operativa. La ausencia de claves **no garantiza por sí misma** que toda salida de red sea imposible: añadir barrera de aplicación y pruebas instrumentadas de no-I/O externo.

**Costes:** web, PG18 y volumen consumen recursos aunque sean temporales. Estimar límites y duración desde el plan de Railway y obtener aprobación del propietario **antes de provisionar**. No atribuir una cifra sin cotización comprobada. Documentar política de parada y retirada del laboratorio.

## 3. Impedimentos del código actual y modificación futura imprescindible

- `security_config.py` permite sólo `development/testing` en local; **rechaza `FLASK_ENV=testing` si detecta Railway**. En laboratorio desplegado se utilizaría `FLASK_ENV=staging` *únicamente tras desarrollar una barrera de identidad específica* que reconozca el proyecto/env/servicio nuevos; el nombre de ambiente Railway no puede fingirse sin control.
- `staging_isolation.py` actual tiene **IDs exactos hardcoded** de la aplicación staging, `FLASK_ENV=staging`, `RAILWAY_ENVIRONMENT_NAME=staging`, host de BD `postgres-zzky.railway.internal` y dominio público fijo. Con ID de laboratorio nuevo el import de `app.py` **debe FALLAR CERRADO**; no desactivar ni rodear esta validación.
- Crear en **otra PR de código** una política `S01-LAB-LOCK` equivalente, auditable e inerte fuera del laboratorio. Debe identificar por **ID Railway de proyecto, entorno y servicio fijados como constantes confiables en el release**, no por una variable `LAB_MODE=true` manipulable. Los IDs reales se obtendrán **después** de autorizar crear recursos, pero **antes** de desplegar web. Incorporar host privado DB, puerto, BD, enlace a servicio nuevo, URL interna, controles de encabezados/healthcheck y lista de rutas permitidas; cualquier discordancia: NO-GO antes de `db.init_app` o de conectar con SQL. No reutilizar los IDs de staging existente.
- Preservar `STG-LOCK-001` original en el staging actual y que NO afecte producción. La política de laboratorio tendrá dos fases: **preflight** cerrado para todo POST/login/API salvo healthcheck; **test** con permisos explícitos solo para cuentas y datos *creados en la BD nueva*, y con finanzas, webhooks, callbacks y correo siempre cerrados. Pasar entre fases requerirá guardas de verificación de esquema/DB, prueba de origen e identidad, ausencia de datos reales y autorización; **no basta un flag solitario**.
- El código candidato ya aplica **PREFREEZE** a pagos Stripe/PayPal; se conserva. No rescatar flujos PayPal antiguos ni desactivar la protección para facilitar pruebas.
- Las pruebas actuales `qa_stg_b01_app_isolation.py` y `test_staging_isolation.py` validan staging ficticio, pero **no validan un nuevo proyecto Railway** ni una imagen recuperable desplegada. Requieren extensión cuando existan IDs y configuración aprobados.

## 4. Contrato de variables para el futuro proyecto (NO aplicar ahora)

| Variable o familia | Contrato propuesto | Comprobación |
|---|---|---|
| `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_ID`, `RAILWAY_SERVICE_ID` | Autogenerados en nuevo proyecto; cotejar con IDs compilados/fijados en `S01-LAB-LOCK` | Fallar cerrado ante ausencia o desajuste |
| `RAILWAY_ENVIRONMENT_NAME` | Valor real del nuevo entorno, no el nombre del staging anterior | Validación exacta |
| `FLASK_ENV` | `staging`, con guard del laboratorio específico | Nunca `testing` o `development` en Railway |
| `SECRET_KEY` | Nueva y exclusiva del laboratorio, almacenada en Railway, nunca copiar de prod/staging | Presencia, entropía y cookies Secure; no divulgar valor |
| `DATABASE_URL` | **Referencia de servicio Railway** a `s01-lab-postgres` del **mismo proyecto/entorno**, sin DSN literal en archivos | Revisar expresión de referencia *no resuelta* y verificar host + identidad efectiva sin imprimir contraseña |
| `APP_BASE_URL` | Host interno/canónico de lab aprobado; no URL de prod ni del staging actual | Coincidir con barrera Host/Origin |
| `PAYPAL_CLIENT_ID/SECRET/WEBHOOK_ID` | Ausentes o vacíos | 0 valores activos; no sandbox remoto |
| `STRIPE_SECRET_KEY/WEBHOOK_SECRET` | Ausentes o vacíos | No enviar ni recibir pagos/webhooks, ni siquiera test |
| `RESEND_API_KEY`, `GOOGLE_CLIENT_ID/SECRET` | Ausentes o vacíos | Barriers de email y OAuth; cero llamadas |
| `TURNSTILE_SECRET_KEY/SITE_KEY` | Ausentes salvo diseño revisado de test; no copiar claves productivas | Sin validación de producción |
| `ENABLE_ADVISORY_STATUS_EMAILS`, `ENABLE_ADVISORY_UPLOADS`, `PROCESSING_ERROR_EMAILS_ENABLED` | `false` | No correo, uploads o notificaciones reales |
| `ADMIN_EMAILS`, `FISCAL_ADVISOR_EMAILS`, notificaciones/contacto | Sólo direcciones ficticias `.invalid`, o vacío si el código lo permite | No direcciones personales/reales |
| Workers, jobs programados, callbacks/webhooks | No crear ni conectar en primera fase | Inventario sin tareas automáticas |

**Referencia DB:** usar el servicio propio y una referencia estilo `${{s01-lab-postgres.DATABASE_URL}}` **solo como forma ilustrativa**; la sintaxis exacta debe confirmarse en la UI de Railway antes de aplicar, porque el nombre identificador del servicio puede variar. `postgresql://` vs `postgresql+psycopg2://` se normaliza por `app.py` cuando corresponde, pero `S01-LAB-LOCK` habrá de validar el destino sin aceptar parámetros `?host` u otras redirecciones. No generar ni copiar contraseñas desde ChatGPT.

## 5. Procedimiento en fases, cada una con permiso independiente

### Gate A — Aprobar presupuesto y alta del laboratorio (PENDIENTE)
- Revisar nombre, workspace, límites de uso, aislamiento e implicaciones de coste.
- Autorizar **explícitamente** nuevo proyecto, PostgreSQL 18 y volumen, sin copiar ningún dato ni habilitar el web.
- Verificar nuevos IDs, privada `RAILWAY_PRIVATE_DOMAIN`, ausencia de TCP proxy público, referencia `DATABASE_URL`, volumen e identidad del cluster; **NO lanzar la aplicación todavía**.
- Inventario SQL de BD propia nueva, inicialmente sin tablas. STOP si aparecen datos, referencias a servicios del proyecto original o variables heredadas.

### Gate B — Integrar y aprobar código de laboratorio (PENDIENTE)
- Crear rama desde cabeza aprobada de PR #61, sin fusionar en `main`.
- Implementar `S01-LAB-LOCK` con IDs del laboratorio **fijados**, controles de base y fase preflight cerrada. No desactivar STG-LOCK existente, seguridad cookies o PREFREEZE de pagos.
- Probar en CI PostgreSQL 18/Flask/Chromium usando únicamente entorno falso y fixtures `.invalid`, fallos de identidad, enlaces cruzados DB, credenciales presentes, errores de host/Origin, callback financiero, correo y datos no sintéticos. Pruebas de regresión completa y SHA exacto. Inspección independiente previa a cualquier despliegue.
- Desactivar y confirmar **Auto Deploy** para el web del laboratorio; `Wait for CI` no implica autorización manual y no impide publicación si la CI pasa.

### Gate C — Inicializar base privada (PENDIENTE; requiere autorización de operación DDL)
- Hacer inventario `current_database()`, `server_version_num`, tablas y recursos *solo del lab*; registrar que no hay tablas/filas previas. Preparar backup/snapshot que pueda restaurarse y procedimiento de interrupción.
- En contexto administrativo aislado y con comprobación programática del proyecto/env/host/DB exactos, ejecutar **una sola vez, explícitamente** `python bootstrap_db.py` desde SHA aprobado contra **PostgreSQL nuevo**. No ejecutarlo en `Procfile` ni desde web ni en staging existente. Si el esquema está parcial o no está vacío: STOP, nunca `stamp` de rescate.
- El bootstrap nuevo crea tablas ORM y luego aplica migraciones semilla. **Se espera que la migración histórica cree el recurso educativo `experimento-bitcoin`**. Por tanto, un recurso semilla tras bootstrap NO demuestra mezcla de datos. Comparar slug/metadata de la semilla únicamente en DB lab.
- Exigir Alembic exacto `z9a0b1c2d3e4`, columnas S01, índices y CHECKs, tablas de pagos nuevas vacías y cero usuarios/solicitudes/pagos. Contrastar contra baseline. No introducir una fila con un token real.
- Si se desea ensayo `v5w6x7y8z9a0` → `z9a0b1c2d3e4`, preparar **OTRA base descartable** con esquema legacy y solo seis expedientes **inventados**; ejecutar únicamente migraciones aprobadas y verificar preservación. La CI ya probó la cadena; no tocar DB staging/producción.

### Gate D — Desplegar y ejecutar S01 en el laboratorio (PENDIENTE)
- Autorización separada del despliegue web SHA exacto tras Gate C. Pin de commit, repositorio y raíz. `Procfile`: gate de esquema de **solo lectura** antes de Gunicorn, healthcheck `/healthz`. Asegurar salud bajo Host de healthcheck Railway.
- Preflight deny-by-default para todo excepto comprobaciones revisadas. Confirmar `GET /healthz=200` y `POST /healthz=503` o rechazo equivalente; otros Host/Origin no aceptados. Cero llamadas externas. En caso de fallo de identidad o revisión DB, la web no llega a estado sano.
- Abrir temporalmente solo tráfico y operaciones imprescindibles del test sintético tras verificar que no hay datos ajenos. Ejecutar smoke con fixtures: login local de roles ficticios, navegación responsive, FIFO con CSV ficticios, administración de S01 y rechazo **503** de pagos/Stripe/PayPal, webhooks y envío de emails. Conectar el ejecutor únicamente por red del lab; **no exponer la web al público** salvo nuevo diseño de autenticación y autorización.
- Observar 4xx/5xx y separar **503 financieros esperados** de 5xx involuntarios; verificar que no se crean pagos, capturas, Stripe intents, notificaciones ni emails reales. Comprobar que el recurso semilla permanece único.

### Gate E — Ensayo de fallo/recuperación y cierre (PENDIENTE)
- Capturar estado del lab y lanzar fallos solo **simulados o sobre BD nueva/sintética**: revisión Alembic incorrecta, CHECK ausente en DB descartable, web que no arranca. El gate ha de fallar **sin DDL implícito**. Ningún rollback a `main` viejo que reabra PayPal.
- Preparar, publicar y probar un **artefacto de contingencia independiente compatible con `z9a0b1c2d3e4`**, con finanzas bloqueadas. Demostrar capacidad de recuperación de tráfico y datos sin ejecutar `alembic downgrade` ni restaurar copias que pierdan registros nuevos.
- Verificar métricas, inventario final y ausencia de recursos/costes olvidados. Decidir retención/eliminación del lab por aprobación expresa; **no borrar automáticamente** hasta guardar evidencias pertinentes.

## 6. Matriz de aceptación / motivos de parada

| Comprobación | Resultado necesario | Si falla |
|---|---|---|
| Proyecto/PG/volumen nuevo | IDs, redes, DB y referencias distintos de production/staging | No desplegar ni ejecutar SQL de escritura |
| `FLASK_ENV` y guard lab | Modo seguro con IDs compilados, sin banderas de bypass | Fallar arranque; revisión de código |
| Claves externas | Vacías o ausentes; barreras de no-I/O | No habilitar rutas, no continuar |
| Bootstrap explícito | BD lab inicialmente vacía; head `z9a0b1c2d3e4` | STOP; no stamp/downgrade |
| Seed recurso | `experimento-bitcoin` único en lab | Investigar, no corregir silenciosamente |
| Integridad financiera | 0 importes pagados y 0 eventos/órdenes/capturas de proveedor, excepto fixtures etiquetadas en BD temporal descartable | Parar test y preservar evidencias |
| Firewall web | Host/Origin/HTTP apropiados, S01 pagos 503, ninguna salida externa | Mantener acceso bloqueado |
| E2E | Fixtures ficticias; roles/CSRF/FIFO/gestión PASS | No GO producción |
| Fallo/recuperación | Imagen compatible nueva y recuperación comprobada sin abrir PayPal | NO-GO producción |
| Costes y teardown | Propietario conoce gasto y autoriza mantener/retirar | Detener recursos nuevos |

## 7. Decisión solicitada más adelante, NO ahora

**Siguiente posible autorización específica (una vez revisado este diseño):**
> Autorizar exclusivamente **crear un proyecto Railway nuevo** `fiscal-cripto-s01-lab` y un PostgreSQL 18 vacío con volumen privado propio, sujeto a límites de coste aprobados, sin clonar proyectos, DB, variables, secretos ni usuarios, sin conectar ni desplegar el servicio web, sin abrir dominios públicos, sin migraciones ni DDL. Tras creación, informar solo los IDs técnicos y la salud de recursos, sin revelar credenciales. Autorizar por separado cada fase B–E.

**Por ahora:** proyecto nuevo **NO creado**, web **NO desplegada**, BD **NO migrada**. PR #61 y `main` no alterados. Este documento no es una autorización para proceder con el presupuesto o la infraestructura.

## 8. Referencias operativas verificadas

- Railway [Controlling GitHub Autodeploys](https://docs.railway.com/deployments/github-autodeploys): Disable impide deploy automático; Wait for CI solo retrasa mientras se ejecutan workflows y puede desplegar en cuanto estén verdes.
- Código auditado en PR #61: `security_config.py`, `staging_isolation.py`, `bootstrap_db.py`, `startup_schema_gate.py`, `Procfile`, `qa_stg_b01_app_isolation.py`.
- Informe de staging anterior: `docs/audit/S01_STAGING_READONLY_PREFLIGHT_INTEGRATION_GATE_2026-10-13.md`; G04-R01/R02 en PR #59/#60.
