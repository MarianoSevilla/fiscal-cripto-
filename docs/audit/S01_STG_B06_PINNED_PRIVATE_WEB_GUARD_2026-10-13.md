# STG-B06 — Identidad real del laboratorio y acceso privado · 13/10/2026

**Alcance aprobado: SOLO CÓDIGO EN GITHUB + CI. ESTADO: NO-GO RAILWAY / DDL / DESPLIEGUE.**

## 1. Identidades verificadas por lectura en Railway

- Proyecto **privado** `fiscal-cripto-s01-lab` — `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`.
- Entorno `lab` — `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- Web vacío `s01-lab-web` — **`212f4f52-b349-4387-a046-9f6b08237d2e`**; sin imagen/repositorio/configuración de variables, sin dominio público ni proxy TCP, **0 deployments**.
- DB privada `Postgres` — `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, `privateNetworkEndpoint=postgres` (esperado DNS `postgres.railway.internal`). Volumen propio `c35d178f-7473-4d0b-adb9-1faae815b7af`.
- Última comprobación SQL realizada **por el propietario**: base `railway`, PostgreSQL `180006` (18.6), `public` tiene **0 tablas**; esta fase NO realiza ninguna consulta nueva ni DDL. Revalidar antes de modificarla.

## 2. Decisión de seguridad para origen interno

La documentación de Railway establece que el host privado de un servicio llamado `s01-lab-web` es `s01-lab-web.railway.internal`, accesible solo desde el mismo proyecto/entorno con `http://…:PORT` sobre WireGuard cifrado. No se requiere dominio público. Esta es una **convención documentada**; el valor efectivo de `RAILWAY_PRIVATE_DOMAIN` del nuevo servicio vacío solo podrá confirmarse en un arranque autorizado posterior.

**Origen privado fijado en código para futuro preflight:** `http://s01-lab-web.railway.internal:8080` (HTTP, no HTTPS, al ser red privada WireGuard). **8080 es un puerto de diseño elegido para el laboratorio**, NO un valor que ya se haya configurado en Railway. Debe quedar explícitamente configurado y verificado como `PORT=8080` antes de cualquier despliegue web.

Implicaciones: ninguna URL de laboratorio se puede abrir desde el navegador personal ni desde Internet; un futuro ejecutor de pruebas necesitará estar en la misma red privada del laboratorio. Cookies Secure siguen habilitadas por `FLASK_ENV=staging`; en esta fase preflight no hay login, sesiones ni rutas de negocio accesibles.

No se ha creado dominio público, proxy TCP ni ejecutor de tests. Un ambiente o test con un host público, variable `RAILWAY_PUBLIC_DOMAIN` o `RAILWAY_STATIC_URL` configurada debe abortar. La comprobación en código de esas variables no sustituye la verificación operativa de dominios/proxies con Railway.

## 3. Contrato de variables del futuro servicio web: NO CONFIGURAR TODAVÍA

| Variable | Valor requerido o comportamiento |
|---|---|
| `RAILWAY_PROJECT_ID` | Identidad real inyectada automáticamente: `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e` |
| `RAILWAY_ENVIRONMENT_ID` | Autogenerada: `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8` |
| `RAILWAY_SERVICE_ID` | Autogenerada: `212f4f52-b349-4387-a046-9f6b08237d2e` |
| `RAILWAY_ENVIRONMENT_NAME` | `lab` |
| `RAILWAY_PRIVATE_DOMAIN` | `s01-lab-web.railway.internal`, comprobar valor real |
| `PORT` | **`8080`**, deberá configurarse explícitamente; el Procfile escucha `0.0.0.0:$PORT` |
| `FLASK_ENV` | `staging`; nunca `testing` en Railway |
| `APP_BASE_URL` | `http://s01-lab-web.railway.internal:8080` |
| `DATABASE_URL` | **Únicamente referencia Railway al servicio `Postgres` de ESTE lab**, forma de configuración `${{Postgres.DATABASE_URL}}` (la URI efectiva contiene secreto: NO imprimir). La plantilla declara `postgresql://…@postgres.railway.internal:5432/railway` y `app.py` normaliza el driver a `psycopg2`; guard acepta esquema `postgresql://` o `postgresql+psycopg2://`, con host, puerto, BD y sintaxis estrictos. |
| `SECRET_KEY` | Secreto nuevo exclusivo del lab, no reutilizar claves de producción o staging, nunca mostrar |
| `PAYPAL_ENVIRONMENT` | `sandbox` como identidad requerida, **sin credenciales** |
| PayPal, Stripe, Google OAuth, Resend, Turnstile | Todas las claves ausentes/vacías, incluso `test` |
| `ENABLE_ADVISORY_STATUS_EMAILS`, `ENABLE_ADVISORY_UPLOADS`, `PROCESSING_ERROR_EMAILS_ENABLED` | `false` o ausentes |
| `RAILWAY_PUBLIC_DOMAIN`, `RAILWAY_STATIC_URL` | Sin valor; prohibido añadir dominios públicos o proxies |
| `S01_LAB_MODE`, `S01_SYNTHETIC_LAB_MODE` | No se utilizan para desbloquear, se ignoran |

**Importante:** la conexión privada `postgres.railway.internal` es una cadena DNS que puede existir también en otros entornos Railway. El aislamiento real depende de (i) las identidades exactas del proyecto/entorno/servicio, (ii) la referencia propia `${{Postgres.DATABASE_URL}}`, (iii) la red privada de Railway. Comparar solo el nombre DNS NO demostraría separación.

## 4. Código y pruebas

- La PR B06 se basa exclusivamente en PR **#62** `security/s01-stg-b04-railway-lab-lock` (head `66084c224880e369d6b9432da371c7e9f620ae19`), creando una PR **en borrador**.
- `lab_isolation.py`: fija IDs, origen interno HTTP + puerto 8080, `RAILWAY_PRIVATE_DOMAIN` y restricciones de datos/credenciales. Cualquier discrepancia cancela import de Flask antes de `db.init_app`.
- `app.py`: conserva política de staging y el orden de barreras; comentario actualizado, sin rutas abiertas.
- Tests unitarios de configuración/Host/Origin y proceso Flask real con **variables ficticias**, sockets/DB/proveedores deshabilitados. En preflight solo `GET/HEAD /healthz` con Host exacto y healthcheck ferroviario sin Origin son accesibles. Toda otra ruta/método denegado.
- `staging_isolation.py` original **no se altera**; debe comprobarse su blob contra PR #61. `startup_schema_gate.py` sigue exigiendo Alembic exacto `z9a0b1c2d3e4`. La BD real del lab (0 tablas) no supera ese gate: un despliegue inmediato **fallaría**. `bootstrap_db.py` no se llama desde el Procfile.
- La nueva configuración en código no se ha probado en la red real, solo en CI sin conectividad. Los tests originales de PostgreSQL18, Chromium y regresión Python deben continuar aprobados.

## 5. Límites y pasos posteriores (sin autorización actual)

1. Revisar el resultado exacto de CI y el inventario de cambios; mantener PR DRAFT apilada y `main` inalterada.
2. Por autorización posterior, verificar referencia efectiva `Postgres.DATABASE_URL`, dominio interno real, `PORT`, variables ausentes y Auto Deploy **desactivado** antes de enlazar un repositorio.
3. **Separadamente**, autorizar la inicialización administrativa de PostgreSQL en LAB, después de inventario renovado, garantía de ninguna conexión a producción/staging y plan de recuperación; `alembic_version` esperada `z9a0b1c2d3e4`.
4. Solo tras lo anterior y nueva autorización, considerar conectar GitHub y desplegar el web en un SHA fijado, manteniendo sin dominio público ni otros accesos al margen de healthcheck.

**STOP/NO-GO:** no conectar rama a Railway, no modificar variables, dominios, servicio ni DB, no correr Alembic o SQL escritura, no fusionar ninguna PR, no generar pagos ni emails.

### Documentación Railway

- [Private Networking](https://docs.railway.com/networking/private-networking)
- [How Private Networking Works](https://docs.railway.com/networking/private-networking/how-it-works)
- [Working With Domains — Private Networking](https://docs.railway.com/networking/domains/working-with-domains)
- [Railway reference variables](https://docs.railway.com/guides/managing-secrets-on-railway#reference-variables)
