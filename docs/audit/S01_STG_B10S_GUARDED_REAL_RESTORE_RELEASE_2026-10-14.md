# STG-B10S — Release candidato de restauración real con autorización explícita

**Fecha 14/10/2026 — PR DRAFT, solo GitHub; SIN ESCRITURAS EN RAILWAY.**

## Decisión

B10R validó mediante CI real dos PostgreSQL18 desechables: función auténtica `restore_candidate.restore_once` con backup generado por `pg_dump -Fc`, `pg_restore --single-transaction --exit-on-error`, pre/postflight y rechazo de segunda ejecución con marcador S3 simulado; CI #38607868049 SUCCESS. El sistema real mantiene respaldo de PG lab verificado mediante S3 HEAD/GET, SHA256 real, `pg_restore --list` y huella destino probados mediante sonda B10Q (Railway deployment `7211c2b0-48f8-4328-b5f4-3a33d7232aec` SUCCESS).

El propietario autorizó continuar la preparación. **Esta PR no autoriza por sí sola restaurar la base REAL**.

## Recurso origen — NO MODIFICAR

- Railway project S01 `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, environment `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- Postgres original service `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`, clúster `7696213098351943739`, despliegue `cf076b94-1f68-4d31-b143-3277d40ef188`.
- Bucket privado AMS `s01-lab-recovery-20261014-ehk810`, endpoint `https://t3.storageapi.dev`, región de protocolo S3 `auto`. Archivo `s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom`, SHA256 exacto `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`.

## Destino autorizado SOLO PARA FUTURA RESTAURACIÓN

- Postgres-Im3h service `317b21e9-b259-4b15-902a-a7bec69b7407`, volumen independiente `16144c31-17d5-49e7-a725-967e883e03f9`, clúster `7696517018472497211`, deployment `d88ec988-a600-4398-9421-7843d872f5b9`.
- Ejecutor privado `s01-lab-restore-one-shot`, service `dc26ad37-ca87-4813-b85f-7a6f23d60527`, sin volumen, proxy ni dominio público, reinicio NEVER y sin cron.
- `TARGET_DATABASE_URL` usa `${{Postgres-Im3h.DATABASE_URL}}`; NO contiene variable `DATABASE_URL` del origen.
- B10N/B10Q verificaron desde consola y servicio privado el clúster exacto y catálogo vacío.

## Código activable exclusivamente con puerta manual en Railway

- `infra/s01_lab_restore/execute_one_restore.py` llama a `restore_candidate.restore_once` **solo después de verificar** que la variable no secreta `S01_RECOVERY_WRITE_APPROVAL` contiene el identificador completo de esta única operación. **La variable NO está configurada hoy**.
- No acepta valores genéricos (`true`, `procede`, `approved`) ni acepta proyecto/servicio/entorno/host distinto, variables de origen, proveedores, S3 incorrecto o datos incompletos.
- `Dockerfile.real-restore-guarded` empaqueta el programa ejecutable, el restaurador y probe con PostgreSQL18 y boto3; **NO es el Dockerfile configurado en el servicio real** (éste continúa usando `Dockerfile.readonly-archive` y commit B10Q `a76afc14392df42f951d086653e431e3836cb14c`).
- `restore_once` descarga el archivo y verifica SHA256/TOC, realiza doble preflight readonly, crea marcador persistente `s01-lab/pg18/restore-intent/target-7696517018472497211.lock` por S3 `IfNoneMatch=*` antes de SQL, ejecuta un único `pg_restore --single-transaction --exit-on-error --no-owner --no-acl --dbname=railway` al DB nuevo, y postflight readonly. Ni `--clean` ni `--create`.
- El marcador S3 persiste incluso si la restauración falla, para impedir reintentos automáticos; NO borrarlo sin nueva evaluación y autorización. El programa se cierra tras una ejecución, sin HTTP/Flask ni scheduler.
- Las pruebas `test_execute_one_restore.py` comprueban denegación incluso si se inyectan flags, proyecto/DB original, S3 incorrecto o falta aprobación. La CI B10S prueba la imagen sin la variable y la resta de suites y restore auténtico solo contra PostgreSQL18 Docker sintéticos, con bucket S3 simulado.

## ÚLTIMA AUTORIZACIÓN REQUERIDA

Para proceder de manera transparente, **después de CI PASS**, mostrar al propietario el SHA exacto de esta PR y el alcance de la escritura:

> Autorizar un ÚNICO intento real de restaurar el backup S01 con SHA256 `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`, sobre Postgres-Im3h service `317b21e9-b259-4b15-902a-a7bec69b7407`, volumen `16144c31-17d5-49e7-a725-967e883e03f9`, clúster `7696517018472497211`, utilizando el ejecutor exacto identificado por SHA de la PR, con marcador S3 de intento único; ninguna acción sobre Postgres fuente, producción, `main`, web, pagos, mails o migraciones.

Solo después de esa aceptación específica se podrán preparar dos cambios en Railway: (1) `S01_RECOVERY_WRITE_APPROVAL` con la cadena fijada y `skipDeploys=true`, (2) asociar el Dockerfile `Dockerfile.real-restore-guarded`, comando `/opt/s01-restore-venv/bin/python /app/execute_one_restore.py`, root `/infra/s01_lab_restore`, source/commit SHA fijado. Revisar de nuevo inventory y CI antes de cada cambio. **No configurar hoy ninguno**.

Tras ejecución: consultar logs y catálogo destino, asegurar 0 objetos extra (copiar DB vacía), archivo hash íntegro y marcador S3 presente, comparar la condición del origen y mantener restaurador parado. Fallos resultan NO-GO y requieren revisión manual; no automatizar recuperación ni intentos repetidos.

### Limitaciones

Un hash y `pg_restore --list` corroboran integridad/legibilidad del archivo, pero sólo el restore real demostrará su restaurabilidad en Railway. S3 `IfNoneMatch` es bloqueo antirreintento cooperativo; no sustituye políticas de permisos o garantías contra concurrentes maliciosos. `sslmode=require` no verifica hostname/CA exhaustivamente. Un dump lógico no incluye roles/globales ni la imagen física del volumen. La escritura sobre `Postgres-Im3h` requiere permiso humano específico.

**NO-GO en esta PR:** no desplegar Dockerfile real, no establecer la variable de aprobación, no escribir a SQL/S3 real, no fusionar PR, no desplegar web ni inicializar el esquema S01 de la aplicación.
