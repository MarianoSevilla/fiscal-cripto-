# STG-B10D — Validación adversarial PostgreSQL18 efímero · 14/10/2026

**SOLO código/CI en PR DRAFT apilada sobre #66** (base SHA `350dc49a677219380a345f93387d6908446476e5`). No se modifica Railway, ninguna base de datos real, ni `main`.

## Riesgos puestos a prueba

Se utilizan **dos contenedores PostgreSQL 18 independientes y desechables** en GitHub Actions. Ambos crean solo la BD sintética `railway` en `127.0.0.1:5432` con credenciales fijas CI, después de validar `GITHUB_ACTIONS`, `CI`, `RUNNER_OS`, ausencia de variables Railway y ausencia de `DATABASE_URL`. Ninguna rama de ejecución usa el Postgres del laboratorio.

- **fault:** mantener advisory lock en otra conexión: el competidor debe abortar con `ALREADY_RUNNING`, dejando cero objetos. Después simular excepción *tras* `db.create_all` y `stamp` pero *antes* de `upgrade`: el siguiente intento debe abortar `NOT_PRISTINE`. Finalmente, `startup_schema_gate.py` debe rechazar el esquema parcial en transacción de solo lectura.
- **healthy:** inicialización limpia, Alembic hasta `z9a0b1c2d3e4`, restricciones financieras S01 y seed verificados por B10C; segundo intento `NOT_PRISTINE`; `startup_schema_gate.py` debe aprobar el esquema completo.

No se limpia ni repara automáticamente el esquema contaminado: cada escenario dispone de un contenedor efímero completamente separado. Los tests de GitHub no son evidencia de la identidad/valores efectivos de Railway.

## Límites / elementos que NO se han resuelto

1. Lock consultivo solo impide colisión entre procesos que respeten el protocolo; no bloquea escritores externos.
2. Una secuencia de DDL + Alembic puede no ser atómica globalmente; ante interrupción debe prohibirse reintento y restaurarse solo tras autorización.
3. La suite no prueba la seguridad operativa de una futura fuente ejecutable de Railway ni que el Postgres de `DATABASE_URL` pertenezca al lab. Eso necesita verificación independiente de referencia de servicio, identidades de Railway, DNS y red.
4. Falta un mecanismo revisado de autorización **de un solo uso**, code pin, protección de logs, backup/restauración efectiva y revocación posterior.
5. No se ha auditado exhaustivamente todas las migraciones históricas; éxito de la suite no sustituye revisión ni validación de aplicación real.

**NO-GO:** no conectar ni ejecutar código en `s01-lab-maintenance`, no inicializar PostgreSQL Railway, no desplegar web, no fusionar PR ni modificar staging/producción.
