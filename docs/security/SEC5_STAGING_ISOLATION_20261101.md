# SEC5-PRIV — staging isolation gate (2026-11-01)

**Authorized:** changes strictly to Railway staging, never production.
The gate is an explicitly configured `preDeployCommand`, not a change to `app.py` or `Procfile`.
Its presence on a GitHub branch does nothing without deliberate staging configuration.

## Guard
- Project `e04f04a8-3aae-4aed-9073-638601f8ca30`, environment `staging` (`b2937140-78f7-4347-a9bc-c96333e03b9b`), service `fiscal-cripto-staging` (`3eecda71-9f53-4b33-a308-887d835b7fce`).
- Database host **exactly** `postgres-zzky.railway.internal`, corresponding to the staging PostgreSQL service's private network endpoint, **not** production `postgres.railway.internal`.
- Provider credentials for Stripe, Resend, Google, PayPal, Turnstile, and fiscal advisory recipients must be empty; error emails explicitly disabled.
- Requires explicit `SEC5_STAGING_ISOLATION=READONLY`.
- Verifies the live Flask connection through `db.engine` within `SET TRANSACTION READ ONLY`, PostgreSQL version 18 and transaction rollback. Output sanitized and NO-GO fail-closed.

A passing preflight is **not a substitute** for a separately validated staging limited-login connection. Staging's old deployment was pinned to an October commit; this branch is based on the PR #175 tested least-privilege prototype. Production remains on main.

**Scope of this code:** zero SQL DDL, zero role changes, zero external API calls, zero changes to the app runtime configuration. The separate staged Railway changes (provider vars blank, source SHA pinned, preDeploy command) must be reviewed as one patch before accepting a staging deployment. If the database DSN does not match the expected host, the deployment must fail closed.

**Follow-up:** after successful, evidence-backed staging isolation, provision a separate staging SQL LOGIN using approved isolated administrative access; validate permission denials and application flows before changing Flask's staging DSN. No change to production or PR merge under this task.

## Actualización operativa: aislamiento PASS, arranque NO-GO (TABLES)

El primer despliegue de staging `2fa108b6-2707-4eac-a931-e40943669ed2` ejecutó la comprobación `SEC5 STAGING ISOLATION: PASS (PostgreSQL18, read-only, staging-only hostname, providers disabled, superuser=on)`. Acto seguido, el arranque Flask falló de forma controlada con `S01 G04 STARTUP: NO-GO (TABLES; details protected)`. **No se ha creado ningún rol, ejecutado DDL ni migración**. La conexión de staging aún es superusuario y el despliegue anterior permanece registrado como SUCCESS.

Para investigar la ausencia de tablas sin tocar datos, `sec5_staging_schema_inventory.py` exige exactamente la misma puerta de aislamiento y consulta exclusivamente `information_schema`/catálogo y `alembic_version` dentro de `SET TRANSACTION READ ONLY`, siempre con `rollback`. Solo imprime nombres de tablas ORM que faltan, número de tablas y revisión Alembic. **No ejecutar `bootstrap_db.py` o `db.create_all` sin decidir una estrategia de datos staging tras examinar este inventario.**

## Estrategia reversible: nueva base dentro del servicio staging existente

El inventario real por pre-deploy read-only (01/11/2026) confirma `17` tablas ORM requeridas, `15` tablas existentes en `public`, ausencia de las tres tablas `s01_stripe_*` y revisión Alembic `v5w6x7y8z9a0` frente a `z9a0b1c2d3e4`. **No se migra ni altera la base antigua.**

El comando explícito `python sec5_staging_provision.py` solo admite el proyecto, entorno, servicio y DB hostname concretos de staging; exige `SEC5_STAGING_PROVISION=EXPLICIT_ONCE` y `SEC5_STAGING_PROVISION_PASSWORD` de alta entropía. A partir del acceso administrador **de staging** crea una nueva base `sec5_priv_stage_20261101`, un LOGIN `sec5_runtime_stage` sin atributos privilegiados, ejecuta `bootstrap_db.py` exclusivamente contra esa base vacía, concede los permisos de las 17 tablas y prueba con el login nuevo la puerta de arranque. No muestra ni almacena credenciales en GitHub. Rechaza colisiones con bases/roles existentes y no modifica el DB antiguo. En error limpia únicamente objetos creados en esa ejecución.

**Límites:** el procedimiento modifica el catálogo PostgreSQL solo en staging; ejecutar exclusivamente como predeploy temporal y retirarlo antes de cambiar `DATABASE_URL` al usuario limitado. En el paso final, borrar/neutralizar las variables temporales de provisión; el app no debe conservar credenciales admin. Restauración posible cambiando el `DATABASE_URL` del servicio web staging a la referencia de Railway para `Postgres-zZky.DATABASE_URL`, sin alterar el DB existente. Registrar en logs `SEC5 STAGING ROLE: PASS` antes de permitir el cambio de credencial runtime. GitHub CI no reemplaza esta evidencia.
