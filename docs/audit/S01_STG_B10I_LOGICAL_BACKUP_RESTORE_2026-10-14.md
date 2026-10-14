# STG-B10I — Ensayo de backup/restauración lógica PostgreSQL18 (CI exclusivamente)

## Objetivo
Validar `pg_dump --format=custom` + checksum SHA256 + `pg_restore --exit-on-error` en **dos contenedores PostgreSQL18 independientes y desechables** de GitHub Actions. Nunca enviar datos del lab, staging ni producción a CI.

## Aislamiento estricto
- Fuente sintética `127.0.0.1:5432` y restauración sintética `127.0.0.1:55433`, PostgreSQL18, contraseña fija CI sin secreto real.
- `require_synthetic_ci()` deniega `RAILWAY_*`, `DATABASE_URL` y entornos ajenos a GitHub CI Linux. No se leen variables ni servicios Railway.
- Dos clústeres con identificadores `pg_control_system().system_identifier` distintos y ninguno igual a `7696213098351943739` (huella real del laboratorio).
- La base origen se crea y puebla mediante el bootstrap sintético ya validado B10C. La base destino se crea vacía de forma independiente.
- `pg_dump` y `pg_restore` se ejecutan usando clientes PostgreSQL18 en contenedores efímeros. El archivo se guarda solo en el directorio temporal del runner; no se publica como artifact.
- Comprobar integridad SHA256 antes de restaurar, exigir `pg_restore --exit-on-error` y verificar después head Alembic `z9a0b1c2d3e4`, tablas S01, constraints, indexes, seed, todos los recuentos por tabla y definiciones de esquema.
- No se ejecuta `DROP DATABASE` o `DROP SCHEMA`, no se conecta a internet para alcanzar bases reales y no se modifican los servicios del laboratorio.

## Límites de interpretación
Aunque sea PASS, este ensayo **no demuestra** que exista un backup íntegro de la base real de Railway ni una restauración real de su volumen. Esa puerta requiere obtener un respaldo del laboratorio en procedimiento autorizado y restaurarlo **en una base distinta**, sin sobrescribir el origen, con evidencias del backup real, checksum, fecha, PG18 y validación de esquema vacío/correcto.

## Estado de otros gates
La huella real del clúster S01 `7696213098351943739` fue confirmada por ambos orígenes en el despliegue privado de solo lectura `86336018-9964-471b-92c7-e4b40db8e4e1`. Las migraciones del laboratorio, el despliegue web, las fusiones de PRs y las operaciones financieras siguen NO-GO. Se necesita autorización específica futura para cualquier escritura o restauración con datos reales.


## Resultado de CI y revisión del desfase

- Workflow GitHub Actions **#38543045211**: **SUCCESS**; SHA del código probado `0e7e86efb12b0c67fcbe204c5365938d76ec8d23`.
- Evidencia: `S01 B10I SETUP PASS`; `s01-ci-synthetic-only.dump: OK` (SHA256); `S01 B10I RESTORE PASS: two independent PostgreSQL18 clusters; Alembic head, all table counts, indexes, constraints and seeded synthetic resources match; no Railway writes`.
- Primeros intentos #38542141912, #38542362270 y #38542584671 terminaron en **FAIL** durante verificación final, aunque `pg_dump` y `pg_restore` finalizaron sin error. La discrepancia se limitó a definiciones `CHECK` de tres constraints: `ck_s01_checkout_status`, `ck_s01_outbox_kind`, `ck_s01_outbox_status`.
- PG18 normalizó `(ARRAY['x'::character varying, ...])::text[]` como `ARRAY[('x'::character varying)::text, ...]` tras restore. Los dos formatos representan la misma lista literal; **la prueba normaliza solo dos renderizados exactos para los tres nombres y los valores enumerados esperados**. Si se altera un valor, la expresión o aparece cualquier otra variante, se lanza error y la CI vuelve a fallar.
- Permanecen comprobaciones estrictas de todos los demás nombres/definiciones de restricciones, tablas, índices, recuentos, seed, PG18, Alembic y huellas de clúster distintas.
- El resultado positivo no permite concluir que exista un backup real de S01 RESTAURABLE. Gate pendiente: respaldo del lab, checksum y restauración **en destino independiente**, sin sustituir el volumen `c35d178f-7473-4d0b-adb9-1faae815b7af` ni tocar la web/producción.
- Ningún servicio Railway fue modificado en esta fase B10I. No autorizado DDL real ni merge de PR.
