# S01 · STG-B07 — Variables y red privada preparadas, SIN APLICAR

**13/10/2026 · RESULTADO: PREPARADO (STAGED); NO-GO PARA DESPLIEGUE, BASE DE DATOS O ACTIVACIÓN.**

## Autorización estricta y medidas adoptadas

Tras completar STG-B06, el propietario indicó «procede» para **STG-B07: preparar la configuración real de variables y el acceso privado del servicio web**. No autorizó la inicialización de PostgreSQL, la conexión de GitHub, despliegues, apertura de dominio público, facturación ni operaciones financieras. Por ello se utilizó **Railway staged changes**: la configuración quedó en revisión, no aplicada.

**No se ha llamado a `accept-deploy` ni se ha alterado ningún otro proyecto/entorno.**

### Alcance e identidad

| Objeto | ID / verificación |
|---|---|
| Proyecto nuevo independiente | `fiscal-cripto-s01-lab` — `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e` |
| Entorno aislado | `lab` — `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8` |
| **ÚNICO servicio con cambios staged** | `s01-lab-web` — `212f4f52-b349-4387-a046-9f6b08237d2e` |
| PostgreSQL 18 + volumen | `Postgres` — `f680f3fc-4581-44ff-8bc1-d034840f2c7e`; online, deploy SUCCESS; **sin cambios staged** |
| Patch Railway | **`7e481ca6-0d26-40e1-83cc-76f08b963f03`** |
| Estado del patch | **STAGED**, 14 cambios, **no destructivo** |
| Despliegues web | **0**, fuente repositorio/imagen nula |
| Dominio público / TCP proxy | **0 / 0** |
| Variables aplicadas al web | Solo variables automáticas `RAILWAY_*`; ninguna variable propia aún está aplicada |
| Shared vars | Ninguna creada o modificada |
| Estado SQL conocido | Última lectura propietario: `railway` PG 18.6, `public` **0 tablas**. NO se ejecutó SQL nuevo en B07 |

### Once variables STAGED exclusivamente en `s01-lab-web`

| Nombre | Valor previsto / política |
|---|---|
| `FLASK_ENV` | `staging` (cookies Secure; prohibido `testing` en Railway) |
| `PORT` | `8080`, coincide con el puerto interno fijado por STG-B06 |
| `APP_BASE_URL` | `http://s01-lab-web.railway.internal:8080` (interno, sin TLS de aplicación; canal WireGuard privado Railway) |
| `DATABASE_URL` | **Reference** `${{Postgres.DATABASE_URL}}` del Postgres ubicado EN ESTE nuevo proyecto `lab`; no se proporcionó ni mostró DSN o contraseña |
| `PAYPAL_ENVIRONMENT` | `sandbox`; **NO** activa PayPal sin credenciales (la barrera S01 lo impide) |
| `ENABLE_ADVISORY_STATUS_EMAILS` | `false` |
| `ENABLE_ADVISORY_UPLOADS` | `false` |
| `PROCESSING_ERROR_EMAILS_ENABLED` | `false` |
| `ADMIN_EMAILS` | Cadena vacía: ninguna dirección real ni fallback de privilegios |
| `FISCAL_ADVISOR_EMAILS` | Cadena vacía: sin permisos asignados por email |
| `RESEND_FROM_EMAIL` | `no-reply@s01-lab.invalid` (ficticio, sin credenciales de correo) |

**Secreto pendiente:** `SECRET_KEY` deliberadamente **NO configurado ni staged**. Debe generarse como valor nuevo, robusto y exclusivo del lab (idealmente secreto sellado desde Railway) antes de aplicar e intentar iniciar Flask; **jamás copiar** `SECRET_KEY` de production/staging. Su ausencia hace fallar el arranque de seguridad por diseño. No existen credenciales de Stripe, PayPal, Resend, Google OAuth, Turnstile, etc., ni se ha activado envío real.

### Tres ajustes de servicio STAGED

- `networking.privateNetworkEndpoint = s01-lab-web`. Solo DNS privado, sin generar dominio público ni proxy.
- `deploy.healthcheckPath = /healthz`. La única ruta permitida en preflight STG-B06.
- `deploy.restartPolicyType = NEVER`. Evita reinicios automáticos ante errores durante el posterior arranque de validación (si se autorizase).

**IMPORTANTE:** el cambio en `privateNetworkEndpoint` puede provocar redeploy al **aplicarse** en Railway. No se ha aplicado; permanecerá en patch pendiente. El nombre privado efectivo y la referencia DB renderizada deberán confirmarse por comprobaciones de metadatos sin revelar secretos.

## Controles contra despliegue accidental o conexiones cruzadas

1. Precheck: proyecto/entorno/ID web exactos, un solo PostgreSQL, un solo volumen, web vacía, 0 dominios públicos, 0 deployments, sin cambios staged previos; PR #63 DRAFT/CI SUCCESS.
2. `set_variables`: **`staged:true`**, `skipDeploys:true`, `environmentId` y `serviceId` explícitos.
3. `update_service`: **`staged:true`** y mismos IDs exactos; **no se llamó a `accept-deploy`**.
4. Postcheck: patch **STAGED**, 14 entradas esperadas bajo **un solo servicio** `s01-lab-web`. Nada tocó `Postgres`, volúmenes, grupos de variables ni networking global; **0 deployments web** y **0 dominios públicos**.
5. Contrato de seguridad de la PR #63: `lab_isolation.py` exige proyecto/entorno/web ID, nombre `lab`, `FLASK_ENV=staging`, `RAILWAY_PRIVATE_DOMAIN`, `PORT=8080`, base URL privada, DB host `postgres.railway.internal:5432/railway`, credenciales de terceros ausentes y correo/cargas bloqueados.
6. **RIESGO RESIDUAL**: el host DB `postgres.railway.internal` es nombre reutilizable entre proyectos. Debe validarse que la variable reference `Postgres.DATABASE_URL` apunta al servicio **de este proyecto/entorno**, no bastando el host. La identidad Railway + aislamiento de su red privada refuerzan esa garantía.
7. Verificación original: GitHub `main` / Railway producción `56882073295faae3bd1bc3632288a970acb330da`; Railway staging `f421a9c21f99267eb0aedf05705c93b62fba3ba9` en SUCCESS, **0 cambios staged** en ambos. PR #61/#62/#63 siguen sin merge; PR #63 `9f8060ce2e096165b33dbae25276c91d52f4ed15` CI 3/3 SUCCESS (`1904 passed, 63 skipped`).

## Próxima decisión: NO aplicar todavía

**PENDIENTES antes de aplicar cualquier patch de lab, inicializar BD o conectar GitHub:**
- Preparar **nuevo `SECRET_KEY`** exclusivamente en el laboratorio mediante un procedimiento seguro; comprobar que no habrá copia, publicación ni retención en repositorio/documentos.
- Revisar que el patch continúa exactamente en `7e481ca6-0d26-40e1-83cc-76f08b963f03`, con 14 cambios únicamente del web, sin cambios al DB ni ningún recurso ajeno.
- Obtener **nueva autorización explícita** para `accept-deploy`. Aceptar cambios staged implica una operación de deployment por Railway; no debe ejecutarse por implicación.
- Repetir inventario **solo lectura** de la BD nueva (0 tablas a fecha de la comprobación previa), plan de recuperación y autorización **diferente** para `bootstrap_db.py` / migraciones; en lab no está instalado Alembic todavía.
- Autorizar **separadamente** conectar la fuente GitHub con SHA exacto y desplegar aplicación solo después de schema gate `z9a0b1c2d3e4` y guard activo. Permisos PayPal/Stripe/email/webhook jamás implícitos.
- Revisar gastos; PostgreSQL está ONLINE y mantiene consumo facturable. La fase B07 **no ha programado** ni ejecutado parada automática.

**NO-GO actual: sin `SECRET_KEY`, con DB sin tablas y web sin fuente, la aplicación no se puede iniciar; es el comportamiento seguro esperado.**

Documentos: [STG-B06](S01_STG_B06_PINNED_PRIVATE_WEB_GUARD_2026-10-13.md) en la rama #63; [STG-B05](S01_STG_B05_EMPTY_LAB_WEB_SERVICE_CREATED_2026-10-13.md) en esta rama de auditoría.
