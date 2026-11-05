# SEC5-PRIV — Inventario mínimo de metadatos de adjuntos históricos de asesoramiento

**Corte técnico:** 05/11/2026. **Estado:** preparación y ensayo con datos sintéticos. **NO se ha ejecutado sobre Railway ni sobre datos de clientes.** Este trabajo no modifica Flask, la política publicada, la base real, credenciales, copias ni el archivo profesional de Rafael.

## Pregunta que resuelve

El titular declara que los documentos fiscales profesionales se envían directamente al despacho de Rafael y que nunca se han almacenado en la web. El código conserva, sin embargo, la tabla `fiscal_advisory_files`, con nombres, rutas y metadatos de adjuntos. Las nuevas subidas están deshabilitadas por defecto, pero **eso no demuestra que la tabla esté vacía ni que no existan archivos huérfanos o copias históricas**.

Antes de diseñar una supresión o traslado de información de esta tabla, es proporcionado determinar **solo la existencia y coherencia de metadatos** sin leer los expedientes.

## Comprobación diseñada

`fiscal_app_export/sec5_priv_advisory_file_probe.py` es un comando manual, nunca importado por el servidor, que:

1. Exige la variable `SEC5_PRIV_ADVISORY_FILE_PROBE=EXPLICIT_READONLY`; no se ejecuta en el arranque ni hay rutas públicas.
2. Usa únicamente el `db.engine` existente de Flask y el control de rol ya auditado `inspect_runtime_role`; rechaza SQLite y los roles SQL privilegiados. No utiliza credenciales administrativas, conexiones alternativas ni consultas a otros proveedores.
3. Abre una transacción `READ ONLY`, comprueba que el servidor la aplica y siempre hace `ROLLBACK`.
4. Ejecuta **una sola consulta agregada** sobre `fiscal_advisory_files`, `fiscal_advisory_requests` y `users` para contar filas, referencias distintas, solicitudes/usuarios inexistentes, solicitudes sin dueño asignado y relaciones donde el `user_id` de la fila no coincide con el de la solicitud.
5. Imprime **solo recuentos y estados**. Nunca selecciona ni imprime `file_name`, `file_path`, emails, NIF, contenidos o IDs de personas, ni consulta el sistema de archivos.

**Salidas:** `NO_METADATA_ROWS` no certifica la ausencia de archivos físicos, backups o adjuntos fuera de la tabla; `REVIEW_REQUIRED` no prueba que los archivos apuntados existan. `INDETERMINATE` rechaza la comprobación sin datos fiables. Ninguna salida autoriza bloqueo, purga, supresión, migración o cambio de custodia.

## Pruebas y garantías

- Pruebas unitarias sintéticas: opt-in, consulta agregada, transacción de solo lectura, rollback, rol no privilegiado, resultados nulos/imposibles, prohibición de exponer nombres y rutas, aislamiento respecto de `app.py` y `startup_schema_gate.py`.
- Extensión **solo CI** del ensayo PG18 `qa_sec5_priv_record_lifecycle_pg18.py` sobre las 17 tablas ORM. Inserta dos filas ficticias de metadatos, una de ellas vinculada a un usuario distinto del de la solicitud; verifica que el rol SQL ordinario ve únicamente los recuentos, detecta la discrepancia y no lee la ruta ni el nombre. No crea archivos físicos.
- La CI completa `backend-tests`, `postgres-bootstrap` y `browser-navigation` del **commit exacto** es imprescindible antes de solicitar integración. Un PASS prueba únicamente lo ensayado, no inventario de producción.

## Decisión posterior, separada

Si en una fase autorizada se ejecutara este preflight sobre el servicio productivo, habría que contrastar el resultado con el custodio, la existencia física de ficheros de manera restringida y las obligaciones de conservación por expediente. No enviar los metadatos identificables, rutas ni documentos a GitHub, correo de soporte o chat. Si hay filas, la actuación correcta es **revisión restringida**, no eliminación automática. No inferir ausencia histórica porque el resultado sea cero.

La decisión sobre **bloqueo legal art. 32 LOPDGDD**, supresión de otras 16 tablas, reconciliación de copias y acceso excepcional **sigue abierta**. Los criterios internos de revisión aprobados el 02/11 no son plazos de eliminación.

**Puerta:** PR en borrador, sin fusionar ni desplegar hasta revisión independiente y autorización expresa. No se ejecuta ninguna comprobación sobre producción en esta entrega.
