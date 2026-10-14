# STG-B11C — Rechazo de esquemas parciales antes de inicializar S01

**Fecha:** 14/10/2026. **Estado:** GitHub CI sintético exclusivamente, sin escrituras sobre Railway. NO implica autorización para desplegar ni para ejecutar migraciones.

## Estado de aislamiento antes de B11C

- PR #83 B11A: 24/24 contratos y ensayo `pg_dump` → `pg_restore` sobre dos PG18 efímeros → creación ORM → Alembic head `z9a0b1c2d3e4`. Ejecución #38612735850 SUCCESS.
- PR #84 B11B: servicio administrativo privado nuevo `s01-lab-schema-preflight` `007db029-c99d-4a68-a965-fd0de3496614`, únicamente `TARGET_DATABASE_URL=${{Postgres-Im3h.DATABASE_URL}}`, sin código desplegado. Código de sonda aprobado en CI 15/15, run #38613598264 SUCCESS. La conexión del repositorio al servicio fue bloqueada por el control de seguridad de la plataforma; **no se reintentó ni se ejecutó por otro mecanismo**.
- Postgres original `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, clúster `7696213098351943739`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af`. Debe permanecer sin escrituras.
- Postgres recuperado `Postgres-Im3h`, `317b21e9-b259-4b15-902a-a7bec69b7407`, clúster `7696517018472497211`, volumen `16144c31-17d5-49e7-a725-967e883e03f9`. Restauración real B10S ya comprobada; **no inicializado todavía**.
- `main` se mantuvo en `56882073295faae3bd1bc3632288a970acb330da`. Sin cambios staged Railway. PRs continúan DRAFT, web lab sin desplegar.
- Servicio antiguo `s01-lab-maintenance` mantiene DSN al Postgres original; prohibido aprovecharlo para ejecutar DDL sobre copia recuperada.

## Prueba adversarial B11C

`fiscal_app_export/tests/qa_s01_b11c_partial_bootstrap_denial_pg18.py` utiliza una base `railway` creada de cero **solo en PostgreSQL 18 disposable de GitHub Actions** en `127.0.0.1:5432`, con credenciales CI y sin variables Railway. Rechaza los system_identifier de los dos clústeres reales.

En cuatro escenarios sucesivos y limpios entre sí, crea un objeto sintético e invoca la función **real de ensayo** `rehearse_once()` del bootstrap B10C:
1. Tabla suelta `public.partial_ci_probe` con dato sintético.
2. Tabla `public.alembic_version` sin una migración válida.
3. Esquema inesperado `unexpected_ci`.
4. Función `public.partial_ci_function`.

En todos debe devolver **`NOT_PRISTINE` antes de ORM, Alembic o DDL**. La prueba compara la lista de tablas y el valor testigo antes y después: los objetos parciales quedan intactos, no aparece `public.users` y no se realizan sellado de migración ni reparaciones automáticas. **Solo el propio script CI borra sus fixtures sintéticos entre escenarios.** No existe código equivalente de borrado/restauración en el laboratorio.

Finalmente mantiene el advisory lock de B10C en una conexión independiente y repite bootstrap sobre BD vacía. Debe denegar con **`ALREADY_RUNNING`** sin crear tablas. Después comprueba la huella sintética y ausencia de `alembic_version`.

Tests offline `test_s01_b11c_partial_bootstrap_scope.py` aseguran CI/localhost, rechazo de clústeres reales, que no se silencien errores distintos a los esperados y que no se puede interpretar una ejecución exitosa como denegación.

## Requisitos restantes y STOP

La seguridad frente a esquemas parciales no reemplaza la prueba de conexión efectiva del servicio B11B —bloqueada por plataforma— ni autoriza inicializar `Postgres-Im3h`. El bootstrap real puede abarcar transacciones separadas; un error a mitad del proceso **podría dejar cambios parciales**. Nunca se realizará automáticamente `DROP`, `stamp`, `upgrade` ni reintentos para reparar.

Para una inicialización real futura deben superarse: bloqueo de conexión B11B resuelto por un mecanismo autorizado, sonda readonly ejecutada desde identidad efectiva `007db029-c99d-4a68-a965-fd0de3496614`, auditoría de código final y SHA congelado, revisión de credenciales, bloqueo antirreintentos, plan de respuesta si DDL termina parcialmente y **aprobación expresa independiente** para la primera escritura de esquema únicamente al volumen recuperado.

**B11C NO-GO:** no despliegue Railway, no migraciones reales, no PR merges, no cambios `main`, no web, pagos ni correo.
