# S01 · STG-B09 — Auditoría pre-bootstrapping PostgreSQL 18 del laboratorio

**Fecha:** 13/10/2026 · **Autorización:** exclusivamente auditoría y pruebas preparatorias, **NO** ejecutar cambios en la BD. **Resultado:** preparación técnica documentada, **NO-GO** para DDL, bootstrap, despliegue o web pública.

## A. Evidencia de infraestructura, solo lectura

| Elemento | Estado al auditar |
|---|---|
| Proyecto lab privado | `fiscal-cripto-s01-lab` — `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e` |
| Entorno Railway | `lab` — `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8` |
| PostgreSQL 18 propio | Servicio `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, imagen `ghcr.io/railwayapp-templates/postgres-ssl:18`, estado deployment SUCCESS, privada `postgres.railway.internal` |
| Volumen DB propio | `c35d178f-7473-4d0b-adb9-1faae815b7af`, montado exclusivamente en PostgreSQL |
| Web laboratorio | Servicio `s01-lab-web` / `212f4f52-b349-4387-a046-9f6b08237d2e`, fuente null, **0 deployments**, sin dominio o TCP proxy público |
| Variables web | 12 variables propias aplicadas; `SECRET_KEY` confirmada **SELLADA** a través de `sealedVariableNames`, valor **NUNCA consultado**. DB_URL procede de referencia al servicio Postgres del proyecto lab (preparado en STG-B07). |
| Cambios Railway en lab | **0 staged**; PostgreSQL sigue online y web sigue sin despliegue |
| Estado SQL | **Última consulta del propietario**: PostgreSQL `180006` (18.6), BD `railway`, `public` **0 tablas**. **No hay una consulta SQL nueva realizada por B09**. No podemos afirmar que la base siga vacía hasta repetir lectura inmediatamente antes de cualquier DDL. |

**Limitación de verificación:** la herramienta conectada de Railway no ofrece ejecutar consultas SQL read-only ni confirmar por sí sola el valor resuelto de la referencia `DATABASE_URL`; solo expone nombres de variables y metadatos de servicio. No imprimir URL de conexión, contraseña o secreto para compensar esta limitación. El DNS `postgres.railway.internal` puede repetirse en proyectos separados; confirmar **referencia del mismo proyecto** y aislamiento de red, no solo hostname.

## B. Versión y grafo de migraciones: comprobación estática independiente

**SHA exacto del candidato auditado:** `9f8060ce2e096165b33dbae25276c91d52f4ed15` (PR #63, DRAFT basada sobre #62).

1. `bootstrap_db.py` importa `app` (por tanto requiere superar primero `security_config`, `S01-LAB-LOCK` y `STG-LOCK-001`). Solo acepta PostgreSQL **totalmente vacío** como fuente de esquema nuevo; `db.create_all()` está únicamente en el entrypoint administrativo explícito, nunca en un request/Procfile.
2. En el caso limpio, tras crear las tablas del modelo actual, comprueba columnas y que **todas las tablas carecen de filas**, después utiliza `stamp(revision="m6n7o8p9q0r1")` y `upgrade()`. El stamp aquí **forma parte del bootstrap expresamente escrito** para una base totalmente nueva, **no** es un `stamp head` arbitrario o reparación de una base poblada.
3. Se inspeccionaron los metadatos `revision` y `down_revision` de **13 archivos** desde `m6n7o8p9q0r1` hasta `z9a0b1c2d3e4`: cadena **lineal** comprobada, sin salto entre revisiones consecutivas; las tres S01 finales son `x7y8z9a0b1c2`, `y8z9a0b1c2d3` y `z9a0b1c2d3e4`.
4. `n7o8p9q0r1s2` inserta el registro de recursos educativo con slug `experimento-bitcoin`, si falta. En una base nueva, tras bootstrap habrá un recurso semilla por diseño: **no interpretarlo como copia de clientes**; verificar `resources` = 1, `resource_requests` = 0 y ausencia de usuarios/reportes/pagos.
5. `startup_schema_gate.py` exige exclusivamente PostgreSQL, `alembic_version` con **`z9a0b1c2d3e4`**, columnas S01, tablas financieras, CHECK/índices. Inicia inspección en una transacción `SET TRANSACTION READ ONLY` y concluye con rollback.
6. `Procfile` ejecuta **`python startup_schema_gate.py && gunicorn ...`**, sin bootstrap. Si la DB está en cero tablas, una web conectada debe **negar el arranque**, no crear tablas.
7. S01 tiene **tres tablas nuevas** `s01_stripe_checkout_attempts`, `s01_stripe_event_receipts` y `s01_stripe_notification_outbox`; ninguna debe contener eventos, capturas ni pagos. El esquema completo esperado a contrastar contra el ORM y Alembic es de **18 tablas** (14 aplicación pre-S01 + 3 S01 + 1 Alembic), bajo reserva de auditoría final de nombres y versión.
8. `y8...` y `z9...` prohíben explícitamente downgrade para evitar destrucción del histórico financiero. No hay autorizado ningún `alembic downgrade` ni eliminación/restauración destructiva.
9. `migrations/env.py` reconstruye una URL SQLAlchemy con `hide_password=False` para Alembic. La operación futura **debe evitar logging DEBUG, tracebacks, ecos de variables y comandos que impriman DSN**. Diseñar preflight sin exponer contraseña.

## C. Evidencia de pruebas sintéticas existente (no nuevo DDL)

La ejecución [Required CI #38469018552](https://github.com/MarianoSevilla/fiscal-cripto-/actions/runs/38469018552) correspondió al **mismo SHA `9f8060ce...`** y concluyó SUCCESS para 3/3 jobs: **1.904 Python PASS, 63 SKIP**, PostgreSQL 18 CI PASS, Chromium PASS; STG-B06 offline PASS.

La batería PostgreSQL solo utiliza el localhost de runners de GitHub y datos falsos:

- `qa_db_bootstrap_postgres.py`: import de Flask sin DDL; gate falla con 0 tablas; bootstrap explícito fresco; head final; recurso semilla; repetición no duplica; DB poblada sin Alembic rechazada; tabla parcial rechazada; head antiguo y CHECK ausente fallan cerrados.
- `qa_s01_g04_six_legacy_pg18.py`: 6 expedientes **sintéticos** a revisión `v5w6x7y8z9a0` → `z9a0b1c2d3e4`, preservación del historial, tablas S01/constraints e índices.
- `qa_s01_recovery_gate_pg18.py`: conserva snapshot sintético, prueba prefreeze de rutas financieras, gate fail-closed con head incorrecto y constraint ausente.
- `qa_stg_b04_lab_app_isolation.py` (actualizada en B06): identidad exacta del web en CI **sin conexiones de red/DB/proveedores**; 20 rutas sensibles 503.

**Estas pruebas NO son un ensayo de despliegue real en Railway, no han migrado el laboratorio y no prueban disponibilidad de un ejecutor administrativo allí.**

## D. BLOQUEO DE DISEÑO: NO existe aún ejecutor administrativo seguro

**Hallazgo B09-001 (bloqueante):** el servicio de aplicación `s01-lab-web` no tiene código ni instancia ejecutándose, y **`bootstrap_db.py` importa `app.py`**. `S01-LAB-LOCK` fija el **ID real del web**, su `RAILWAY_PRIVATE_DOMAIN`, `PORT`, `APP_BASE_URL`, proyecto, entorno, modo y la referencia a BD. Por tanto, un *servicio de mantenimiento nuevo con otro `RAILWAY_SERVICE_ID`* **sería rechazado antes de conectar a DB**, tal como exige el control de seguridad.

**No hacer ninguna de estas maniobras:**
- Copiar o simular `RAILWAY_SERVICE_ID` de `s01-lab-web` para ejecutar desde otro servicio; constituiría una suplantación de identidad y un bypass del aislamiento.
- Conectar GitHub al web y configurar un `preDeployCommand` que migre automáticamente: eso acoplaría la mutación de DB a la primera publicación web, vulnerando la separación de autorizaciones y complicando rollback.
- Abrir proxy TCP público para conectar desde Mac/CI; usar credenciales de production/staging; ejecutar una migración desde scripts CI autorizados solo para `127.0.0.1`.
- Sustituir el bootstrap por SQL ad hoc o `alembic stamp head` sin pruebas.

**Solución propuesta, para nueva autorización:** preparar primero **un servicio de mantenimiento efímero, privado y sin fuente**, cuya identidad real Railway se capture antes de otra PR de código. Implementar una ruta de import/ejecución exclusiva para ese ID que admita **solo comando administrativo** con host/DB de laboratorio, sin Flask HTTP escuchando, sin credenciales financieras ni correo y sin banderas genéricas de bypass. Auditar CI con fallos para otros IDs, proyectos, host/DSN, puertos, datos existentes e intentos de repetición. Conectar **solo ese ejecutor**, usar SHA exacto y comando único, bajo autorización DDL separada y duración/coste controlados. Si no se acredita cómo desconectar/hacer one-shot sin autodeploy, STOP. No crear ese servicio todavía.

## E. Recuperación: requisitos aún sin probar en laboratorio

Railway documenta respaldos de volumen y, donde corresponda, PITR mediante CLI (`railway postgres pitr backup...`). Aquí **NO se ha creado backup ni se ha comprobado la política de retención o capacidad de restauración**. El laboratorio parte de una BD que el propietario vio vacía; aunque no tenga expedientes, las escrituras de bootstrap son irreversibles sin plan de restauración o reconstrucción en caso de fallo parcial.

Antes de DDL: confirmar plan/coste, mecanismo autorizado de backup/volumen o recreación segura de BD sintética, congelación de cambios, garantía de que los scripts de mantenimiento se ejecutan solo una vez, captura del estado previo y procedimiento de recuperación **sin** `alembic downgrade` ni borrar DB de usuarios. Preparar respuesta si create_all/stamp/upgrade falla a mitad, sin seguir sobre un esquema parcial.

No reiniciar ni sustituir el Postgres del laboratorio para hacer pruebas de recuperación sin autorización adicional.

## F. Consulta de solo lectura para la próxima verificación (NO ejecutada por ChatGPT)

Antes de autorizar DDL, solicitar al propietario ejecutar **exclusivamente en Postgres del proyecto `fiscal-cripto-s01-lab`**, desde el editor SQL de Railway, este SELECT de metadatos:

```sql
SELECT
    current_database() AS db,
    current_setting('server_version_num') AS pg_version_num,
    COUNT(*) FILTER (WHERE c.relkind IN ('r','p')) AS public_tables,
    COUNT(*) FILTER (WHERE c.relkind IN ('v','m','f')) AS public_views,
    COUNT(*) FILTER (WHERE c.relkind = 'S') AS public_sequences,
    COUNT(*) FILTER (WHERE c.relkind IN ('i','I')) AS public_indexes
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public';
```

Resultado esperado ANTES del bootstrap: `db=railway`, `pg_version_num` entre 180000 y 189999, **todos los contadores cero**. Si cualquier contador no es cero, STOP sin ejecutar script. La base existente de staging (`v5w6x7y8z9a0`) NO es un destino válido.

Esa lectura no demuestra por sí sola la identidad del proyecto: cotejar en Railway el servicio `Postgres`, su ID, env `lab` y el DSN efectivo **sin imprimir secretos**.

## G. Gates y estado

| Gate | Estado |
|---|---|
| Aislamiento de proyecto/entorno Postgres vs prod/staging | **PASS** por inventario Railway read-only (no conecta SQL) |
| Web sin código/URL pública; secreto sellado | **PASS** |
| PR #63, single-head, CI PG18 sintética | **PASS**, SHA `9f8060ce...` |
| Revalidación SQL de DB lab inmediatamente antes de DDL | **PENDIENTE** |
| Procedimiento de mantenimiento sin web deploy y sin identidad suplantada | **BLOQUEADO B09-001** |
| Backup/reconstrucción ensayable y coste acordado | **PENDIENTE** |
| Autorización para alta de runner / modificación de barrera | **NO concedida** |
| Autorización DDL/bootstrap | **NO concedida** |
| Autorización para conectar y desplegar web | **NO concedida** |
| GO global para inicializar PostgreSQL Railway | **NO-GO** |

**Entrega de B09:** auditoría estática y de la infraestructura y revisión de pruebas existentes, con bloqueo identificado. Ningún cambio de BD, servicio, variable de entorno, deploy ni merge. `main` / Railway producción y staging originales siguen pendientes de integración S01, NO cambiarlos.
