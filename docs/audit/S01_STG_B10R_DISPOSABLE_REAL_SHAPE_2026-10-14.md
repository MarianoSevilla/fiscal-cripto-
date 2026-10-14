# STG-B10R — Preparación del ejecutor final, bloqueado antes de RESTORE real

**Fecha:** 14/10/2026. **Estado:** PROVISIONAL; PR draft y GitHub CI solamente. El usuario dijo «procede» tras B10Q, por lo que se continúa la preparación de un ejecutor final, sin interpretar la autorización genérica como una aprobación específica del commit ejecutable de escritura.

## Huellas y recursos fijados

- Railway S01: project `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, environment lab `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- **Origen prohibido para SQL de escritura o restauración:** Postgres service `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volume `c35d178f-7473-4d0b-adb9-1faae815b7af`, system_identifier `7696213098351943739`, deployment `cf076b94-1f68-4d31-b143-3277d40ef188`.
- **Destino de eventual restauración**: `Postgres-Im3h` service `317b21e9-b259-4b15-902a-a7bec69b7407`, volume `16144c31-17d5-49e7-a725-967e883e03f9`, system_identifier `7696517018472497211`, deployment `d88ec988-a600-4398-9421-7843d872f5b9`. PostgreSQL 18.6, sin objetos de usuario ni extensiones extra antes de la operación.
- Servicio administrativo privado `s01-lab-restore-one-shot` ID `dc26ad37-ca87-4813-b85f-7a6f23d60527`, sin dominios/TCP, sin volumen, restart `NEVER`, sin cron, referencia a `TARGET_DATABASE_URL=${{Postgres-Im3h.DATABASE_URL}}` exclusivamente. **No cuenta con `DATABASE_URL` del Postgres original**.
- Bucket privado AMS `s01-lab-recovery-20261014-ehk810`; objeto exacto `s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom`, SHA256 real `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`.
- B10Q lectura REAL en Railway `7211c2b0-48f8-4328-b5f4-3a33d7232aec` **PASS**: hash comprobado tras descarga, `pg_restore --list` OK, doble comprobación readonly de clúster destino exacto. Este es el único despliegue autorizado para el servicio hasta nuevo permiso.

## Qué implementa B10R

- Nuevo `infra/s01_lab_restore/real_restore_entrypoint.py`, diseñado como el futuro punto de entrada que sustituirá a la sonda cuando exista autorización. En esta PR su `LIVE_RESTORE_AUTHORIZED_IN_SOURCE` es **literal `False`** y `entrypoint()` siempre deniega; incluso si alguien cambia el valor a `True` sin revisar el mecanismo, deniega por `SOURCE_GATE_TAMPERED`. Ninguna variable o argumento permite habilitarla.
- `Dockerfile.real-restore-disabled` crea una imagen separada que **sí incluye** `restore_candidate.py` y este entrypoint bloqueado. La imagen NO es la configurada en Railway. El servicio real permanece anclado a `Dockerfile.readonly-archive` y a un SHA inmutable de B10Q.
- `test_real_restore_entrypoint.py`: pruebas de denegación incluso si el usuario intenta activar mediante entorno, flags o modificaciones triviales.
- `qa_b10r_real_shape_ci.py`: prueba **más fiel del procedimiento completo**, con dos PostgreSQL18 Docker realmente desechables; origen sintético vacío, `pg_dump -Fc` real, lector SQL/PG18 realmente apuntando al segundo contenedor, restauración mediante `restore_candidate.restore_once()` y `pg_restore --single-transaction --exit-on-error`, postflight y segunda ejecución rechazada. Solo el cliente S3/marker es un sustituto local en memoria. No contiene credenciales ni datos Railway y rechaza un entorno con `RAILWAY_*` o `DATABASE_URL`.
- CI contiene todas las suites B10N/B10O/B10P/B10Q/B10R más build de la imagen BLOQUEADA, y comprueba rechazo del arranque sin imprimir secretos, seguido de integración real con PostgreSQL18 CI. Ningún Docker CI se conecta al PostgreSQL S01 ni al bucket AMS.

## LIMITACIONES y qué se requiere para restaurar de verdad

- El archivo real y la base nueva ya están identificados; su legibilidad, hash y preflight real se comprobaron en B10Q, **pero aún no se ha probado el efecto real de `pg_restore --dbname` sobre el destino Railway**.
- La copia lógica de una base vacía no cubre necesariamente roles/globales de clúster, configuraciones, ni validación de otros objetos fuera del dump; no sustituye un plan físico de recuperación.
- Para autorizar una escritura concreta se debe preparar **un commit nuevo** cuyo punto de entrada llame explícitamente `restore_candidate.restore_once`, tras una revisión independiente, CI completa y bloqueo de múltiples intentos, y establecerlo por SHA inmutable. Es una versión diferente de esta PR, que NO puede ejecutar restauraciones.
- El restaurador escribe un marcador S3 permanente mediante `IfNoneMatch=*` como control cooperativo de reintentos. Hay que confirmar la semántica efectiva del backend de objeto y los riesgos de un fallo parcial antes de activarlo. Ni el marcador ni la huella sustituyen ACL/autenticación ni un control de concurrencia de otros escritores.
- Es obligatoria **autorización específica final** de una sola escritura a `Postgres-Im3h`, aceptación del marcador S3 y de que ante cualquier error se detendrá sin reintentos. No usar `--clean`, `--create` ni mutar el Postgres original.
- Railway y `main` no se alteran al crear esta PR; ninguna PR se fusiona ni se despliega web, pagos, correo, o migraciones SQL de aplicación.

**NO-GO RESTAURACIÓN REAL EN B10R**: esta rama no habilita ni ejecuta la operación, únicamente deja preparado y ensayado el procedimiento.
