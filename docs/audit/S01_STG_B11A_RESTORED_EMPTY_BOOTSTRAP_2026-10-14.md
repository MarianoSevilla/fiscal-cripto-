# STG-B11A — Preparación de inicialización del esquema S01 sobre copia restaurada (CI aislada)

**Fecha:** 14 de octubre de 2026. **PR DRAFT. NO-GO para escrituras reales.** El usuario autorizó continuar la fase preparatoria después de una recuperación real exitosa, sin autorizar explícitamente una segunda operación SQL que inicialice el esquema de la aplicación.

## Situación real confirmada antes de B11A

- GitHub `main` inmóvil en `56882073295faae3bd1bc3632288a970acb330da`. El código de nuevas migraciones pertenece a ramas apiladas aún no fusionadas, NO a la web de producción.
- Proyecto Railway S01 `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, environment `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- Postgres **original** `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`, clúster `7696213098351943739`, deployment `cf076b94-1f68-4d31-b143-3277d40ef188`: **preservar sin escrituras**, como referencia vacía y respaldo de recuperación.
- Postgres **recuperación** `Postgres-Im3h`, ID `317b21e9-b259-4b15-902a-a7bec69b7407`, volumen separado `16144c31-17d5-49e7-a725-967e883e03f9`, clúster `7696517018472497211`, deployment `d88ec988-a600-4398-9421-7843d872f5b9`: posible destino futuro de la **primera inicialización S01**; actualmente vacío según la restauración real B10S.
- Respaldo privado AMS `s01-lab-recovery-20261014-ehk810` `s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom`, SHA256 `1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab`. El backup se restauró realmente en el destino separado mediante `pg_restore --single-transaction`, deployment exitoso `fdb2c898-2ff2-424b-b726-9ac590a9bcf0`, postflight vacío y un solo intento.
- Se revocó la variable `S01_RECOVERY_WRITE_APPROVAL` asignándole un valor inválido (se conserva el nombre); el servicio `s01-lab-restore-one-shot` volvió a `Dockerfile.readonly-archive`, SHA `a76afc14392df42f951d086653e431e3836cb14c`, deployment `8422986e-9d30-4e4c-bf11-3e400082fdcd`, cero réplicas activas. El servicio web S01 no tiene despliegue.
- El servicio **s01-lab-maintenance** (`9728d19b-7d17-4acb-8be1-c4b0847179df`) conserva `DATABASE_URL=${{Postgres.DATABASE_URL}}` al Postgres original, por lo que **NO DEBE USARSE** para inicializar el Postgres-Im3h. Mantiene código readonly B10G. Crear un ejecutor nuevo o reconfigurar uno para la copia recuperada es una fase posterior, con identidad propia; no reutilizar ni suplantar las credenciales/ID del servicio web.
- Railway sin cambios staged; servicios DB y volúmenes separados. Estado de producción no alterado.

## Comprobación de migraciones y bootstrap

- `fiscal_app_export/private_maintenance_rehearsal.py` B10C mantiene `CI_DSN=postgresql://postgres:ci-only-test-password@127.0.0.1:5432/railway`, head Alembic único `z9a0b1c2d3e4`, baseline `m6n7o8p9q0r1`. Su `main()` deniega **siempre** ejecución real.
- La inicialización sintética utiliza exclusivamente `models.db` más una instancia Flask privada sin rutas, **NUNCA importa `app.py`**. La invocación real de `bootstrap_db.py` importa `app.py` y su pin de web no coincide con mantenimiento; prohibido parchear el guard para hacerlo funcionar.
- Flujo sintético: `db.create_all`, `flask_migrate.stamp(m6n7o8p9q0r1)`, `upgrade(head)`, comprobaciones de cabeza Alembic, tablas críticas S01, constraints/indexes y semilla de recurso `experimento-bitcoin`; un segundo intento es rechazado porque la BD ya no está vacía.
- La operación total **NO ES ATÓMICA EN UNA ÚNICA TRANSACCIÓN**; aunque algunas migraciones usen transacciones, la combinación de ORM, stamp y Alembic puede dejar un esquema parcial. En caso de error real: STOP sin auto-`DROP`, sin redeploy/retry, inspección posterior y plan de recuperación separado.

## Qué comprueba B11A (exclusivamente GitHub CI)

1. Dos contenedores PostgreSQL 18 desechables en puertos locales `127.0.0.1:55433` (origen sintético) y `127.0.0.1:5432` (destino sintético); sus system_identifier deben ser distintos entre sí y de **ambos** clústeres reales S01.
2. Ambos catálogos vacíos y sin objetos adicionales. `pg_dump -Fc --no-owner --no-acl` sobre origen sintético y `pg_restore --single-transaction --exit-on-error` sobre destino sintético, manteniendo el esquema vacío.
3. Invocación de la función de ensayo B10C para efectuar el esquema S01 real sobre la copia sintética recién restaurada; Alembic al head fijado y validaciones de constraints/indices/semillas.
4. Repetir el bootstrap sobre el mismo destino: **debe fallar** antes de SQL con `NOT_PRISTINE`.
5. Comprobar de nuevo que el origen sintético continúa vacío y su cluster ID no cambió.
6. Contratos negativos con CI ausente, variables `RAILWAY_*`, `DATABASE_URL`, `TARGET_DATABASE_URL`, `S01_RECOVERY_WRITE_APPROVAL`, puertos no allowlisted y huellas de cluster reales. Nada de secretos Railway, conexión a buckets, escritura a clústeres reales ni acceso al proveedor de pagos.
7. El `main()` de B10C permanece permanente NO-GO, incluso si se intenta activar por variables.

## Salida B11A y próxima autorización

El resultado correcto es **CI PASS y PR DRAFT**, no una base real inicializada. Si la CI queda verde, preparar en fases separadas el ejecutor ADMIN para **Postgres-Im3h**, con service ID y conexión privada propios; comprobar desde ese ejecutor la identidad efectiva del target, ausencia de exposición pública y funciones proveedoras, HEAD esperado, locks y plan de respuesta a parcialidad.

**Autorización específica futura imprescindible:** una única inicialización de esquema SOLO en `Postgres-Im3h` (servicio `317b21e9-b259-4b15-902a-a7bec69b7407`, clúster `7696517018472497211`, volumen `16144c31-17d5-49e7-a725-967e883e03f9`) con un commit inmutable/CI revisados, aceptando que `create_all` y migraciones crean tablas y pueden requerir recuperación manual si fallan. El Postgres original permanece prohibido para escrituras y producción/web/pagos/main quedan fuera de alcance.

**Estado B11A: NO-GO para DDL real y cualquier despliegue de esquema en Railway.**
