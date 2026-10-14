# STG-B10P · Protocolo de liberación del restaurador: **NO-GO real** (14/10/2026)

## 1. Decisión operativa de la fase
Esta PR **solo prepara el mecanismo de liberación y su auditoría sintética**. No se han ejecutado migraciones ni restauraciones en Railway. El propietario permitió avanzar con la preparación, **no autorizó específicamente una escritura real** en PostgreSQL.

El origen de producción y la web siguen fuera del alcance de la fase.

## 2. Evidencia verificada y fijada

| Recurso | Identidad inmutable |
|---|---|
| Proyecto Railway S01 | `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e` |
| Entorno `lab` | `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8` |
| PostgreSQL **original** (prohibido como destino) | servicio `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`, cluster `7696213098351943739` |
| PostgreSQL **recuperación** | servicio `317b21e9-b259-4b15-902a-a7bec69b7407`, volumen `16144c31-17d5-49e7-a725-967e883e03f9`, cluster `7696517018472497211` |
| Ejecutor `s01-lab-restore-one-shot` | servicio `dc26ad37-ca87-4813-b85f-7a6f23d60527`, sin volumen ni dominios públicos, restart `NEVER`, cron desactivado |
| Bucket privado de recuperación | `s01-lab-recovery-20261014` / `s01-lab-recovery-20261014-ehk810`, región física AMS, API S3 `auto` |
| Objeto en bucket | `s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom` |
| SHA256 exacto del objeto | `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab` |
| Código activo en servicio de restauración | SHA `c39e046e82ac59cfe7731fbcb6df064efe697b0d`, imagen que **solo copia `probe.py`** |
| Prueba previa del destino | despliegue de sonda readonly `9ab448c9-310c-41fb-83d5-e95da06daccb`: PG18.6, cluster exacto, 6 categorías de objetos vacías |

Copia REAL descargada y verificada previamente desde bucket (B10L); restauración de copia REAL **aún no efectuada**.

## 3. Qué añade B10P

- `infra/s01_lab_restore/release_gate.py`: liberación de código **literalmente desactivada**. `LIVE_RESTORE_RELEASED=False`, `restore_release()` devuelve `NO-GO` para cualquier entrada. Si alguien cambia el boolean a `True` sin revisar el mecanismo de autorización, sigue sin ejecutar nada: `INVALID_RELEASE_GATE`.
- `Dockerfile.candidate-disabled`: imagen de prueba que contiene `probe.py`, `restore_candidate.py`, `release_gate.py`, `boto3` fijado y cliente PG18.6. Su único `ENTRYPOINT` es `release_gate.py`, que aborta siempre antes de tocar S3 o SQL. **Esta imagen no está configurada ni desplegada en Railway**.
- La imagen de Railway que ya existe se sigue construyendo desde `Dockerfile`, que solo contiene la sonda READ ONLY y **excluye** los dos nuevos archivos.
- `test_release_gate.py`: contratos negativos sobre boolean no habilitable, variables de entorno manipuladas, denegación de main y contenido de ambas imágenes. No hay una ruta de restauración en `main()` de B10P.
- Nueva CI: pruebas B10N, B10O y B10P, build de la imagen readonly y candidata, arranque de la imagen candidata con flags falsificados y exigencia de aborto.

## 4. Requisitos para una fase FUTURA de liberación real

La aprobación nunca vendrá dada por el CI verde o por fusionar código. Una fase nueva deberá realizar, **en ese orden**, las siguientes acciones y reportar evidencia:

1. **Congelar código y revisión independiente:** SHA completo nuevo, árboles/diffs sin código de la aplicación, PR DRAFT, test exacto del punto de entrada ya activado y build de la imagen concreta a desplegar. Evitar usar una rama que pueda avanzar mientras se despliega.
2. **Comprobar origen**: servicio/volumen de origen no cambiaron; no existe ningún enlace `DATABASE_URL` del servicio restaurador con el Postgres original.
3. **Comprobar destino**: `Postgres-Im3h` healthy, volumen propio, fingerprint `7696517018472497211` y esquema vacío desde el ejecutor *inmediatamente antes* de cualquier restauración real. Distinto del original.
4. **Comprobar backup**: bucket privado de S01, objeto exacto y SHA256 de los bytes descargados, longitud y cabeceras, formato custom PG18.
5. **Comprobar aislamiento del ejecutor**: sin dominios públicos, TCP proxies, cron, reintentos ni credenciales de Stripe, PayPal, correo o web, start command de una sola ejecución; no pasar secretos a logs/GitHub.
6. **Autorizar específicamente**: el propietario debe aprobar una única escritura `pg_restore` **solo** en servicio `317b21e9-b259-4b15-902a-a7bec69b7407` / volumen `16144c31-17d5-49e7-a725-967e883e03f9`, reconociendo que escribirá datos y un marcador de intento S3 que no se elimina automáticamente.
7. **Ejecutar una sola vez** desde artefacto inmóvil con `restartPolicyType=NEVER`; nunca permitir conexión al original. El candidato exige doble preflight, `pg_restore --single-transaction --exit-on-error`, sin `--create/--clean`, y postflight. Abortar ante cualquier cambio o sospecha.
8. **Verificar post-restauración**: recuperar versión/huella del destino, clasificación de catálogo vacío, hash fuente/S3 y estados de objetos; registrar evidencias sin contenido personal. Comprobar otra vez que original mantiene su huella y sin cambios.
9. **Incidencias**: ante error o interrupción, mantener el marcador S3 y el destino tal cual; NO reintentar, no borrar/resetear original ni destino automáticamente, investigar el resultado SQL/manual y pedir un nuevo permiso si se requiere otra acción.

`sslmode=require` significa cifrado, pero no autentica el certificado del servidor como `verify-full`. La huella y pins internos son controles operativos adicionales, no una garantía criptográfica completa. El backup lógico de `railway` **no** es una copia integral de roles/globales/volumen del clúster.

**PROHIBICIONES B10P:** no desplegar ninguna imagen de restauración, no invocar `restore_once` en Railway, no ejecutar DML/DDL real, no migraciones, no fusionar PR, no iniciar web, no alterar la fuente ni activar pagos/emails.

## 5. Criterio de salida

La fase queda **PREPARADA** cuando GitHub CI del commit de la PR marque éxito y Railway continúe ejecutando solo la sonda de lectura con 0 procesos activos. Este resultado no cambia el estado **NO-GO PARA RESTAURACIÓN REAL**.
