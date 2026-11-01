# SEC5-PRIV-011/012/013 · Piloto ejecutable de aislamiento PostgreSQL 18

**Estado: prueba técnica en rama aislada. No es solución de producción ni implementa un derecho de supresión íntegro.**  
**Corte:** 01/11/2026. **Base:** `main@916d97c74df1657fe2f28cf7f2eb85ff0d52535f`.

## Objetivo y alcance mínimo

La desactivación de cuenta existente retira identificadores principales, pero los datos asociados pueden permanecer accesibles en las tablas ordinarias; un campo `blocked=true` no acredita el **bloqueo efectivo** que puede exigir el art. 32 LOPDGDD.

Esta intervención **demuestra técnicamente** en una base PostgreSQL 18 **desechable de CI** que el dato personal puede retirarse de su tabla visible y conservarse temporalmente en una tabla separada cuyos permisos de lectura niegan acceso al rol normal de la aplicación. **No usa las tablas reales, no traslada datos de clientes, no crea roles de producción y no activa purgas.** Su único artefacto ejecutable está en `fiscal_app_export/tests/qa_sec5_priv_blocking_pg18.py` y solo puede arrancar en el servicio de PostgreSQL 18 de GitHub Actions con la variable explícita `SEC5_PRIV_PILOT_ONLY=1`.

## Comportamiento implementado y exigido por CI

1. **Comprobación fail-closed de entorno.** Requiere `GITHUB_ACTIONS=true`, `SEC5_PRIV_PILOT_ONLY=1`, `FLASK_ENV=testing`, localhost, credenciales **sintéticas fijas de CI** y PostgreSQL 18. No acepta una URL de base de datos arbitraria. Nunca se ejecuta desde la app Flask.
2. Crea en el PostgreSQL desechable dos esquemas temporales: `sec5_priv_pilot_app` (tres contactos ficticios) y `sec5_priv_pilot_vault` (evidencias del bloqueo). **No crea tablas en `public` ni muta el esquema ORM productivo.**
3. Crea dos roles `NOLOGIN` distintos: `sec5_priv_pilot_runtime` únicamente puede consultar la tabla ordinaria; `sec5_priv_pilot_exception` puede leer la evidencia de bloqueo pero **no actualizarla**. El esquema restringido no tiene privilegios para `PUBLIC`.
4. **Transacción atómica:** ante el permiso sintético `SYNTHETIC_MANUALLY_REVIEWED`, selecciona `FOR UPDATE`, inserta la identidad/contenido en el esquema restringido y redacta `email/message` de la tabla operativa, marcándola `blocked`. Si se provoca un fallo entre operaciones, se verifica rollback integral.
5. **Reintento idempotente:** un segundo bloqueo para el mismo registro retorna `False` y exige que el dato original esté ausente de la tabla normal y exista exactamente una evidencia bloqueada; una inconsistencia falla.
6. **Pruebas adversariales:** ninguna decisión no sintética se acepta; no se modifican los otros dos contactos de prueba; el rol ordinario **no puede SELECT** en la tabla protegida y el lector excepcional no puede `UPDATE`. Se elimina todo el esquema y roles del piloto al finalizar, incluso ante error.
7. La CI `postgres-bootstrap` ejecuta este comprobador **después** de las suites preexistentes de base de datos. Las otras suites, incluidos backend y navegador, no cambian.

## Qué queda pendiente para un bloqueo legal de producción

- **Normativa/decisión:** determinar por finalidad qué datos concretos se deben suprimir, mantener operativos, bloquear conforme al art. 32 LOPDGDD o comunicar a otro responsable. Los hitos 30/90/180 días siguen siendo revisiones propuestas, **no instrucciones de purga**.
- **Aislamiento real:** la configuración productiva actual no está comprobada para un rol SQL separado sin privilegios de propietario/superusuario. Sin dividir las credenciales y permisos reales, el patrón de laboratorio **no impediría a una app con rol propietario leer todo**. Requiere diseño y autorización específica de migraciones/roles, nunca una mera marca de estado.
- **Integración:** migración reversible y con respaldo validado, aislamiento a nivel de cada una de las **17 tablas y campos con PII**, soporte de correos duplicados y referencias `user_id`, roles de administración, endpoints, campañas, exportaciones, tareas y copias de seguridad. El piloto únicamente usa una tabla ficticia. No es una función legal para ejecución directa.
- **Auditoría excepcional:** registrar causa, legitimación, solicitud, acceso excepcional y período aplicable sin convertir una copia en repositorio permanente. La evidencia no debería ser visible para el rol operativo ni por la API. Una tabla con texto accesible al mismo propietario de BD no basta.
- **Supresión definitiva:** una vez prescrita la obligación, eliminar también evidencias bloqueadas y controlar restauraciones de backups anteriores. Aquí **no hay motor de borrado**, ni se demuestra supresión de proveedores o restauraciones reales.
- **Pruebas necesarias:** transacciones y concurrencia con esquema real sobre PostgreSQL 18 desechable, aislamiento multicliente, rutas Flask y admin, claves S01 Stripe, texto libre, retenciones aprobadas, fallo parcial, reintentos y restauración segura.

## Operativa y autorizaciones

La información de las copias previas (11 y 14/10/2026) y restauraciones de Mac queda en la PR de política #172. **No se ha recuperado ninguna copia real ni se han leído datos personales** para este piloto.

El resultado **PASS de esta CI**, si lo obtiene, solo demostrará aislamiento y reversión transaccional en un laboratorio PostgreSQL 18. No acredita cumplimiento jurídico integral ni autoriza modificar producción.

**Prohibido sin autorización independiente:** fusionar, desplegar, ejecutar scripts en Railway, crear roles o esquemas en producción, mover, bloquear o eliminar registros de clientes, alterar backups o activar automatizaciones de purga. La PR #172 y la política general siguen abiertas.
