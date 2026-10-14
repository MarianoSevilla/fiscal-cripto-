# STG-B10N — Sonda de identidad del destino S01 · 14/10/2026

**Tipo:** GitHub DRAFT + pruebas sintéticas, no restauración SQL real. La PR está apilada sobre #76 STG-B10M y no introduce código de restauración en el contenedor.

## Evidencia independiente del propietario

Consulta SQL ejecutada en **Railway → Postgres-Im3h → Database → Query**:
- Base de datos: `railway`
- PostgreSQL `server_version_num=180006` (18.6)
- **Clúster de recuperación `7696517018472497211`**
- Relaciones, funciones y tipos de usuario en `public`: **0 / 0 / 0**.
- Consulta adicional: esquemas no estándar, extensiones no estándar, triggers de evento: **0 / 0 / 0**.

El clúster original **`7696213098351943739`** es diferente. Ambas lecturas anteriores se originaron en la consola del nuevo Postgres; todavía faltaba corroborar por el proceso administrador privado. El identificador del clúster ayuda a distinguir recursos pero no sustituye autenticación TLS con validación de certificado.

## Inventario Railway comprobado

Proyecto `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, environment `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- Origen Postgres `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, deployment `cf076b94-1f68-4d31-b143-3277d40ef188`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`.
- Destino `Postgres-Im3h`, service `317b21e9-b259-4b15-902a-a7bec69b7407`, deployment `d88ec988-a600-4398-9421-7843d872f5b9`, volumen independiente `16144c31-17d5-49e7-a725-967e883e03f9`.
- Servicio restaurador vacío `s01-lab-restore-one-shot`, ID `dc26ad37-ca87-4813-b85f-7a6f23d60527`, `rootDirectory=/infra/s01_lab_restore`, start `/opt/venv/bin/python /app/probe.py`, restart NEVER; sin cron, fuente, despliegue, volumen ni dominios/proxy públicos. **La start command configurada no coincide todavía con el Dockerfile de esta nueva sonda**: se debe conciliar mediante auditoría independiente antes de cualquier despliegue. El Dockerfile contiene el ENTRYPOINT efectivo `python3 /app/probe.py`; no adivinar comportamiento del override de Railway.
- El servicio tiene variables de conexión `TARGET_DATABASE_URL` referidas al Postgres **nuevo**, variables de bucket con valores secretos ocultos, y **ninguna variable fuente `DATABASE_URL`**.
- Respaldo real de S01 lab en bucket privado, SHA256 `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`; **este programa no lo lee**.

## Sonda de esta PR

`infra/s01_lab_restore/probe.py` rechaza cualquier proyecto/entorno/servicio o destino no fijado exactamente, `DATABASE_URL` del origen, proveedores, marcadores públicos y cambios de huella. Ejecuta un único `psql -X -A -t -c SELECT ...` con `PGOPTIONS=default_transaction_read_only=on`; obliga a `transaction_read_only=on` y **compara exactamente `7696517018472497211`**. Espera 0 objetos en las seis categorías y PostgreSQL 18.6. Redacta detalles de fallos sin imprimir credenciales, DSN o resultados de tablas.

La imagen aislada copia **solo `probe.py`**, no contiene el `restore.py` propuesto anteriormente, ni SDK S3, ni Flask, modelos, Alembic o interfaz HTTP. Que una sonda supere CI no confiere autorización SQL de escritura.

## Próximos controles todavía NO-GO
1. CI offline de esta PR B10N sobre SHA exacto en GitHub, revisión de código e identificación correcta del start command del servicio Railway.
2. Solo después, comprobación desde la sonda real del mismo clúster destino (sin acceso al original). Si falla, STOP; no deshabilitar pins para conseguir PASS.
3. Revisar en PR distinta un restaurador real de una sola ejecución, sin acceso a la DB original, con validación de archivo y SHA, comprobación de destino vacío, prevención de reintentos y postflight.
4. Autorización **separada y específica** antes de cualquier `pg_restore` real en `Postgres-Im3h`. No se ha llevado a cabo hasta esta fase.

**Prohibido:** fusionar PR, activar web, pagos, correo, migraciones o alterar base/volumen original.

## Evidencia final de la prueba privada (14/10/2026)

- [CI #38579144913](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38579144913): **SUCCESS**, 14/14 unittest, build de contenedor `postgres:18.6-bookworm` y rechazo de lanzamiento con identidad no fijada.
- Código ejecutado inmutable: `c39e046e82ac59cfe7731fbcb6df064efe697b0d`; ejecución Railway `9ab448c9-310c-41fb-83d5-e95da06daccb`, servicio privado `s01-lab-restore-one-shot`.
- Registro exacto: `S01 STG-B10N PROBE PASS: target PG18.6, pristine, cluster=7696517018472497211, different from original`.
- La prueba de solo lectura del proceso privado coincide con la huella proporcionada previamente desde la consola de `Postgres-Im3h`; las seis categorías de objetos no previstos devolvieron cero.
- Para desplegar la sonda se corrigió únicamente el comando de arranque del servicio de `/opt/venv/bin/python /app/probe.py` a `python3 /app/probe.py`, conservando `restartPolicyType=NEVER`, cron vacío, sin dominios ni proxies públicos, sin volúmenes.
- No se ejecutó `pg_restore`, ningún comando de inicialización SQL ni aplicaciones Flask; el código conectado contiene exclusivamente `probe.py` y no incluye el restaurador de archivo.
- La integración de código **queda en DRAFT**. El ejecutor en Railway permanece fijado al SHA anterior al commit documental; publicar una evidencia en GitHub no equivale a redeploy.
- **NO-GO** para la restauración real, las migraciones, la fusión de PR, web, pagos y correos hasta revisar por separado y autorizar el código exacto de restauración de una sola ejecución.
