# SEC5-PRIV — Ensayo PostgreSQL 18 de reserva y supresión de registros

**Fecha:** 02/11/2026. **Estado:** ensayo ejecutable de CI con datos ficticios. **No es procedimiento productivo y no constituye bloqueo legal conforme al art. 32 LOPDGDD.**

## Alcance verificable

- La CI `postgres-bootstrap` crea una base PostgreSQL 18 desechable `sec5_priv_lifecycle_ci`, genera mediante SQLAlchemy las **17 tablas** de modelos reales y añade un esquema reservado exclusivamente para el ensayo.
- Solo se actúa sobre **dos registros sintéticos de `processing_errors`** inequívocamente vinculados al mismo `users.id`; no implementa supresión de cuentas, informes FIFO, expedientes ni cascadas.
- Una operación ficticia `BLOQUEAR_ART32` coloca **la fila completa** en una tabla `ledger` de esquema reservado y borra la original de la tabla ordinaria dentro de la misma transacción. El nombre de la decisión es una etiqueta **sintética**, no una calificación jurídica efectiva.
- Otra operación ficticia `SUPRIMIR` elimina una fila ordinaria y escribe una marca mínima de recuperación, sin su contenido. La marca conserva un `user_id` enlazable: **no es anonimización**, ni establece una obligación de conservarlo en producción. No implica supresión integral del titular.
- La misma función no se importa por Flask ni expone API, ruta, tarea, CLI operativa o migración de producción. El entorno exige GitHub Actions, `CI=true`, `FLASK_ENV=testing`, `SEC5_PRIV_LIFECYCLE_PG18_ONLY=1`, localhost PostgreSQL 18 y ausencia de `DATABASE_URL`, variables Railway y claves de proveedores.
- Las credenciales de ensayo son ficticias. El rol ordinario recibe las concesiones del contrato ACL existente sobre las 17 ORM. El rol excepcional tiene solo `SELECT` sobre la tabla reservada, sin membresías ni acceso al esquema ordinario. Los esquemas y logins de ensayo se eliminan al finalizar.

## Comprobaciones adversariales

1. Rechaza autorización inexistente, etiqueta de autorización no sintética y decisiones no previstas.
2. Rechaza registro de otro usuario con el mismo email copiado, registro sin FK de usuario, cuenta desactivada y titular con expediente de asesoramiento y evidencia sintética de Stripe.
3. Inyecta excepciones tanto antes como **después del DELETE**, todavía dentro de la transacción: ambos casos deben revertir íntegramente reserva y borrado.
4. Prueba dos solicitudes **concurrentes** de supresión para un mismo registro, con bloqueo de fila y resultado exactamente una operación nueva y otra idempotente; también rechaza la repetición incompatible de una decisión.
5. Verifica mediante consultas ORM que los dos registros salieron de `processing_errors`, mientras los registros ajenos y el recibo sintético S01 permanecen intactos.
6. Comprueba que un login normal no puede leer el esquema reservado; que el login excepcional no puede consultar `processing_errors` ni actualizar la reserva, y que ninguno puede asumir `postgres`.
7. Exige que el fichero de prueba siga fuera del árbol de importación de Flask y que su ejecución desde CI esté protegida por un indicador explícito.

## Límites y NO-GO

Este es un **ensayo por tipo de registro**, no una solución del ciclo de vida de los datos personales:
- No inspecciona libremente texto de otras tablas, correos históricos externos, expedientes de Rafael Ramos ni proveedores Gmail/Resend/Stripe. El ensayo solo representa **una** dependencia financiera; no efectúa llamadas externas ni transacciones reales.
- No garantiza que el tratamiento posterior sea jurídicamente válido, que exista motivo o plazo de bloqueo aplicable, ni prueba accesos HTTP/admin, exportaciones o tareas programadas sobre las 17 tablas. No se autoriza generalizar las dos operaciones a otros modelos.
- El campo `payload` JSONB es solo evidencia de laboratorio y no introduce en producción cifrado, roles de custodia, firma, historial de auditoría ni destrucción a prescripción.
- Las **copias de seguridad** y la conciliación de supresiones previas a una restauración siguen pendientes. Una marca sintética en la misma base no sobreviviría necesariamente a una restauración anterior.
- No hay cambios productivos, no se crean servicios o usuarios de Railway y la PR debe mantenerse **sin desplegar** hasta revisión y autorización de cualquier implementación real.

**Criterio de cierre de este subtrabajo:** CI PostgreSQL 18 y pruebas estáticas PASS para el commit exacto, seguida de auditoría de límites. El estado de SEC5-PRIV global continuará abierto después.
