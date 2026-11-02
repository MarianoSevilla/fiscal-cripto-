# SEC5-PRIV — Verificación explícita de privilegios del login Flask (PostgreSQL 18)

**Estado:** herramienta de inspección preparatoria, **sin activar en producción**. No crea roles, no migra tablas y no es el sistema legal de bloqueo.

## Motivo y límite

En Railway, el servicio web \`fiscal-cripto-\` utiliza \`DATABASE_URL\`. El conector conectado permite comprobar el nombre de la variable pero no el rol PostgreSQL que contiene ni sus privilegios. Es incorrecto afirmar que es un login limitado o propietario sin comprobarlo en la conexión real. El piloto de bloqueo en PR #173 demostró la separación de dos credenciales **sintéticas**, no la configuración de producción.

Esta PR introduce \`fiscal_app_export/sec5_priv_role_preflight.py\` para identificar, en **la conexión del propio Flask**, riesgos observables a través de los catálogos PostgreSQL 18. La inspección solo lee \`pg_roles\`, \`pg_database\`, \`pg_namespace\`, \`pg_class\`, atributos del usuario, propiedad de objetos y posibilidad de asumir roles privilegiados. La consulta y la comprobación de \`transaction_read_only\` se ejecutan bajo \`SET TRANSACTION READ ONLY\` y la transacción se revierte. No lee clientes, informes, expedientes, pagos, contraseñas, \`pg_authid\` ni correo electrónico.

## Uso exclusivamente explícito — pendiente de autorización para conectar con producción

El archivo **no se importa** desde \`app.py\`, \`Procfile\`, \`bootstrap_db.py\` ni \`startup_schema_gate.py\`; no cambia el arranque de la web. Solo la ejecución consciente del comando \`SEC5_PRIV_ROLE_PREFLIGHT=EXPLICIT_READONLY python sec5_priv_role_preflight.py\` en un contexto donde \`app\` pueda acceder a su propia conexión permite la inspección. No ejecutar este comando en Railway sin una decisión operativa específica. No debe conectarse con un DSN de administrador distinto de \`DATABASE_URL\` de la aplicación, porque respondería a una pregunta diferente.

La salida es deliberadamente limitada: \`NEEDS_SEPARATION\` y nombres de riesgos si detecta superusuario, capacidad de asumir roles privilegiados, pertenencia a propietarios, privilegios DDL, etc.; o \`CANDIDATE_ONLY\` si no detecta esas condiciones. En cualquier caso informa \`VAULT_PROVEN: false\`. No imprime URI, usuario, contraseña ni excepciones crudas.

**Advertencia:** \`CANDIDATE_ONLY\` es una condición preliminar, no una certificación de mínimos privilegios. No prueba ACL específicas de un futuro esquema de bloqueo, rutas HTTP/administrador, funciones \`SECURITY DEFINER\`, permisos futuros, proveedores, borrado ni RGPD. Es posible que una credencial limitada siga teniendo \`SELECT\` explícito sobre información personal: se necesitarán pruebas negativas cuando exista el almacén real.

## Validación

- Tests unitarios sobre fallos cerrados, ausencia de activación automática, rollback y señalización de propietarios / superusuario / \`SET ROLE\` privilegiado.
- Test de CI PostgreSQL 18 con dos conexiones **realmente autenticadas**: \`postgres\` y un usuario de prueba sin privilegios en el contenedor desechable; roles temporales creados por el *harness* CI y eliminados al terminar. La herramienta de inspección **no ejecuta ningún DDL**.
- Tres trabajos de CI exigidos: \`backend-tests\`, \`postgres-bootstrap\` y \`browser-navigation\`. No declarar la PR apta sin el resultado exacto del HEAD.

## Puerta de diseño posterior

1. Acreditar rol actual de la conexión Flask en un momento autorizado mediante el preflight de solo lectura; proteger la salida.
2. Aprobar política de conservación por finalidad y base/excepción para cada categoría de datos (PR #172). No hay calendario de supresión aprobado.
3. Diseñar el reparto entre rol web limitado, rol migrador operativo separado y rol excepcional legal con auditoría; probar todas las ACL, membresías y accesos antes de despliegue.
4. Obtener backup nuevo, cifrado y restauración aislada verificable antes de permisos/migraciones, con protección frente a reintroducción de datos suprimidos.
5. No fusionar ni desplegar esta herramienta ni los pilotos por una CI PASS; son pasos preparatorios distintos del tratamiento de datos reales.
