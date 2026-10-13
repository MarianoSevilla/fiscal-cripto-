# S01 STG-B10B — Identidad del servicio administrativo privado · 14/10/2026

**Autorización:** "procede" tras cierre de B10A: crear y preparar identidad de ejecutor privado vacío, configurar salvaguardas no ejecutables y redactar PR DRAFT. **NO autorización para despliegue, conexión de código, ejecución de preflight vivo ni migraciones DDL**.

## Lectura y acción en Railway (proyecto S01 separado)

- Proyecto: `fiscal-cripto-s01-lab`, ID `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`.
- Entorno: `lab`, ID `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- PostgreSQL exclusivo de lab: servicio `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, despliegue existente sin modificar. Volumen separado en Postgres.
- Web lab: `s01-lab-web`, servicio `212f4f52-b349-4387-a046-9f6b08237d2e`, sigue **sin source y sin deployments**.
- **Servicio administrativo creado SOLO en entorno lab:** `s01-lab-maintenance`, ID efectivo **`9728d19b-7d17-4acb-8be1-c4b0847179df`**. Source: null, latestDeployment: null, sin Docker image, sin repositorio, sin volumen, sin dominio público y sin TCP proxy.
- Configuración explícita: política de reinicio `NEVER`; cron ausente; una única réplica configurada (inactiva porque no hay deployment); tracing/autoinstrumentation inactivos, outbound IPv6 deshabilitado.
- Variables propias configuradas usando `skipDeploys=true`: `FLASK_ENV=staging`, `PAYPAL_ENVIRONMENT=sandbox`, `DATABASE_URL` como **referencia literal** `${{Postgres.DATABASE_URL}}` al servicio `Postgres` del mismo proyecto. No se han configurado SECRET_KEY ni credenciales de PayPal, Stripe, Resend u otros proveedores.
- Inventario posterior: Railway confirma nombres de esas 3 variables y los nombres `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_ID`, `RAILWAY_SERVICE_ID`, `RAILWAY_PRIVATE_DOMAIN`. La conexión OAuth **oculta los valores**, de modo que **NO consta verificación del valor resuelto** de `DATABASE_URL` ni del DNS privado efectivo; son gates operativos futuros.
- Nombre DNS esperado por convención: `s01-lab-maintenance.railway.internal`. Que el nombre coincida **no constituye prueba de resolución DNS efectiva** sin un despliegue autorizado. No se ha configurado puerto HTTP; este no es un servidor web ni requiere dominio público.
- B09 validó manualmente `public` con cero tablas, vistas, secuencias e índices. No se ha repetido SQL ni cambiado PostgreSQL en B10B.

## Código GitHub y CI

- Base PR **#64** `security/s01-stg-b10a-private-maintenance-preflight`, SHA `cbfdcb57a36e90256a72fe9cb15234d76dcd7518`; #64 DRAFT con CI sintética 19/19 PASS.
- Nueva rama apilada: `security/s01-stg-b10b-pin-maintenance-service`. Cambios limitados al pin real `MaintenanceIdentity.service_id`, comentarios, pruebas offline y workflow CI propio de B10B.
- Las pruebas solo simulan el entorno usando diccionarios y conexiones falsas; no hacen peticiones a Railway, ni a PostgreSQL, ni usan credenciales reales. Mantener la PR en borrador sin merge.
- **Límite de aislamiento:** el pin de servicio por sí solo no prueba cuál es la instancia de Postgres resuelta. Antes de una futura ejecución deberá comprobarse por separado identidad/procedencia de la referencia y los valores efectivos sin exponer credenciales.
- El `app.py` del laboratorio permanece bloqueado al **ID de servicio web**. No se ha diseñado aún una ruta administrativa para importar `bootstrap_db.py` sin transgredir este bloqueo; requiere una B10C con revisión de seguridad independiente.

## No autorizados

NO `create-deployment`, `connect-service-source`, `accept-deploy`, `redeploy`, `bootstrap_db.py`, `alembic upgrade`, SQL de escritura, cambios en `main`, fusión de PR, aplicaciones/servicios de staging o producción ni acceso HTTP público.

**Resultado esperado B10B:** identidad administrativa real fijada, servicio vacío e inactivo, CI sintética verde, PR DRAFT; **NO-GO para ejecución en Railway o inicialización DB**.
