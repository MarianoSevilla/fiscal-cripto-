# S01 CLOSEOUT — Única inicialización del esquema en Postgres-Im3h (candidato SIN desplegar)

**14 de octubre de 2026.** PR de integración **DRAFT**. Alcance: preparar y validar el paso que permite **terminar el laboratorio**. NO se autorizan escrituras ni cambios del servicio Railway mediante esta PR.

## Situación confirmada del laboratorio

- Railway proyecto `fiscal-cripto-s01-lab` `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, entorno `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- **Original prohibido para DDL:** Postgres `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, system_identifier `7696213098351943739`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`, último despliegue `cf076b94-1f68-4d31-b143-3277d40ef188`.
- **Destino único:** Postgres-Im3h `317b21e9-b259-4b15-902a-a7bec69b7407`, system_identifier `7696517018472497211`, volumen separado `16144c31-17d5-49e7-a725-967e883e03f9`, despliegue `d88ec988-a600-4398-9421-7843d872f5b9`.
- B10S: una restauración REAL satisfactoria del respaldo del original vacío; archivo S3 SHA256 `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`; intento único, variable de autorización revocada.
- B11B: **sonda de identidad readonly REAL satisfactoria** desde el nuevo administrador `s01-lab-schema-preflight`, ID `007db029-c99d-4a68-a965-fd0de3496614`: deployment `d2b85e25-58d2-4da7-bd67-b5d3db4eba79`, SHA `5b00abe567ab5298b92881fb7cf86f821e15d223`, log literal `S01 STG-B11B: PASS (READ ONLY; schema target PG18.6 cluster=7696517018472497211; pristine)`. Conectado por UI Railway a rama `security/s01-stg-b11b-readonly-schema-target`; el bloqueo del conector de ChatGPT no impide el despliegue autorizado por UI. 0 procesos activos.
- Este nuevo administrador posee **solo** `TARGET_DATABASE_URL=${{Postgres-Im3h.DATABASE_URL}}` como variable propia, restart `NEVER`, sin cron, dominio o volumen público. El administrador anterior `s01-lab-maintenance` sigue apuntando a **Postgres original**; nunca utilizarlo para DDL.
- `main` de GitHub todavía en `56882073295faae3bd1bc3632288a970acb330da`; web de laboratorio sin desplegar; sin cambios pendientes Railway.

## Código de ejecución — Único servicio y alcance

- `fiscal_app_export/schema_preflight.py`: **copia byte a byte** de `infra/s01_lab_schema/preflight.py` B11B, verificada en tests para evitar divergencias. Rechaza proyecto/env/servicio/domino/hostname/puerto/base incorrectos; PG18.6 clúster EXACTO y seis grupos de objetos extras a cero, vía psql read-only.
- `fiscal_app_export/schema_bootstrap_one_shot.py`: **NO se ejecuta por defecto**. Su `main()` exige `S01_SCHEMA_BOOTSTRAP_APPROVAL` igual a `ONE-SCHEMA-BOOTSTRAP:POSTGRES-IM3H:7696517018472497211:z9a0b1c2d3e4`; la variable **NO EXISTE** en Railway. Rechaza literalmente `procede`, `true` y aprobaciones de restore antiguas.
- Tras aprobación exacta: preflight readonly, cabeza Alembic local `z9a0b1c2d3e4`, conexión separada `postgresql://...@postgres-im3h.railway.internal:5432/railway` con SSL require, comprobar identidad del escritor por `pg_control_system` en la **misma conexión**, `pg_try_advisory_lock(2026,1010)`, segundo preflight readonly con lock retenido, luego **una** ejecución `db.create_all(); stamp(m6n7o8p9q0r1); upgrade(z9a0b1c2d3e4)`. Realiza postcheck readonly de migración, tablas, constraints, índices y recurso `experimento-bitcoin`. Suelta advisory lock y termina.
- Reutiliza directamente las funciones de esquema `_minimal_flask_context`, `_check_post_bootstrap` y `assert_graph_head` del ensayo B10C **ya probado** en PG18, sin importar `app.py`.
- `Dockerfile.schema-one-shot` mantiene solo modelos/migraciones y dependencias Python fijadas en `requirements.schema-bootstrap.txt`, sin endpoints web, pagos, tareas o credenciales de otros servicios. **No es el Dockerfile actualmente conectado a B11B**.
- NO se efectúan `DROP`, `--clean`, resets, reintentos, reparación automática ni correos. **Atención: `create_all`, `stamp` y `upgrade` no constituyen una sola transacción**; error a mitad del proceso puede dejar objetos parciales. En caso de NO-GO: PARAR, preservar datos, obtener diagnóstico por vía autorizada y pedir nueva autorización.
- `schema_postcheck_readonly.py` + `Dockerfile.schema-postcheck-readonly`: imagen separada sin ningún escritor. Solo consulta catálogo, cabeza única Alembic, tablas críticas y semilla. Útil para devolver el servicio a modo lectura después de revocar la aprobación, sin ejecutar el B11B preflight que **correctamente rechazaría una base ya no vacía**.
- Suite `test_s01_final_schema_bootstrap_gate.py`: pruebas de autorización, host, identidad, bloqueo y denegación; `test_s01_schema_postcheck_readonly.py`: validaciones de esquema no vacío y parking image. Integración `qa_s01_final_schema_one_shot_pg18.py`: ejecuta el **controlador nuevo real** usando ORM + Alembic sobre base de CI aislada y verifica que segundo intento falla `NOT_PRISTINE`. El test usa un transporte sintético inyectado que jamás entra en el Dockerfile de Railway.

## Secuencia de ejecución real futura — REQUIERE AUTORIZACIÓN ESPECÍFICA

**No ejecutar pasos de esta sección hasta que se obtenga consentimiento explícito para el SHA inmutable final y la escritura delimitada.**

1. Auditoría de solo lectura justo antes del despliegue: `main` inalterada, PR y QA verdes; sin staged Railway, clúster original y volumen intactos; `Postgres-Im3h` mismo servicio/volumen/deployment; B11B deployment PASS y sin réplicas activas; secreto `TARGET_DATABASE_URL` solo referenciado a `Postgres-Im3h`.
2. Confirmar SHA exacto del release CI y fijar fuente sin auto-despliegues. Inspeccionar patch staged antes de aplicarlo. **Solo un servicio** `s01-lab-schema-preflight`, nuevo root `/fiscal_app_export`, nuevo `Dockerfile.schema-one-shot`, start command `/opt/s01-schema-venv/bin/python /app/schema_bootstrap_one_shot.py`, restart `NEVER`, cron vacío; identidad de proyecto/env/servicio, rama SHA y aprobación EXACTA, ningún otro recurso.
3. Una **única acción controlada** de Deploy Changes tras consentimiento. Leer logs; exigir `S01 SCHEMA BOOTSTRAP: PASS` más cabeza Alembic `z9a0b1c2d3e4`; registrar deployment y resultado. Si NO-GO, detenerse; **sin Retry ni Redeploy**.
4. **Revocar inmediatamente la variable `S01_SCHEMA_BOOTSTRAP_APPROVAL`**, usando actualización sin despliegue. Cambiar imagen del servicio **a `Dockerfile.schema-postcheck-readonly`**, misma fuente/root sin importar código de escritura en la nueva imagen; revisar patch de un único servicio y ejecutar una sola comprobación read-only posterior. Confirmar que el servicio retorna a 0 procesos, no queda autorización activa y no hay staged.
5. Registrar el resultado y comenzar el *cierre de PRs* y la comprobación de staging antes de producción. El original permanece intacto. No desplegar pagos ni web automáticamente junto con DDL.

### Limitaciones que requieren vigilancia humana

- `sslmode=require` cifra el canal, pero no proporciona la validación completa `verify-full` de certificado/host.
- Advisory lock protege frente a otros ejecutores cooperativos, pero no ante escritores externos; la base no tiene aún aplicación web desplegada.
- Reintento sin cambios tras un error parcial queda bloqueado porque el catálogo deja de estar vacío; si un fallo ocurre antes de primer DDL, la aprobación debe revocarse igualmente y no reintentarse.
- El marcador de un solo intento de restauración S3 pertenece a B10S y no es un permiso para el bootstrap de tablas.
- Datos de usuario y bases productivas no forman parte de la prueba de laboratorio. La integración de PRs de pagos y seguridad **aún no está cerrada**.

**ESTADO ACTUAL: CÓDIGO CANDIDATO; NO DDL REAL.** Se necesita CI PASS, SHA final confirmado y nueva autorización del propietario.
