# STG-B10Q — Auditoría privada del archivo real antes de autorizar restore

**14/10/2026.** STG-B10Q es una fase de **lectura exclusivamente**: no restaura, no inicializa, no migra, no altera la base de origen ni la base de destino. Ningún resultado CI equivale a permiso de escritura.

## Contexto verificado

- Proyecto S01 `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, entorno `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- Origen `Postgres`: servicio `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`, cluster `7696213098351943739`.
- Destino `Postgres-Im3h`: servicio `317b21e9-b259-4b15-902a-a7bec69b7407`, volumen `16144c31-17d5-49e7-a725-967e883e03f9`, cluster `7696517018472497211`.
- Servicio lector privado `s01-lab-restore-one-shot` `dc26ad37-ca87-4813-b85f-7a6f23d60527`: sin dominios públicos/proxies, sin volumen, sin cron, restart `NEVER`.
- Respaldo real B10L en bucket privado S01, región física AMS, API `https://t3.storageapi.dev`, S3 region `auto`, nombre `s01-lab-recovery-20261014-ehk810`; clave `s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom`; SHA256 `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`.
- STG-B10N confirmó desde la sonda real el clúster de recuperación PG18.6 y las seis categorías de objetos no previstos a cero, deployment `9ab448c9-310c-41fb-83d5-e95da06daccb`.
- B10O/B10P son candidatos de restauración todavía **NO-GO**, nunca desplegados. La PR #79 mantiene bloqueo `LIVE_RESTORE_RELEASED=False`.

## Objetivo B10Q
Comprobar en el **mismo entorno privado del servicio restaurador**, antes de habilitar un restore, que sus referencias S3 realmente resuelven al objeto correcto, que éste es descargable e íntegro, que `pg_restore --list` puede interpretar el archivo **sin modificar ninguna base**, y que el clúster de destino continúa vacío.

`infra/s01_lab_restore/preflight_archive.py` ejecuta:
1. Validación del proyecto/env/service/hostname/destino DB; rechaza conexión a Postgres original, secretos de proveedores y marcadores de red pública, con aceptación limitada de `PORT`.
2. `probe.probe` readonly con `PGOPTIONS=default_transaction_read_only=on` y huella EXACTA `7696517018472497211`.
3. Lecturas `S3 HEAD` y `S3 GET` exclusivamente contra bucket/objeto inmóviles. Compara metadatos, longitud 5..50 MiB, `PGDMP` y hash de bytes `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`. Archivo local temporal eliminado automáticamente.
4. Comando `pg_restore --list <archivo>` **sin** `--dbname` ni SQL; no se imprime TOC ni datos.
5. Segunda sonda readonly, para confirmar la huella y vacío del destino después de leer el respaldo.
6. Log único de `PASS` sin credenciales ni datos personales, o rechazo `NO-GO` con códigos predefinidos.

`Dockerfile.readonly-archive` incluye solo `probe.py` y `preflight_archive.py`. Quedan **excluidos** `restore_candidate.py`, `release_gate.py`, Flask, migraciones y providers. La conexión S3 usa HTTPS, retries acotados y credenciales Railway por referencia (no copiadas a GitHub). `sslmode=require` cifra la conexión PG pero no verifica exhaustivamente el certificado.

## Validación / gate

CI contiene pruebas sintéticas positivas y negativas: intentos de apuntar al DB original, proyecto/servicio incorrecto, marcadores públicos, credenciales S3 ausentes, endpoint/bucket incorrectos, archivo truncado, hash incorrecto, cabecera no custom, errores CLI, identidad cambiada entre sondas; y valida que imagen/entrypoint no contienen restaurador. La CI nunca accede a los servicios Railway.

Tras CI y preflight independientes de Railway, **se puede autorizar una única ejecución de lectura** de la imagen B10Q con raíz `/infra/s01_lab_restore`, dockerfile `Dockerfile.readonly-archive`, comando `/opt/s01-preflight-venv/bin/python /app/preflight_archive.py`, restart `NEVER`, cron vacío, no exposición, SHA exacto y variables privadas ya configuradas. No usar `Dockerfile.candidate-disabled` ni un código de restore para este control.

**La autorización de la sonda B10Q, si se ejecuta, NO AUTORIZA** a invocar `restore_once`, `pg_restore` con `--dbname`, crear/escribir SQL real, modificar la copia S3, fusionar PRs o desplegar la web.

## Estado de escritura
**NO-GO para restauración REAL**. Antes de ejecutar cualquier `pg_restore` real se requerirá commit nuevo con un punto de entrada revisado, verificación de artefacto SHA, revisión independiente de parámetros y S3, y permiso específico de una operación única sobre `Postgres-Im3h`, no sobre el origen.

## Resultado real del preflight privado

- CI de `preflight_archive.py` / imagen `Dockerfile.readonly-archive`: [GitHub Actions #38585932260](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38585932260) **SUCCESS**, suites sintéticas B10N 14/14, B10O 22/22, B10P 8/8 y B10Q 20/20, build de la imagen de solo lectura y rechazo de arranque sin identidad.
- Commit inmutable conectado al servicio `s01-lab-restore-one-shot`: **`a76afc14392df42f951d086653e431e3836cb14c`**, configuración raíz `/infra/s01_lab_restore`, `Dockerfile.readonly-archive`, inicio `/opt/s01-preflight-venv/bin/python /app/preflight_archive.py`, restart `NEVER`.
- Deployment Railway **`7211c2b0-48f8-4328-b5f4-3a33d7232aec`** estado **SUCCESS**.
- Registro literal: `S01 STG-B10Q: PASS (READ ONLY; target cluster=7696517018472497211; source archive SHA256=1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab; pg_restore LIST checked; no SQL writes)`.
- El archivo real se descargó por S3 GET, se compararon longitud + metadatos + SHA-256 de contenido, se comprobó formato de archivo custom con `pg_restore --list` y la huella de destino antes/después con SELECT readonly. La imagen NO contiene `restore_candidate.py` ni instrucciones de importación.
- Este resultado es evidencia de **legibilidad e integridad del backup real desde el ejecutor privado**, y evidencia de destino PostgreSQL18.6 correcto; **no** confirma que `pg_restore --dbname` se haya ejecutado. La restauración real sigue NO-GO hasta revisión específica y autorización de escritura.
- El commit que documenta este resultado **no se desplegará** automáticamente en el servicio; mantener la referencia al SHA ejecutable anterior.
