# SEC5-PRIV — usuario SQL limitado para Flask: validación aislada

**Estado 01/11/2026:** propuesta de implementación + prueba real sobre un PostgreSQL 18 desechable de GitHub Actions. **No ejecutada en Railway staging o production. No hay credenciales ni datos reales en estos artefactos.**

## Diagnóstico acreditado

El propietario ejecutó desde el Mac una consulta read-only por SSH **dentro del servicio web de producción, usando \`db.engine\` de Flask**. La salida de atributos (no credenciales ni datos) confirmó:

- \`same_session_role=True\`
- \`rolsuper=True\`, \`rolbypassrls=True\`, \`rolcreaterole=True\`, \`rolcreatedb=True\`
- \`database_owner_member=True\` y \`public_schema_owner_member=True\`

Por tanto, la conexión Flask **es superusuario actualmente**. Esto incrementa el impacto de una eventual ejecución de SQL en la aplicación y no permite utilizar las ACL de un almacén bloqueado como barrera real frente al proceso web. **No evidencia explotación ni acceso no autorizado.**

## Objetivo técnico mínimo

Crear, **solo tras autorización y ensayo controlado**, una identidad SQL independiente para el tráfico web, con login sin privilegios de administración/propiedad:

- \`LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT\` y credencial exclusiva generada fuera del repositorio.
- \`CONNECT\` en la base concreta y \`USAGE\` sobre el esquema \`public\`.
- \`SELECT, INSERT, UPDATE, DELETE\` únicamente en **las 17 tablas ORM existentes**. Estas autorizaciones amplias son todavía **por tabla, no por finalidad ni por usuario HTTP**; la capa Flask debe conservar sus propias barreras. No conceder \`TRUNCATE\`, \`MAINTAIN\`, \`REFERENCES\`, \`TRIGGER\`, \`CREATE\`, \`ALTER\`, \`DROP\` ni privilegios de propietario.
- \`USAGE, SELECT\` solo en secuencias **propiedad de las tablas ORM**, necesarias para claves automáticas. La concesión sobre tablas no incluye secuencias en PostgreSQL.
- \`SELECT\` exclusivo en \`alembic_version\` para permitir la puerta de arranque read-only. No \`INSERT/UPDATE/DELETE\` sobre la versión de esquema.
- **Sin** \`GRANT ... ON ALL TABLES IN SCHEMA public\`, sin \`ALTER DEFAULT PRIVILEGES\` y sin permisos sobre un futuro esquema de bloqueo. Cada migración futura deberá revisar manualmente las nuevas tablas y privilegios antes del despliegue.

La función \`sec5_priv_runtime_acl.grant_existing_runtime_acl\` contiene el contrato de concesiones **sin creación de roles ni conexión propia**. Solo el harness aislado de CI puede crear la identidad SQL de prueba y llama a la función para probarla. **No está importada desde \`app.py\`, \`Procfile\` o \`bootstrap_db.py\`.**

## CI real con el esquema y rutas actuales

El job \`postgres-bootstrap\` ejecuta \`qa_sec5_runtime_grants_pg18.py\` contra PostgreSQL 18 local, con protección \`GITHUB_ACTIONS=true\`, \`CI=true\`, \`FLASK_ENV=testing\`, \`SEC5_RUNTIME_ACL_CI_ONLY=1\`, \`DATABASE_URL\` heredado ausente y proveedores externos desactivados. El test:

1. Crea base y rol LOGIN **efímeros**, sin tocar Railway, y reconstruye el esquema con \`bootstrap_db.py\` administrativamente (migrador separado).
2. Ejecuta \`startup_schema_gate.py\` primero con admin y luego con login limitado.
3. Efectúa \`INSERT/SELECT/UPDATE/DELETE\` ORM sobre usuario ficticio, informe FIFO, caso de asesoramiento y contacto; valida IDs y relaciones.
4. Confirma rechazo real de \`CREATE TABLE\`, \`ALTER TABLE\`, \`TRUNCATE\`, \`DELETE\` en \`alembic_version\`, \`SET ROLE postgres\` y \`SELECT\` de un almacén sintético reservado.
5. Verifica que el login limitado **no tiene INSERT en ninguna tabla externa a las 17 ORM**. Destruye base de ensayo y rol en \`finally\`.

Este ensayo **no prueba flujos externos Stripe/Resend, todas las rutas HTTP, permisos de tablas no ORM de futuras versiones, concurrencia real ni retenciones RGPD**. Una CI satisfactoria es condición necesaria, no evidencia de un cambio seguro en producción.

## Estado de staging y criterio NO-GO

Inspección Railway 01/11/2026:

- Existe entorno \`staging\` con PostgreSQL 18 y volumen propio, sin cambios staged.
- El servicio \`fiscal-cripto-staging\` está **fijado al commit** \`50a6632b3217c4cb11ab97214d7f0ea71b410e3b\` de \`validation/privacidad-pr92-staging-20261017\`, **anterior al main actual**. No es un clon listo para probar el runtime actual.
- En staging figuran variables de **Stripe, PayPal, Resend, Google y Turnstile**. Conocer los nombres no demuestra si las claves son ficticias o reales; **no ejecutar pruebas integradas que llamen proveedores** hasta inventario de aislamiento, neutralización y firewall de pruebas.
- No se ha consultado ningún valor secreto, ni filas o expedientes, ni modificado volumen/variables.

## Condiciones para migración posterior (pendiente de autorización)

1. Confirmar identidad de staging, origen de \`DATABASE_URL\`, que apunte **solo a PostgreSQL staging**, y modo de aislamiento de proveedores. No copiar base real ni credenciales productivas.
2. Ejecutar ensayo real de aplicación actual contra BD sintética y usuario limitado, incluyendo login, administración, informes FIFO y estados S01, sin solicitudes externas.
3. Antes de cambios en producción, crear copia cifrada **actualizada** y demostrar restauración aislada; las copias manuales de octubre no acreditan cobertura reciente.
4. En una ventana autorizada, crear login nuevo con contraseña fuerte gestionada por Railway, conceder privilegios exactos, validar por conexión independiente y preparar reversión del DSN; migraciones mantienen usuario admin separado. No degradar el superusuario existente ni publicar contraseñas en GitHub/CI/chat.
5. Cambiar \`DATABASE_URL\` del **servicio web exclusivamente**, no del servicio PostgreSQL, con despliegue controlado y monitoreo; comprobar puerta de arranque, rutas y rollback. El futuro vault de bloqueo legal requiere rol y permisos especiales propios; no está implementado aquí.

**NO MERGE / NO DEPLOY sin revisión independiente y autorización posterior.** Referencias: PostgreSQL 18 \`GRANT\`, \`ALTER DEFAULT PRIVILEGES\` y \`Schemas\`, documentación oficial.
