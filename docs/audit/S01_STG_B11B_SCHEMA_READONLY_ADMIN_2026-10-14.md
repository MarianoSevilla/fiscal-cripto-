# STG-B11B — Nuevo administrador S01 exclusivamente para preflight de esquema

**Fecha 14 de octubre de 2026.** Sin autorización DDL sobre Railway. Prohibido fusionar PRs o desplegar web.

## Precondiciones

STG-B11A PR #83 superó [CI #38612735850](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38612735850): 24/24 contratos y restauración de BD vacía entre dos PostgreSQL18 efímeros antes de la inicialización completa de modelos + Alembic al head `z9a0b1c2d3e4`, con doble bootstrap rechazado y origen sintético intacto.

Railway S01 proyecto `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, entorno lab `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`:
- PostgreSQL original NO TOCAR: servicio `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, clúster `7696213098351943739`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`.
- PostgreSQL recuperado elegido como futuro destino exclusivo: `Postgres-Im3h`, servicio `317b21e9-b259-4b15-902a-a7bec69b7407`, clúster `7696517018472497211`, volumen `16144c31-17d5-49e7-a725-967e883e03f9`. El restore REAL B10S finalizó PASS, resultado BD restaurada vacía.
- Servicio antiguo `s01-lab-maintenance` `9728d19b-7d17-4acb-8be1-c4b0847179df` mantiene `DATABASE_URL` apuntando al **original**, y NO SE RECONFIGURA ni utiliza.
- Servicio `s01-lab-restore-one-shot` volvió a su imagen de lectura y la variable de aprobación del restore quedó invalidada.

## STG-B11B nuevo recurso

Servicio vacío, exclusivo del entorno lab, creado SIN fuente/despliegue inicial: **`s01-lab-schema-preflight`**, service ID `007db029-c99d-4a68-a965-fd0de3496614`.

Variables autorizadas únicamente:
- `TARGET_DATABASE_URL=${{Postgres-Im3h.DATABASE_URL}}` (referencia privada Railway, nunca mostrar DSN/clave; No `DATABASE_URL` del Postgres original).
- Identidades `RAILWAY_*` inyectadas por plataforma. Sin claves Stripe, PayPal, Resend, Sendgrid o Google y sin secretos de la web.

Código de PR:
- `infra/s01_lab_schema/preflight.py`: exige project/env/service exactos, dominio interno del nuevo servicio, hostname `postgres-im3h.railway.internal:5432/railway`, PostgreSQL versión `180006`, clúster `7696517018472497211` y seis categorías de catálogo vacías. Deniega el clúster original, redes públicas/DSNs secundarios, secretos de proveedores y fallos de consulta. Solo ejecuta `SELECT` con `default_transaction_read_only=on`, timeout y SSL require. No devuelve contraseñas, contenido de tablas ni DSNs.
- `Dockerfile` copia **únicamente** `preflight.py` y arranca `python3 /app/preflight.py`, con PostgreSQL18 + Python; sin Flask, modelo ORM, Alembic, correos, pagos o DDL.
- `test_preflight.py`: 15 contratos negativos/positivos con subprocess fakes, sin acceso Railway. CI construye imagen y comprueba denegación fuera del servicio exacto.

## Fase de ejecución solo lectura

Tras CI exitosa y revisión de SHA, se admite conectar a ese servicio la PR B11B bajo `rootDirectory=/infra/s01_lab_schema`, `dockerfilePath=Dockerfile`, `startCommand=python3 /app/preflight.py`, restart `NEVER`, cron ausente, sin dominio ni TCP proxy, sin volumen, sólo `TARGET_DATABASE_URL` a copia recuperada. **Una sola ejecución de lectura**; la ejecución no autoriza migraciones.

La validación real desde el servicio demuestra que la ruta efectiva va a `Postgres-Im3h`. Con resultado PASS, queda pendiente otra PR que incorpore únicamente un ejecutor administrativo de esquema con puerta independiente de aprobación humana. Debe prohibir pasar `DATABASE_URL` del origen, fijar la semilla/versionado, contemplar fallos parciales y bloquear segundo intento.

## NO-GO

- **No** ejecutar `db.create_all`, `flask db upgrade`, `bootstrap_db.py` ni `pg_restore` nuevos durante B11B.
- No cambiar el servicio `s01-lab-maintenance` actual ni el clúster original; no fusionar ninguna PR ni mover `main`.
- No activar pagos, email, endpoints web o cron; nunca usar identidad del servicio web para ejecutar migraciones.
- La primera DDL real en `Postgres-Im3h` requiere una autorización humana específica y un commit inmutable probado.

**Estado esperado:** servicio privado y temporal de solo lectura validado; base recuperada sigue vacía.
