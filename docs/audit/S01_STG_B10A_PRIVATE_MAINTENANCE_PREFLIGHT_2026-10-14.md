# STG-B10A — Ejecutor privado: preflight de solo lectura (NO-GO DDL)

**Fecha:** 14/10/2026. **Alcance autorizado:** exclusivamente código, pruebas sintéticas y PR DRAFT. No Railway, migraciones, despliegues ni merges.

## Base de seguridad congelada

- PR base: **#63** `security/s01-stg-b06-pin-private-web`, SHA `9f8060ce2e096165b33dbae25276c91d52f4ed15`; cadena apilada #61 → #62 → #63.
- `main` SHA observado: `56882073295faae3bd1bc3632288a970acb330da`. No cambiarlo.
- Lab Railway de solo lectura: proyecto `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e`, entorno `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`, PostgreSQL independiente `f680f3fc-4581-44ff-8bc1-d034840f2c7e`. Web vacío `212f4f52-b349-4387-a046-9f6b08237d2e` sin source/deploy. Sin cambios pendientes en el entorno.
- Verificación manual STG-B09 proporcionada por el propietario: `railway`, versión `180006`, cero tablas, vistas, secuencias e índices en `public`. Es un **snapshot**, no elimina el preflight futuro.

## Diseño codificado

- Módulo `private_maintenance_preflight.py`: no importa Flask/app/Alembic ni inicializa modelos. No puede modificar esquemas ni ejecutar `bootstrap_db.py`.
- **Identidad administrativa SIN PIN:** `service_id=None`. Es condición obligatoria fail-closed en el `main()`, antes de cargar psycopg2 o abrir red. Los IDs de proyecto y entorno están fijados a S01 lab. DNS del servicio propuesto `s01-lab-maintenance.railway.internal` es **solo candidato**, no un dominio efectivamente observado; la fase B10B debe verificarlo.
- `RAILWAY_*_ID`, nombre de entorno, dominio privado, `FLASK_ENV=staging`, DSN de PostgreSQL privado y `/railway` se validan como conjunto. Variables públicas, `APP_BASE_URL`, `PORT`, credenciales externas y features no autorizadas son rechazadas. No hay bypass por `S01_LAB_MODE` ni por `S01_SYNTHETIC_LAB_MODE`.
- En futura ejecución autorizada, se requerirá inventario operacional independiente (dominios/proxies, Auto Deploy, referencia `Postgres.DATABASE_URL` propia del proyecto). El DNS `postgres.railway.internal` por sí solo **NO prueba** aislamiento físico.
- Futuro preflight: conexión SSL `require`, timeout 5s, `default_transaction_read_only=on`, `SET TRANSACTION READ ONLY`, solo `SELECT` de catálogos, verificar base `railway`, PostgreSQL 18, esquema `public` presente y vacío (relaciones, funciones, tipos), sin esquemas de usuario adicionales, extensiones extra ni event triggers. `rollback` siempre y `close` siempre. No imprimir secretos/DSN o trazas DBAPI.
- Pruebas unitarias con conectores falsos y valores sintéticos; sin conexión a Railway ni PostgreSQL real. Workflow nuevo `pull_request` limitado al stack B06, solo `contents: read`, sin secretos ni dependencias, sin servicio de base de datos.

## Separación expresa de fases

- **B10A:** entrega solo el preflight sin ninguna vía de escritura. El runner productivo queda cerrado hasta un servicio con ID real.
- **B10B:** requiere autorización independiente para crear un servicio administrativo vacío, observar el ID y dominio privado reales, asegurar red/variables/referencia DB sin exposición pública, reinicios ni cron, y fijar ese ID en revisión de código. Mantener DDL deshabilitado.
- **B10C:** otra autorización y revisión de código para conectar un ejecutor de inicialización única con `bootstrap_db.py`. El `app.py` actual exige el ID del servicio web al importar; **no se permite eludirlo** con flags arbitrarios. Se necesita definir una ruta administrativa de importación controlada y verificada sin abrir rutas web ni proveedores. Ejecutar sobre base vacía con exclusión mutua, plan de recuperación y verificación `z9a0b1c2d3e4`. No está implementado por B10A.
- **B11:** evaluar despliegue web privado y comprobación `startup_schema_gate.py` solo después de completar migraciones autorizadas.

**STOP/NO-GO:** no crear/editar Railway, no conectar servicios ni GitHub a Railway, no `alembic upgrade`, no `db.create_all`, no `bootstrap_db.py`, no ejecutar SQL de escritura ni correos/pagos reales, no tocar staging/producción y no fusionar ninguna PR.
