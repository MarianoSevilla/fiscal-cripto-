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
