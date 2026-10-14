# STG-B10L — Preparación de backup real PostgreSQL S01 (solo bucket y servicio vacío)

**Fecha:** 14/10/2026. **Autorización:** «procede» para continuar la fase de recuperación real, después de B10K. Conservar la distinción: extracción real de backup != autorización para restaurar, sobrescribir, inicializar schema, integrar PR o desplegar web.

## Inventario y acciones Railway ejecutadas

- Proyecto **S01 lab** `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, entorno `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`; PostgreSQL original `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volumen original `c35d178f-7473-4d0b-adb9-1faae815b7af`, cluster `7696213098351943739`.
- Se ha creado **bucket privado exclusivo** `s01-lab-recovery-20261014` (ID `3e5112d5-39bf-43fa-8602-155e61b06e73`) en **región ams** del entorno lab; nombre S3 `s01-lab-recovery-20261014-ehk810`, API HTTPS `https://t3.storageapi.dev`, región de API `auto`. Las credenciales S3 están **redactadas** por el conector y no se copian al repositorio.
- Se ha creado servicio **vacío e independiente** `s01-lab-backup-reader` (ID `2b2b54f8-3010-4d08-ada4-f2df73f4be2d`) solo en `lab`: sin código fuente, sin volúmenes, sin dominios públicos/TCP proxies, sin deployments hasta autorizar y configurar su ejecución. Nunca usar `s01-lab-maintenance` ni conectarlo a DDL.
- Original Postgres no se reinició ni se modificaron sus variables, imagen, volumen, base o servicios de producción/staging. `main` continúa `56882073295faae3bd1bc3632288a970acb330da`.

## Ejecutor autónomo auditado en esta PR

Solo `infra/s01_lab_backup/Dockerfile` y `backup.py` (nueva raíz de build aislada, sin `app.py`, Alembic ni proveedor financiero). Imagen basada en PostgreSQL18 con herramientas `psql/pg_dump` y Python para S3. El ejecutor:

1. Antes de importar el SDK S3 o abrir socket comprueba pins exactos Railway (`project/env/lab/service/private-domain`), ausencia de dominios públicos en variables, prohibición de secretos de pagos/correo/web, `PORT` legítimo, host exclusivamente `postgres.railway.internal:5432/railway` y nombre/end-point/región del bucket.
2. Ejecuta únicamente consultas `SELECT` al catálogo con `default_transaction_read_only=on` y `sslmode=require` para comprobar PostgreSQL18, huella **`7696213098351943739`** y cero objetos públicos/esquemas o extensiones ajenas a los esperados.
3. Ejecuta **`pg_dump --format=custom --no-owner --no-acl`** con variables `PGHOST/PGPASSWORD` ocultas (no DSN en comando ni logs), copia temporal acotada a **50 MiB**, y repite el preflight. Solo lectura del origen.
4. Guarda exactamente **un objeto S3 privado** bajo clave fija `s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom`, `IfNoneMatch=*` para prevenir sobrescrituras, metadatos de origen/huella/digest y SSL/TLS en tránsito.
5. Vuelve a leer los bytes del bucket y compara SHA256 del objeto descargado; elimina archivos temporales al salir. Logs solo códigos estáticos o SHA256, jamás contraseñas/DSN/contenidos.
6. Su política de error NO-GO y ausencia de cron/reintentos impide asumir un backup exitoso sin confirmación. **Un objeto remoto íntegro no demuestra restaurabilidad**; es el siguiente gate independiente.

### Variables del servicio backup (solo cuando el ejecutor CI pase y se autorice su conexión)
- `DATABASE_URL = ${{Postgres.DATABASE_URL}}` (referencia Railway del Postgres original en S01).
- `BACKUP_ENDPOINT = ${{s01-lab-recovery-20261014.ENDPOINT}}`
- `BACKUP_BUCKET = ${{s01-lab-recovery-20261014.BUCKET}}`
- `BACKUP_REGION = ${{s01-lab-recovery-20261014.REGION}}`
- `BACKUP_ACCESS_KEY_ID = ${{s01-lab-recovery-20261014.ACCESS_KEY_ID}}`
- `BACKUP_SECRET_ACCESS_KEY = ${{s01-lab-recovery-20261014.SECRET_ACCESS_KEY}}`

No introducir manualmente valores de secreto ni imprimir variables. Railway OAuth oculta los valores resueltos, por eso el ejecutor compara endpoint/bucket y valida la huella del clúster antes de dump.

### Criterios para un futuro despliegue de solo backup (NO ejecutar automáticamente desde esta PR)
- Revisar CI y commit exactos; `main` sin cambios, PR DRAFT; endpoint y DB referencia del mismo proyecto, bucket privado AMS; no servicio extra ni conexión al web.
- Root directory estrictamente `/infra/s01_lab_backup`, Dockerfile `Dockerfile`, ENTRYPOINT `backup.py`; service backup `restartPolicyType=NEVER`, cron ausente, sin volumen, sin dominio ni TCP públicos, una sola réplica.
- Registrar SHA esperado, deployment ID, hash remoto, último estado y evidencia de que el objeto S3 existe con permisos privados. Al fallar el upload, no reintentar ni reparar a ciegas; conservar el estado para inspección.
- No crear servicio PostgreSQL de restauración hasta verificar objeto real y tener plan de destino separado. Restauración real requiere un permiso/etapa independiente, verificación de huella del destino diferente y aceptación de que la BD original no cambia.

**STOP / NO-GO:** ningún comando `pg_restore`, `alembic upgrade`, `db.create_all`, SQL DML/DDL, `DROP`, copia a GitHub, deploy web o proveedores externos. No se autorizan cambios en la base original más allá de SELECT/pg_dump ni modificaciones a `main`.

## Resultado real y evidencia validada

### Incidencias NO-GO y resolución controlada
- Primer deployment reader `4a04aa52-b948-45ac-bd97-096e92fb2b5c`: **`NO-GO (WRONG_BUCKET_DESTINATION)`**, antes de conectar a PostgreSQL. CI inicial 17/17 + Docker image **SUCCESS**.
- Diagnóstico no sensible en código: segunda ejecución `766562b5-70cc-4bea-9e29-bec2d4f9d1ae` detectó `NO-GO (WRONG_BUCKET_DESTINATION:BACKUP_REGION)`. El código no imprimió valores del bucket ni claves.
- La región física del bucket Railway es **`ams`**, mientras la API S3 anuncia región **`auto`**. Solo se corrigió la variable `BACKUP_REGION=auto` del reader; no se cambiaron claves, DSN, servicio Postgres ni destino S3. Actualización `skipDeploys=true`.
- CI corregida [#38547807724](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38547807724): **SUCCESS**, 17/17 contratos, build Docker PG18 y fail-closed. Ejecutado el commit inmutable `1aff998a1cd446ad591492800c534912d4d70a9b` sin código de DDL.

### Evidencia de backup REAL en bucket privado
- Tercer deployment (redeploy mismo build con región API correcta): `a4dffe40-a1ae-4534-a788-989a457733c2`.
- Log exacto: `S01 STG-B10L: PASS (private lab backup, remote SHA256=1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab, source cluster=7696213098351943739, source pristine)`.
- El ejecutor verificó identidad del clúster, PostgreSQL18 y catálogo vacío ANTES y DESPUÉS del `pg_dump`; subió el objeto al bucket privado con `IfNoneMatch=*` y **comprobó que los bytes descargados del bucket dan el mismo SHA-256**.
- Ubicación lógica interna (NO URL pública): bucket `s01-lab-recovery-20261014` / objeto `s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom`.
- Hash SHA256 **`1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`**.
- Railway inspeccionado tras éxito: el Postgres original conserva deployment `cf076b94-1f68-4d31-b143-3277d40ef188`, web lab sin deployment, backup reader `restartPolicyType=NEVER` y **0 réplicas en ejecución**, sin dominios públicos o TCP proxies, 0 cambios pendientes. `main` no se modificó.

### Próxima puerta y estado
**Backup REAL capturado y verificado por descarga/hash, pero RESTAURACIÓN REAL PENDIENTE.** El bucket S3 no contiene una validación de `pg_restore` real: ello exige otro clúster PostgreSQL 18 y volumen NUEVOS, sin acceso desde la web, con identidad/sello distintos y comprobación de esquema vacío restaurado. **No usar botón Restore del volumen original, ni `pg_restore` hacia el origen.**

La PR queda **DRAFT** y este texto es evidencia; no autoriza ejecución de DDL, fusión a main, despliegue web ni pagos.
