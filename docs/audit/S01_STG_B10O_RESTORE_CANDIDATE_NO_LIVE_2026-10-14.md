# STG-B10O — Candidato de restauración real, deliberadamente inejecutable

**Fecha:** 14/10/2026. **Estado:** DRAFT, código y QA offline exclusivamente. No se ejecutó ningún `pg_restore` sobre Railway, no hay nuevo deploy ni modificaciones de variables o volúmenes.

## Hechos verificados

Origen PostgreSQL S01 lab, servicio `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`, clúster **`7696213098351943739`**. Destino independiente `Postgres-Im3h`, servicio `317b21e9-b259-4b15-902a-a7bec69b7407`, volumen `16144c31-17d5-49e7-a725-967e883e03f9`, clúster **`7696517018472497211`**. Ambos PostgreSQL 18.6.

El propietario verificó desde Railway Query seis recuentos de objetos inesperados a cero. Después, el despliegue privado B10N `9ab448c9-310c-41fb-83d5-e95da06daccb` confirmó que la conexión del servicio ejecutor llega exactamente al destino esperado, y catalogó 0 objetos extra, **sin escribir SQL**.

Copia REAL previamente obtenida por B10L desde el origen intacto: bucket privado `s01-lab-recovery-20261014-ehk810`, endpoint `https://t3.storageapi.dev`, región API `auto`; clave `s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom`; SHA-256 **`1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`** verificado por descarga completa.

## Diseño del candidato (`infra/s01_lab_restore/restore_candidate.py`)

- En esta PR, el `main()` SIEMPRE sale con `NO-GO (LIVE_RESTORE_NOT_AUTHORIZED)`. La imagen Docker que Railway ya tiene configurada **solo copia `probe.py`**, ni incluye ni arranca el candidato. No existe un flag de entorno para habilitar el restore en B10O.
- Reutiliza `probe.validate_environment` para pin exacto de proyecto, lab, service runner, dominio interno y `TARGET_DATABASE_URL` al hostname privado `postgres-im3h.railway.internal:5432/railway`; rechaza cualquier `DATABASE_URL` del origen, configuración pública y secretos de proveedores de pagos/email.
- Prueba `probe.probe` **READ ONLY** desde el mismo ejecutor, con PG18.6, `transaction_read_only=on`, clúster `7696517018472497211` y cero objetos en las seis categorías. La huella del original `7696213098351943739` se rechaza expresamente.
- Se conecta solo al bucket privado S3 fijado, comprueba metadatos `sha256`, `cluster`, `pgmajor`, `database` y máximo de **50 MiB**. Descarga el archivo en temporal privado, comprueba longitud, `PGDMP`, SHA-256 de los **bytes** descargados y `pg_restore --list`.
- Verifica por segunda vez la identidad y vacío del destino justo antes de declarar intención.
- Crea atómicamente un **marcador de intento único en el bucket**, con clave `s01-lab/pg18/restore-intent/target-7696517018472497211.lock` y `IfNoneMatch=*`. Incluso si falla después del marcador, se conserva y no se reintenta ni elimina automáticamente. Cualquier intervención posterior exige una revisión independiente de esa marca, del catálogo destino y del estado de la transacción.
- El único comando de escritura SQL que podría invocar una **futura versión ejecutable explícitamente autorizada** sería `pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname=railway`, usando `PGHOST` fijado desde el preflight, SSL require y sin `--clean`, `--create`, `DROP` ni reintentos automáticos. El fichero proviene exclusivamente de SHA-256 fijado y bucket privado. El postflight exige las mismas seis categorías vacías al tratarse de un backup de DB vacía.
- El `--single-transaction` protege frente a escrituras SQL parciales del restore ante errores, sin prometer reversión de cualquier efecto externo o no transaccional. Si el postflight falla, **nunca** se limpia, destruye ni repara el destino automáticamente.
- Resultados de `pg_restore`, datos SQL, DSN, valores de credenciales, body de S3 y errores de SDK no se publican en logs de un futuro ejecutor. Esta PR no contiene un ejecutor de producción, solo función candidata importable para pruebas sintéticas.

## Cobertura B10O

1. Contratos offline positivos y negativos: host original prohibido, huellas incorrectas, catálogos no vacíos, archivo corrupto/cambiado, metadatos S3 incorrectos, archivo excedido, catálogo de archivo ilegible, bloqueo por cambio de destino, replay de marcador, SQL fallo, postflight fallo y ausencia de salida de log con secretos.
2. CI verifica que el contenedor Docker Railway actual **no contiene** `restore_candidate.py` y que ejecutar su `main()` termina siempre en NO-GO.
3. CI PostgreSQL 18 desechable comprueba sintéticamente las opciones `--single-transaction --exit-on-error` de `pg_restore` contra un segundo clúster; no se conecta a Railway ni emplea el respaldo real.

## Bloqueos para fase de ejecución real futura

- Auditoría independiente del código de este candidato y cualquier cambio antes de preparar entrypoint real; SHA exacto de commit revisado, CI completamente verde, revisión de dependencias y seguridad de S3.
- Validar inmediatamente antes del hipotético despliegue en Railway los IDs exactos de los dos Postgres y sus volúmenes, bucket, integridad del objeto, dominio/proxy **ausentes**, `restartPolicyType=NEVER`, sin cron, sin `DATABASE_URL` al origen, `main` intacta y ausencia de cambios pendientes.
- Necesaria **autorización específica explícita** para escribir solo en `Postgres-Im3h`, usando exactamente el SHA/artefacto autorizado, un único intento, aceptación de marcador S3 permanente y de que el destino puede necesitar reparación manual si falla.
- Sin esa autorización: **NO-GO** para restore REAL, bootstrap, migraciones, PR merge, producción, staging, web, Stripe, PayPal y emails.

**Nota:** S3 `IfNoneMatch` es una medida antirreintento cooperativa, no un mecanismo de autenticación ni una garantía absoluta ante un actor malicioso. `sslmode=require` cifra, pero la identidad TLS completa requiere `verify-full` con CA/hostname verificados. Ambas son limitaciones documentadas, no excusas para operar fuera de alcance.


## Resultado de validación B10O

- [Ejecución inicial #38581897895](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38581897895): **SUCCESS**, 14 contratos B10N + 22 contratos B10O, contenedor readonly confirmado sin restaurador y `main()` del candidato NO-GO.
- [Ejecución adversarial definitiva #38582342330](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38582342330): **SUCCESS en ambos jobs**, SHA del código probado `35bca8ea929a40abff6d067186acd6c8152eddcd`.
- Prueba positiva: `B10O PG18 PASS: single transaction restore to a disposable independent PostgreSQL18 DB`.
- Prueba de fallo deliberado: dos tablas anteriores del archive se crearon provisionalmente; una tercera tabla con nombre en conflicto forzó el error de `pg_restore`. Por `--single-transaction --exit-on-error`, PostgreSQL18 **revirtió las tablas anteriores**, preservó la preexistente y registró `B10O ROLLBACK PASS: forced late conflict rolled back preceding tables, target fixture preserved`.
- Todos los recursos de esa prueba son sintéticos y desechables de GitHub Actions; no se modificó `Postgres-Im3h` ni el original.
- **IMPORTANTE:** haber validado el rollback en un caso sintético no equivale a una garantía de que cualquier operación futura pueda revertirse sin intervención. El marcador S3 de un intento real sería persistente, y una incidencia posterior requeriría evaluación manual.
- La CI no incluye claves reales de Railway, no descarga el respaldo real y **no genera una imagen ejecutable con `restore_candidate.py`**. No se concede ninguna autorización nueva de escritura.
