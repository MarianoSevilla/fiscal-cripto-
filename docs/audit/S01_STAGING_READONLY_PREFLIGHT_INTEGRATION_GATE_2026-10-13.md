# S01 — Staging preflight read-only y gate de integración

**13 de octubre de 2026 · AUDITORÍA SIN CAMBIOS DE INFRAESTRUCTURA.** No autoriza Railway deploy, variables, recursos, base de datos, reconfiguración de GitHub ni merge. **NO-GO despliegue de PR #60 directamente sobre staging.**

## Fuentes y huellas verificadas

- Railway proyecto `e04f04a8-3aae-4aed-9073-638601f8ca30`, entornos `production` y `staging`; servicio web producción `fiscal-cripto-` y staging `fiscal-cripto-staging`.
- Producción web: rama `main`, SHA `56882073295faae3bd1bc3632288a970acb330da`, deployment SUCCESS; `source.checkSuites: true` (marca de chequeo CI en configuración). Rama `main` idéntica a GitHub, sin pendientes de configuración.
- Staging web: rama `security/staging-preflight-isolation-20261012`, con **commit fijado por `source.commitSha`** en `f421a9c21f99267eb0aedf05705c93b62fba3ba9`, despliegue SUCCESS. Coincide con SHA actual de su rama GitHub. No confundir cambiar rama con retirar fijación de commit, ni asumir autodeploy deshabilitado por el pin.
- PostgreSQL 18 producción: servicio `Postgres`, volumen `cf04823e-2108-4667-9432-4e680288b20a` en `/var/lib/postgresql/data`. Staging: servicio `Postgres-zZky`, volumen `11b1b798-6231-4ef1-906a-8faa76508276`, distinto. Ambos online.
- `DATABASE_URL` figura por nombre en las variables de cada web, pero el conector Railway OAuth **no devuelve valores**. Los dos recursos aislados **no demuestran** que la aplicación staging apunte efectivamente a `Postgres-zZky`. Validación de referencia de variable y destinatario, sin copiar contraseña, aún PENDIENTE.
- No hay parches pendientes de Railway en ninguno de los dos entornos. Producción PostgreSQL muestra **2 avisos no críticos aún sin clasificar**; staging web tuvo 1 FAILED en 24 h, con posterior SUCCESS (no se deben tratar sin lectura contextual como defectos del SHA actual).
- `main` no contiene los 10 commits propios adicionales de la rama staging; ésta está 10 ahead/0 behind de `main`, cambiando `app.py`, `staging_isolation.py`, su suite y `STAGING_LOCKDOWN_001.md`.

## Hallazgo P0 — La rama staging tiene una defensa que no está en la candidata

La rama staging `f421a9c2...` **sí** implementa `STG-LOCK-001`:
- Antes de importar/inicializar BD comprueba identidad exacta Railway, `APP_BASE_URL`, `FLASK_ENV=staging`, `PAYPAL_ENVIRONMENT=sandbox` y DSN PostgreSQL del host privado **`postgres-zzky.railway.internal:5432/railway`**. Si contradicen identidad o destino aborta.
- Requiere ocho claves externas **ausentes o vacías**, incluyendo PayPal, Stripe, Resend y Google OAuth. El conector muestra los nombres, nunca sus valores: no está acreditada hoy su ausencia o vaciado.
- Deniega por defecto API, autenticación, uploads, webhooks y todas las solicitudes mutantes, así como `GET /verify-email` porque modifica estado; permite sólo páginas públicas GET/HEAD/OPTIONS listadas. Niega Host/Origin ajenos; permite exclusivamente el healthcheck Railway `Host: healthcheck.railway.app`, `GET/HEAD /healthz` sin Origin. Intercepta envío Resend.
- La documentación de esa rama informa que **el webhook Stripe TEST seguía apuntando a producción** al 12/10/2026. **No verificado de nuevo aquí ni autorizado a cambiarlo**. Tratarlo como riesgo a resolver antes de ensayar eventos del proveedor.
- En consecuencia, **STG-LOCK-001 impide el E2E autenticado y los POST de gestión que S01 necesita probar**. Es seguro como preflight de lectura, NO como laboratorio funcional sin contrato nuevo.

El candidato S01 PR #60 `d4edd911a343fba15d92ef6c035bd118b6c24fe9` **no contiene** `fiscal_app_export/staging_isolation.py` ni los diez commits STG-LOCK. Cambiar el origen staging directamente a #60 puede **perder** esas defensas. Tampoco se debe fusionar ciegamente la rama staging entera en main: sus bloqueos permanentes de API afectarían pruebas S01 y podrían introducir comportamiento no deseado en producción.

**Dictamen:** **NO-GO para sustituir staging por la PR #60 sin integrar/verificar STG-LOCK y fijar modo de laboratorio sintético explícito.**

## Trigger deploy / Railway Wait for CI

Config web prod `source.checkSuites: true`; documentación oficial: [Controlling GitHub Autodeploys](https://docs.railway.com/deployments/github-autodeploys). La marca indica gate CI configurado, pero *Wait for CI* permite desplegar al terminar con SUCCESS; **NO impide despliegue después de fusionar**. Antes de merge S01 se necesita **Disable automatic deployments** comprobado en **Service Settings → Source/GitHub**, o un mecanismo equivalente verificable y autorizado. No asumir que `checkSuites` es autorización manual, ya que no lo es.

En staging también hay origen enlazado a GitHub y `source.commitSha` fijado; verificación/autorización requerida para cambiar ese pin y controlar trigger antes de nuevas ejecuciones. **No se ha modificado ninguna de estas propiedades**.

## Preparación de staging con dos fases independientes

### Gate STG-A: seguridad e identidad (solo lectura, ahora)

1. Congelar SHA y anotar despliegue web/DB staging. Confirmar por la UI de Railway **solo la expresión de referencia** de `DATABASE_URL` del servicio staging (no URL resuelta): debe apuntar exclusivamente al servicio `Postgres-zZky` del entorno staging. No copiar valores, credenciales, passwords, tokens ni cadenas DSN al chat.
2. Confirmar que `APP_BASE_URL` es la URL pública staging y que `FLASK_ENV=staging`; verificar que PAYPAL_CLIENT_ID/SECRET/WEBHOOK_ID, STRIPE_SECRET/WEBHOOK_SECRET, RESEND_API_KEY y GOOGLE_CLIENT_ID/SECRET están **deshabilitadas/vacías**, sin publicar valores. Si hay claves configuradas, detenerse, **no sobrescribirlas** sin autorización concreta. `SECRET_KEY` debe existir y ser no trivial, sin revelar valor.
3. En editor SQL del **Postgres-zZky de staging**, únicamente bajo confirmación de destino, obtener revisión Alembic y contadores anónimos para detectar datos no sintéticos. Nunca volcar nombres, emails, archivos, tokens, hashes o filas reales. No ejecutar migración ni `stamp`.
4. Revisar origen, automatismos y estados de avisos de PostgreSQL producción sin exponer logs privados. Confirmar token PayPal histórico G05 caducado; **no borrar ni revocar en BD**.
5. Revalidar `STG-LOCK-001` exacto `f421a9c2...` y HTTP salud + restricciones sin llamadas a proveedores. Sin autorización, no cambiar el pin.

### Gate STG-B: laboratorio S01 (requiere nueva autorización precisa)

**Diseño preferido:** preparar una rama de integración **partiendo de PR #60** que porte/adapte `STG-LOCK-001` de forma estrictamente condicionada por identidad staging y con dos modos revisados: (i) preflight deny-by-default sin autenticación/escrituras ni IO externo y (ii) laboratorio funcional controlado para *solo fixtures*, donde exista prueba robusta de BD nueva/aislada, host, credenciales externas ausentes, red externa de cobro/correo bloqueada, y permisos explícitos para login, recepción y gestión C1. Nada de esto debe degradar el comportamiento de producción ni habilitar S01 pagos.
- Alternativa con menor interferencia: servicio de laboratorio adicional con PostgreSQL de prueba **nuevo** y credenciales sintéticas, separados de staging ya existente. Crear infraestructura cuesta recursos y requiere permiso; no está ejecutado.
- **No usar** la BD staging actual para sembrar, `drop_all`, tests destructivos, migración o fixtures mientras se desconozcan sus contenidos. Un cambio de código sin despejar este gate también podría invocar el arranque viejo `bootstrap_db.py` que aplica migraciones de forma automática.
- Plan de ensayo autorizado: backup/restore de BD sintética, revisión `v5w6x7y8z9a0` si se prueba migración legacy, pasos Alembic `x7y8z9a0b1c2`→`y8z9a0b1c2d3`→`z9a0b1c2d3e4` antes de G04 startup read-only; smoke `/healthz`, autenticación, FIFO, E2E C1, respuestas 503 financieros, huella/contadores y recuperación de un artefacto de contingencia seguro compatible con `z9...`. No PayPal, Stripe, Resend, Google OAuth reales ni webhooks.

## Consulta SQL opcional de staging por el propietario (solo metadatos)

*Solo una vez confirmado en la UI que el editor es de Postgres-zZky y que su conexión no apunta a producción; ejecutar cada SELECT por separado sin punto y coma si el editor añade LIMIT.*

```sql
SELECT current_database() AS database_name,
       current_setting('server_version_num')::integer AS pg_version,
       (SELECT version_num FROM public.alembic_version) AS alembic_revision
```

```sql
SELECT COUNT(*) AS total_s01_requests,
       COUNT(*) FILTER (WHERE payment_link_token IS NOT NULL) AS tokens_persistidos,
       COUNT(*) FILTER (WHERE paypal_order_id IS NOT NULL OR paypal_capture_id IS NOT NULL) AS paypal_references,
       COUNT(*) FILTER (WHERE amount_paid IS NOT NULL OR paid_at IS NOT NULL) AS payment_indicators
FROM public.fiscal_advisory_requests
```

Estas consultas solo devuelven esquema/metadatos y conteos. Si alguna tabla no existe o hay más de una revisión Alembic, **STOP**, sin intentar reparaciones. No se ejecutaron desde ChatGPT.

## Estado al cerrar este preflight

- Infraestructura staging existente: **ONLINE, dos servicios con DB/volumen propio**, sin parches pendientes, SHA fijado f421.
- Candidato S01 PR #60: **CI SUCCESS** exacto SHA `d4edd911a343fba15d92ef6c035bd118b6c24fe9`, 1556 tests Python pass, 63 skip, PG18 G04-R02 success y 26 E2E browser pass; **no en staging ni producción**.
- **NO-GO staging funcional** hasta resolver identidad/variables sin secretos, adaptación STG-LOCK sin perder guardas, y autorizar código/infra por separado.
- **NO-GO producción** hasta ensayos completos, backup fresco, estrategia de corte con autodeploy bloqueado, recovery sin reactivar PayPal y autorización expresa.
