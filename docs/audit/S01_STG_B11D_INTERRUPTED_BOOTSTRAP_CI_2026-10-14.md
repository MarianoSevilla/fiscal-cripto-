# S01 — STG-B11D · Interrupciones reales de bootstrap en PostgreSQL18 sintético

**Fecha:** 14 de octubre de 2026. **Estado:** PR DRAFT / CI sintética exclusivamente. **NO-GO para ejecutar inicialización real ni desplegar servicios Railway.**

## Punto de partida

- B11A (PR #83, CI #38612735850): restauración de una base vacía sintética sobre PG18 distinto y bootstrap completo con Alembic head `z9a0b1c2d3e4`.
- B11B (PR #84, CI #38613598264): sonda de solo lectura 15/15 PASS, nuevo servicio `s01-lab-schema-preflight`, ID `007db029-c99d-4a68-a965-fd0de3496614`, en lab; `TARGET_DATABASE_URL` apunta solo a `Postgres-Im3h`. **La conexión del repositorio a este servicio fue bloqueada por un control de seguridad. No se reintentó ni se sorteó el bloqueo. El servicio no tiene deployment.**
- B11C (PR #85, CI #38615226530): 19/19 controles y 5 ensayos en PG18 disposable: tabla/registro parcial, `alembic_version` provisional, esquema adicional, función adicional, lock concurrente → rechazo antes de crear nuevas tablas.
- El clúster original `7696213098351943739` en Postgres `f680f3fc-4581-44ff-8bc1-d034840f2c7e` está reservado, sin escrituras. El clúster recuperado `7696517018472497211` en `Postgres-Im3h` `317b21e9-b259-4b15-902a-a7bec69b7407` permanece sin inicialización S01 real. Volúmenes separados; `main` inmutable `56882073295faae3bd1bc3632288a970acb330da`.

## Prueba adversarial adicional B11D

La diferencia frente a B11C: **inyectar el fallo después de que el inicializador realmente haya comenzado a escribir**. Así se verifica la política de seguridad del segundo intento cuando Alembic y SQLAlchemy han dejado un estado incompleto.

`fiscal_app_export/tests/qa_s01_b11d_interrupted_bootstrap_pg18.py` usa exclusivamente:
- contenedor GitHub Actions `postgres:18` desechable, `127.0.0.1:5432/railway`, contraseña CI fija no real;
- `GITHUB_ACTIONS=true`, `CI=true`, `RUNNER_OS=Linux`, rechazo de `RAILWAY_*`, variables de DSN externa y huellas de ambos clústeres S01 reales;
- **sin** `DROP DATABASE` ni comandos que limpien la BD, sin Flask `app.py`, sin servidor, pagos, bucket ni secretos Railway;
- la función `private_maintenance_rehearsal.rehearse_once()` original, no una réplica del bootstrap, con un parche de interrupción localizado por fase.

La CI ejecuta una **matriz de cuatro trabajos independientes**, cada uno con una BD PG18 recién creada:

1. `after-models`: `db.create_all` ha creado físicamente las tablas, se interrumpe antes de `stamp`.
2. `after-stamp`: `db.create_all` y `flask_migrate.stamp` han persistido la revisión inicial; interrupción antes del primer `upgrade`.
3. `mid-upgrade`: ejecuta migraciones Alembic reales hasta el antecesor inmediato de `z9a0b1c2d3e4` y simula interrupción antes de aplicar la última revisión.
4. `after-upgrade`: completa Alembic hasta `z9a0b1c2d3e4`, pero simula un fallo antes de la validación posterior.

Cada prueba exige que el proceso real se interrumpa, que exista un catálogo ya modificado, que la sesión de advisory lock quede liberada, que un segundo `rehearse_once()` falle con `NOT_PRISTINE` y que el catálogo, constraints, versión Alembic y recuentos sintéticos no cambien durante el intento rechazado. Nunca borra ni repara objetos. La huella del clúster CI debe permanecer intacta. Los tests offline rechazan entornos que no sean CI y casos de ejecución no enumerados.

## Interpretación de los resultados

- **PASS** demostrará la denegación del reintento sobre un estado realmente parcial, pero **no** que toda la inicialización de S01 sea atómica. `db.create_all`, `stamp` y `upgrade` pueden persistir operaciones en transacciones distintas.
- La corrección de un fallo real requerirá inspección independiente del estado, una estrategia de restauración/manipulación aprobada y una autorización nueva. No ejecutar `DROP`, `stamp` ni `upgrade` automáticos como reparación.
- Este ensayo no verifica la identidad efectiva desde `s01-lab-schema-preflight`; la conexión B11B sigue bloqueada, sin ejecutar. No volver a intentar ni eludir el rechazo mediante el servicio antiguo de mantenimiento (que apunta al origen).

## Restricciones

**NO-GO** para DDL real en `Postgres-Im3h` o Postgres original, conexión o despliegue del servicio nuevo bloqueado, fusionar PRs, `main`, web, migraciones en producción, Stripe/PayPal o correo.

**Próximo gate:** resolver formalmente el bloqueo de B11B y acreditar la huella del destino desde la identidad efectiva de un administrador autorizado; luego revisar un ejecutor específico y solicitar una **aprobación expresa e independiente** antes de la primera DDL real.
