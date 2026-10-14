# STG-B10M — Prevalidación de restauración de un PostgreSQL18 realmente vacío

**Fecha 14/10/2026. Solo GitHub Actions, sin conexiones a Railway.** Apilada sobre PR #75 (B10L), todavía DRAFT. La restauración de una base de laboratorio real en un nuevo clúster está pendiente de autorización de destino y del ejecutor de recuperación.

## Copia REAL disponible

- Fuente: proyecto S01 `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`, servicio PostgreSQL `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`.
- Clúster: `7696213098351943739`. Verificación previa y posterior de catálogo vacío; backup de solo lectura.
- Bucket privado AMS: `s01-lab-recovery-20261014` (ID `3e5112d5-39bf-43fa-8602-155e61b06e73`); objeto interno **`s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom`**.
- SHA256 verificado al descargar de nuevo desde el bucket: **`1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`**.
- Deployment que obtuvo éxito: `a4dffe40-a1ae-4534-a788-989a457733c2`, lector limitado `s01-lab-backup-reader`, SHA del ejecutor `1aff998a1cd446ad591492800c534912d4d70a9b`.
- Fuente original continúa operativa con su volumen, sin migraciones; web lab sigue inactiva. `main` no cambió.

## Qué añade B10M

B10I/B10K probaron copias/restauraciones con modelo y tablas S01 sintéticos; B10M prueba el **caso real de estructura inicial vacía** usando dos PostgreSQL18 desechables y un dump original de la base vacía generado por `pg_dump -Fc` dentro de CI. Comprueba:

1. Dos clústeres diferentes entre sí y diferentes de `7696213098351943739`.
2. Bases `railway` vacías de origen/destino y versión PostgreSQL18.
3. `pg_dump --no-owner --no-acl` del esquema vacío, SHA256 local y `pg_restore --exit-on-error` sobre clúster diferente.
4. Conservación en destino de cero relaciones, funciones y tipos en `public`, cero extensiones extra y cero event triggers.
5. Sin alteración de Railway, descarga del objeto real ni traslado de credenciales a GitHub. Ningún artefacto público con datos reales.

## Puerta futura de RESTAURACIÓN REAL (NO-GO actualmente)

Para demostrar que **el archivo real respaldado** es restaurable, no basta con el hash o B10M: se requiere autorización explícita para (i) crear nuevo servicio y nuevo volumen PostgreSQL18 en entorno controlado, (ii) verificar sus IDs y nueva huella de clúster independientes, y (iii) ejecutar un **único** restaurador con destino estrictamente fijado a ese servicio y fuente S3 fijada a bucket/clave y SHA exactos. El restaurador no debe conectarse como escritor a la fuente, no debe tener source DATABASE_URL, no debe incluir Flask/proveedores ni endpoints públicos, y debe rechazar una BD destino no vacía o con huella original.

No utilizar el botón Restore de Railway sobre el volumen original; no copiar credenciales, backups, registros de clientes o DSN a GitHub/CI. No ejecutar `alembic upgrade`, `bootstrap_db.py` o inicio web en esta fase.

## Estado operativo
**Backup REAL creado y verificado SHA256. Restauración REAL aún PENDIENTE.** B10M es un gate de ensayo sintético adicional para justificar la creación futura de infraestructura aislada; no autoriza por sí solo DDL real.
