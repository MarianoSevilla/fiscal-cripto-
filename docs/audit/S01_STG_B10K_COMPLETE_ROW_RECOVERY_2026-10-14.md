# S01 STG-B10K — Integridad completa del contenido restaurado · 14/10/2026

## Brecha detectada en la auditoría de B10I
La CI STG-B10I verificaba PG18, head Alembic, lista de tablas, contadores de filas por tabla, índices, constraints y la pareja `slug, title` de los recursos sembrados. **No verificaba todos los campos de todas las filas**: una alteración de contenido podía mantener idénticos esos controles.

## Refuerzo solo sintético
- En `qa_stg_b10i_pg18_backup_restore.py` se añade `SHA256` del contenido de **cada fila de todas las tablas**, recorriendo `to_jsonb(row)::text` con un orden estable y delimitación de longitud por registro. Se almacena solo la huella de cada tabla, nunca el texto de filas en el informe.
- El ensayo sigue confinado a `127.0.0.1:5432` y `127.0.0.1:55433`, dos clústeres PostgreSQL 18 independientes de CI, con `GITHUB_ACTIONS=true`, `CI=true`, ausencia de `RAILWAY_*` y `DATABASE_URL`, y huellas distintas de `7696213098351943739`.
- La restauración positiva exige igualdad de todos los digest SHA256 por tabla además de los controles existentes.
- Un paso **negativo** adicional modifica solamente `resources.description` en el destino efímero, mantiene las mismas tablas y número de filas y deja idéntica la pareja semilla `slug/title`; la huella de contenido debe variar y detectarlo.
- La verificación negativa no se considera un fallo CI: el propio test exige el rechazo para superar su control.
- No se modifica Railway, PostgreSQL del laboratorio, web, DDL, pagos ni código servido al público. La prueba de recuperación se sigue refiriendo únicamente a datos CI.

## Límites
El SHA256 detecta discrepancias en el contenido transformado a JSONB; ello no sustituye la auditoría de todos los objetos PostgreSQL, privilegios, parámetros de servidor, ni pruebas de copia/restauración del volumen original. La huella usa representación PG18 y debe validarse de nuevo ante un cambio de major, collation, tipos o comportamiento de serialización.

La preparación de backup REAL S01 y restauración en otro servicio/volumen continúa **NO-GO** sin permisos separados, datos de procedencia, checksum, huella de destino y resultado verificado.

**Pre-requisito de esta PR:** PR #73 STG-B10J. Todas las PR continúan en DRAFT, sin merge.
