# STG-LOCK-001 — Preflight estricto de Railway staging

Estado: **PR en borrador, corrección del healthcheck code-only, sin autorización de nuevo despliegue**. Base: `main` `56882073295faae3bd1bc3632288a970acb330da` (12/10/2026). **NO autoriza merge, despliegue, variables, credenciales, webhooks ni pagos.** PR #29 U04 y #30 PREFREEZE intactas.

## Por qué se necesita

La auditoría de 12/10/2026 encontró que staging ejecuta `cc1da441f1f07c640a88d3bcd1eb7fef4258daaf`, siete commits detrás de `main`, aunque dispone de un PostgreSQL propio (`Postgres-zZky`). PayPal está en `sandbox`, sin Client ID/Secret. Falta `APP_BASE_URL` y su fallback apunta a producción. Existen variables para Resend, Google OAuth y Stripe cuyos **valores no se conocen**. El webhook Stripe test activo apunta a producción. No se ha acreditado que el dataset staging sea exclusivamente sintético.

Esta PR añade un **lockdown de preflight**, **no** un motor PayPal Sandbox ni una implementación Stripe. El objetivo es evitar accesos transaccionales, contactos con proveedores y exposición de APIs mientras se certifica el entorno.

## Incidencia detectada en el primer despliegue de staging (12/10/2026)

El despliegue Railway `1d9e66db-1a92-4095-91ef-57056965759d` del commit `b5eab9801d99305351642a4721f4c4c4d6b6e2fb` terminó en **FAILED**. El proceso arrancó, `bootstrap_db.py` comunicó `DB bootstrap: existing Alembic history upgraded` y Gunicorn escuchó en el puerto `8080`; la versión anterior permaneció activa. La documentación oficial de Railway indica que sus comprobaciones HTTP usan `Host: healthcheck.railway.app`. El bloqueo previo rechazaba cualquier Host distinto del dominio público de staging con HTTP `421`, por lo que el healthcheck no podía alcanzar un `2xx`. Esta es una causa compatible con la evidencia, no una lectura directa del código HTTP interno de Railway.

La corrección permite exclusivamente `GET/HEAD /healthz` cuando el Host sea exactamente `healthcheck.railway.app` y **no exista Origin**. Cualquier otro acceso desde ese Host devuelve `421`; la política de rutas del dominio público no se modifica. Se añaden pruebas de regresión y se requiere aprobación separada para cambiar el SHA fijado y volver a desplegar. No se desactiva el healthcheck.

## Archivos y comportamiento

- `fiscal_app_export/staging_isolation.py`: validación sin DB/red de identidad Railway, URL canónica y DSN, cierre de credenciales externas, política HTTP y barrera del SDK Resend.
- `fiscal_app_export/app.py`: invoca la validación tras `build_security_config`, **antes de `db.init_app` / `db.create_all` y de la migración que ejecuta `bootstrap_db.py`**. Solo en staging instala un `before_request` con denegación por defecto de rutas no revisadas y deshabilita `resend.Emails.send` de todo el proceso; su CORS permite exclusivamente el origen staging.
- `fiscal_app_export/tests/test_staging_isolation.py`: pruebas unitarias offline de identidad, errores, DSN, rutas, URLs, correos y credenciales.
- Este documento. **No se tocan** esquemas, migraciones, `bootstrap_db.py`, `Procfile`, dependencias, proveedores, ni PR #29/#30.

## Contrato de staging preflight

1. Se activa si el modo Flask, el nombre de entorno Railway, el ID de entorno o el ID de servicio señala staging. Si uno contradice los demás, **el arranque falla cerrado**, sin conexión a BD, y sin mostrar secretos.
2. Requiere `FLASK_ENV=staging`, IDs Railway actuales de proyecto/entorno/servicio, `RAILWAY_ENVIRONMENT_NAME=staging`, `APP_BASE_URL=https://fiscal-cripto-staging-staging.up.railway.app` exacta, sin barra final, y `PAYPAL_ENVIRONMENT=sandbox`.
3. Exige `DATABASE_URL` con driver `postgresql+psycopg2`, hostname privado `postgres-zzky.railway.internal`, puerto `5432`, base `railway`, usuario y contraseña presentes, sin query/options ni fragmento que pudiera redirigir la conexión. **Esto no certifica los datos ni la conexión en vivo.**
4. Durante este preflight las siguientes variables deben estar ausentes o **vacías**: `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `RESEND_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`. Si alguna contiene valor, **no arranca**. No introducir credenciales Sandbox con este código: exige otro diseño/PR.
5. La `SECRET_KEY` y cookies seguras se validan con `security_config.py` de `main`. Para staging, HTTP rechaza cualquier Host distinto (`421`) y un Origin distinto (`403`), con una **única excepción técnica**: `Host: healthcheck.railway.app`, exclusivamente `GET` o `HEAD` sobre la ruta exacta `/healthz`, y **sin cabecera `Origin`**. No se admite ese Host en otras rutas, métodos, puertos ni prefijos/sufijos de hostname. La excepción es necesaria porque Railway utiliza ese hostname para su healthcheck previo a activar un despliegue.
6. **Denegación HTTP por defecto**: todo método distinto de GET/HEAD/OPTIONS devuelve `503`. Incluso GET/HEAD/OPTIONS devuelve `503` salvo rutas públicas expresamente enumeradas en `_STAGING_PUBLIC_READ_PATHS` (Home, `/healthz`, páginas legales, informativas y SEO revisadas) o recursos bajo `/static/` con extensiones de imagen, estilo, script o fuente expresamente permitidas. HTML, PDF, CSV, JSON y XML quedan bloqueados como archivos estáticos directos. Se bloquean rutas dinámicas, autenticadas, APIs, administrador, OAuth y pagos, así como cualquier ruta futura no revisada. En particular, **`GET /verify-email` modifica la BD y debe devolver `503`**. Los rechazos incluyen `Cache-Control: no-store`; los 503 incluyen `Retry-After`. Esta suspensión de staging es intencionada y temporal.
7. Se impide `resend.Emails.send` incluso si una ruta auxiliar/campaña de fondo intentase enviarlo. La política de producción se mantiene igual cuando ninguna identidad indica staging.

## Lo que todavía no demuestra y acciones prohibidas

- No certifica contenido exclusivamente sintético en la BD, ausencia de credenciales de terceros fuera de las enumeradas, rutas externas incrustadas en HTML o identidad de todos los procesos. Se necesita evidencia operativa adicional antes de ensayos.
- No cambia el webhook Stripe test actualmente dirigido a producción; no se permite crear, activar, desactivar ni reenviar webhooks sin autorización individual.
- No resuelve la conciliación PayPal Live ni la retirada de U03; PREFREEZE de producción sigue siendo prioritario.
- No fusionar esta PR ni ejecutar un nuevo despliegue sin autorización específica. Tras el primer intento fallido, la configuración de origen del servicio staging quedó fijada al commit `b5eab9801d99305351642a4721f4c4c4d6b6e2fb` de la rama `security/staging-preflight-isolation-20261012`, pero Railway mantuvo **online el despliegue anterior** `cc1da441f1f07c640a88d3bcd1eb7fef4258daaf`. Los commits nuevos de esta PR no se aplican automáticamente mientras el servicio permanezca fijado al SHA antiguo.
- No se permite habilitar PayPal Sandbox, Stripe Test, Resend, OAuth ni UI financiera con esta versión de preflight; requerirán integración de S00/S01 y pruebas aprobadas.
- El repositorio contiene enlaces públicos hardcodeados a `marianosevilla.com`; la PR bloquea emails y APIs, pero no pretende reescribir todos los enlaces editoriales. Revisar antes de abrir flujos transaccionales.

## Condiciones para una autorización posterior de despliegue

1. Inspeccionar en solo lectura `current_database()`, identidad PostgreSQL, revisión Alembic, conteos agregados, existencia de datos reales y esquema, sin volcar PII.
2. Verificar `FLASK_ENV`, `APP_BASE_URL`, `SECRET_KEY` y que todas las variables prohibidas estén vacías. Proteger las credenciales fuera del chat.
3. Hacer backup restaurable de staging y estudiar migraciones pendientes porque el `Procfile` ejecuta `bootstrap_db.py` antes de arrancar Gunicorn. Preparar ventana y reversión no destructiva.
4. Exigir CI completa y pruebas Flask/PostgreSQL/HTTP, incluyendo 503 en webhooks, `GET /verify-email`, rutas dinámicas y futuras rutas no enumeradas, además de ausencia de red/correos; comprobar que no se cambia producción. Revisar por qué cualquier job falla antes de corregir.
5. Solicitar autorización separada para variables, selección del SHA y despliegue staging; inspeccionar la identidad real de la instancia y los 503, no únicamente `/healthz`.
6. Una implementación financiera posterior necesitará controles probados de autenticidad, idempotencia, conciliación y reserva económica S00, más aislamiento del webhook Stripe test de producción.

**Veredicto:** esta PR es solo un paso previo de seguridad. No autoriza ensayos end-to-end y puede dejar staging en modo mantenimiento hasta que otro cambio explícitamente revisado habilite el laboratorio sintético.
