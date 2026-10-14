# STG-B11E · Puerta final de preparación del esquema (bloqueada por código)

**Fecha: 14/10/2026.** Fase de inspección y validación **exclusivamente GitHub CI**. Ninguna conexión de repositorio a Railway, ningún despliegue ni SQL de escritura.

## Datos efectivos confirmados de forma independiente (solo lectura)

- GitHub `main`: `56882073295faae3bd1bc3632288a970acb330da`; PR #86 B11D en borrador, CI `38618861684` **SUCCESS en cuatro casos de interrupción**.
- Railway proyecto `5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e` / entorno `lab` `3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8`.
- Postgres **original** clúster `7696213098351943739`, servicio `f680f3fc-4581-44ff-8bc1-d034840f2c7e`, volumen `c35d178f-7473-4d0b-adb9-1faae815b7af` — NUNCA DESTINO DE DDL S01.
- Destino futuro **Postgres-Im3h** clúster `7696517018472497211`, servicio `317b21e9-b259-4b15-902a-a7bec69b7407`, volumen independiente `16144c31-17d5-49e7-a725-967e883e03f9`. El backup real B10S se restauró como BD vacía; no se ha inicializado el esquema real S01.
- Administrador `s01-lab-schema-preflight` ID `007db029-c99d-4a68-a965-fd0de3496614`: únicamente referencia `TARGET_DATABASE_URL=${{Postgres-Im3h.DATABASE_URL}}`; sin deployments, dominios, proxies ni volúmenes, `restartPolicyType=NEVER`, sin cron. **La vinculación del repositorio en B11B fue bloqueada por un control de seguridad de la plataforma; no se repite ni se sortea.**
- Administrador anterior `s01-lab-maintenance` mantiene `DATABASE_URL` al original. No utilizar, alterar ni otorgar permiso de DDL sobre su conexión.
- Web del laboratorio sin desplegar; sin modificaciones pendientes en Railway. Original, destino y sus volúmenes siguen separados.

## Qué cambia B11E

`infra/s01_lab_schema/bootstrap_release_gate.py` es un contrato exclusivamente puro, deliberadamente **sin motor de escritura**:

- `SOURCE_RELEASED=False`; `release_gate()` siempre **NO-GO (DDL_NOT_AUTHORIZED)**. Cambiar superficialmente el boolean a `True` sigue denegando como `UNREVIEWED_SOURCE_CHANGE`.
- `validate_review_parameters()` permite *inspeccionar sin sockets* una configuración hipotética de un futuro runner. Reutiliza los pins de identidad `preflight.py`; rechaza hostname original, IDs equivocados, claves externas y una variable de autorización del restore previamente usado.
- La cadena de intención (no es una contraseña ni una credencial) está fijada a un único bootstrap, clúster `7696517018472497211` y cabeza Alembic `z9a0b1c2d3e4`. Su presencia **no habilita nada** ni reemplaza una autorización humana.
- Sin `psycopg2`, SQLAlchemy, `app.py`, ORM, Alembic, `subprocess` ni `db.create_all`. No es un ejecutor de esquema y **no se empaqueta en el Dockerfile B11B**.
- Test `test_bootstrap_release_gate.py` con 14 contratos: identidades, bloqueo absoluto, intento de activar con variables, denegación del origen, rechazos de credenciales adicionales y ausencia de código de DDL.
- Se ejecuta únicamente en GitHub Actions sin secretos Railway, servicio Postgres, ni redes externas.

## Plan de desbloqueo LEGÍTIMO, sin operaciones técnicas elusivas

1. Resolver **formalmente** la política de seguridad que rechazó la conexión de fuente al servicio B11B, mediante el soporte/controles autorizados de la plataforma. El mensaje de bloqueo no aclara su causa concreta; no atribuirla a un error de GitHub, red o credenciales sin evidencia. No lanzar herramientas equivalentes, CLI directa, Actions deploy, duplicación de servicio o otra ruta mientras se mantenga la restricción.
2. Cuando la política lo permita, realizar inventario nuevo: nombre/IDs/volúmenes inmutables, `main` congelada, sin cambios staged, permisos/proveedores deshabilitados, servicio privado con 0 dominios/proxies y sin cron.
3. Con autorización para **sonda de lectura únicamente**, conectar al servicio B11B una versión probada con SHA fijo y verificar desde el propio proceso `PG18.6`, `system_identifier=7696517018472497211` y **las seis categorías de objetos a 0**. De momento, **esto NO se ha ejecutado**.
4. Solo entonces diseñar la imagen ejecutora **separada y revisada**, que no importe `app.py` ni confunda el proyecto/servicio de mantenimiento con la web de producción. Debe usar el mismo pinned target, advisory lock, comprobación real de catálogo y plan manual ante migración parcial.
5. Congelar commit exacto, ejecutar CI de esquema + fallos parciales + antirreintentos y presentar el alcance al propietario. **Solicitar autorización específica independiente** para una única escritura de DDL sobre Postgres-Im3h. Cualquier fallo implica STOP, nunca DROP/retry/reparación automática.

## NO-GO persistente

B11E no autoriza conectar el servicio bloqueado, habilitar ejecutores, crear tablas, sellar Alembic, migrar esquema real, fusionar PRs, modificar `main`, web, Stripe, PayPal o correo. La base de recuperación sigue preparada pero **sin inicialización de la aplicación**.
