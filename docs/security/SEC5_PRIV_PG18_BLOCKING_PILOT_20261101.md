# SEC5-PRIV-011/012/013 · Piloto ejecutable de aislamiento PostgreSQL 18

**Estado: prueba técnica en rama aislada. No es solución de producción ni implementa un derecho de supresión íntegro.**  
**Origen:** 01/11/2026 sobre `main@916d97c7`. **Revisión:** 02/11/2026, tras la integración de la política documental en `main@34bc21f3`.

## Objetivo y alcance mínimo

La desactivación de cuenta existente retira identificadores principales, pero los datos asociados pueden permanecer accesibles en las tablas ordinarias; un campo `blocked=true` no acredita el **bloqueo efectivo** que puede exigir el art. 32 LOPDGDD.

Esta intervención **demuestra técnicamente** en una base PostgreSQL 18 **desechable de CI** que el dato personal puede retirarse de su tabla visible y conservarse temporalmente en una tabla separada cuyos permisos de lectura niegan acceso al rol normal de la aplicación. **No usa las tablas reales, no traslada datos de clientes, no crea roles de producción y no activa purgas.** Su único artefacto ejecutable está en `fiscal_app_export/tests/qa_sec5_priv_blocking_pg18.py` y solo puede arrancar en el servicio de PostgreSQL 18 de GitHub Actions con la variable explícita `SEC5_PRIV_PILOT_ONLY=1`.

## Comportamiento implementado y exigido por CI

1. **Comprobación fail-closed de entorno.** Requiere `GITHUB_ACTIONS=true`, `SEC5_PRIV_PILOT_ONLY=1`, `FLASK_ENV=testing`, localhost, credenciales **sintéticas fijas de CI** y PostgreSQL 18. No acepta una URL de base de datos arbitraria. Nunca se ejecuta desde la app Flask.
2. Crea en el PostgreSQL desechable dos esquemas temporales: `sec5_priv_pilot_app` (tres contactos ficticios) y `sec5_priv_pilot_vault` (evidencias del bloqueo). **No crea tablas en `public` ni muta el esquema ORM productivo.**
3. Crea dos roles `NOLOGIN` distintos: `sec5_priv_pilot_runtime` únicamente puede consultar la tabla ordinaria; `sec5_priv_pilot_exception` puede leer la evidencia de bloqueo pero **no actualizarla**. El esquema restringido no tiene privilegios para `PUBLIC`. También crea dos roles `LOGIN NOINHERIT` efímeros, con contraseñas sintéticas distintas, **sin membresías y con `USAGE/SELECT` concedidos directamente a cada login**. Los roles `NOLOGIN` se usan por separado para el ensayo `SET LOCAL ROLE` desde la sesión administrativa de CI; **ningún LOGIN puede asumirlos**, ni asumir el rol excepcional/opuesto o `postgres`. Las sesiones autenticadas verifican explícitamente `rolsuper=false`, `rolbypassrls=false`, `rolinherit=false`, `rolreplication=false` y ausencia de membresías. Esta variante se aproxima mejor al rol ordinario desplegado, sin suponer que exista un almacén legal en producción.
4. **Transacción atómica:** ante el permiso sintético `SYNTHETIC_MANUALLY_REVIEWED`, selecciona `FOR UPDATE`, inserta la identidad/contenido en el esquema restringido y redacta `email/message` de la tabla operativa, marcándola `blocked`. Si se provoca un fallo entre operaciones, se verifica rollback integral.
5. **Reintento idempotente:** un segundo bloqueo para el mismo registro retorna `False` y exige que el dato original esté ausente de la tabla normal y exista exactamente una evidencia bloqueada; una inconsistencia falla.
6. **Pruebas adversariales:** ninguna decisión no sintética se acepta; no se modifican los otros dos contactos de prueba; el rol ordinario **no puede SELECT** en la tabla protegida y el lector excepcional no puede `UPDATE`. Se elimina todo el esquema y roles del piloto al finalizar, incluso ante error. Se verifica además que el `LOGIN` operativo no puede leer el almacén, el `LOGIN` excepcional no puede escribirlo ni leer datos ordinarios, y ninguno puede asumir el papel del otro ni elevarse a `postgres`.
7. La CI `postgres-bootstrap` ejecuta este comprobador **después** de las suites preexistentes de base de datos. Las otras suites, incluidos backend y navegador, no cambian.

## Qué queda pendiente para un bloqueo legal de producción

- **Normativa/decisión:** la política interna de puntos de revisión por finalidad fue **aprobada e integrada en PR #172** el 02/11/2026. Los hitos 24 meses y 30/90/180 días **no son instrucciones de purga** y 24 meses de inactividad **nunca desactivan ni cierran la cuenta**. Sigue pendiente decidir por caso cuándo corresponde conservar operativo, suprimir o bloquear conforme al art. 32 LOPDGDD, con excepciones y plazos legales verificables.
- **Aislamiento real:** el 02/11/2026 **sí se comprobó** en producción que `db.engine` de Flask utiliza `sec5_runtime_prod` sin `SUPERUSER`, `BYPASSRLS`, `CREATE`, `INHERIT` ni membresías, con DML limitado a 17 tablas ORM y Alembic en lectura. **Eso mitiga el acceso superusuario, pero no acredita bloqueo legal alguno:** todavía no existe un almacén reservado real, credencial de acceso legal excepcional, procedimiento de traslado de datos por finalidad ni control de accesos de expedientes bloqueados. Su implementación requerirá diseño, pruebas y autorización específicos.
- **Integración:** migración reversible y con respaldo validado, aislamiento a nivel de cada una de las **17 tablas y campos con PII**, soporte de correos duplicados y referencias `user_id`, roles de administración, endpoints, campañas, exportaciones, tareas y copias de seguridad. El piloto únicamente usa una tabla ficticia. No es una función legal para ejecución directa.
- **Auditoría excepcional:** registrar causa, legitimación, solicitud, acceso excepcional y período aplicable sin convertir una copia en repositorio permanente. La evidencia no debería ser visible para el rol operativo ni por la API. Una tabla con texto accesible al mismo propietario de BD no basta.
- **Supresión definitiva:** una vez prescrita la obligación, eliminar también evidencias bloqueadas y controlar restauraciones de backups anteriores. Aquí **no hay motor de borrado**, ni se demuestra supresión de proveedores o restauraciones reales.
- **Pruebas necesarias:** transacciones y concurrencia con esquema real sobre PostgreSQL 18 desechable, aislamiento multicliente, rutas Flask y admin, claves S01 Stripe, texto libre, retenciones aprobadas, fallo parcial, reintentos y restauración segura.

## Operativa y autorizaciones

Las copias cifradas manuales históricas de octubre y una copia posterior de noviembre con restauración estructural PG18 comunicada por el titular se documentan en la PR #172. No se han leído ni trasladado respaldos al laboratorio de este piloto. **No se ha recuperado ninguna copia real ni se han leído datos personales** para este piloto.

El resultado **PASS de esta CI**, si lo obtiene, solo demostrará aislamiento y reversión transaccional en un laboratorio PostgreSQL 18. No acredita cumplimiento jurídico integral ni autoriza modificar producción.

**Prohibido sin autorización independiente:** fusionar, desplegar, ejecutar scripts en Railway, crear roles o esquemas de bloqueo en producción, mover, bloquear o eliminar registros de clientes, alterar backups o activar automatizaciones de purga. **La PR #172 ya está integrada** (criterios internos únicamente); el expediente global de privacidad sigue abierto.
