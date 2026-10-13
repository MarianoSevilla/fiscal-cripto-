# STG-B01 — Integración STG-LOCK-001 sobre S01 (modo seguro y pruebas sintéticas)

**Alcance 13/10/2026:** solo código y pruebas GitHub, sin desplegar, modificar Railway, consultar registros ni migrar bases reales.

## Decisiones de seguridad

1. Se porta **sin cambios de comportamiento** el módulo `staging_isolation.py` y su suite `test_staging_isolation.py` desde el commit de staging `f421a9c21f99267eb0aedf05705c93b62fba3ba9` al árbol candidato PR #60 `d4edd911a343fba15d92ef6c035bd118b6c24fe9`. Se reinstala el control **antes de `db.init_app`** en `app.py`; la instancia no intenta corregir `DATABASE_URL` ni migrar.
2. La **aplicación Railway staging permanece bloqueada por defecto**: no se añade interruptor de entorno para desbloquear POST, autenticación, pagos o webhooks. El aislamiento exige `FLASK_ENV=staging`, identificadores Railway, host `postgres-zzky.railway.internal`, URL canónica, PayPal sandbox sin secretos, Resend/Stripe/OAuth inertes y denegación por defecto, preservando la excepción exacta del healthcheck.
3. El **modo laboratorio que se puede validar ahora** es solo `FLASK_ENV=testing` en CI, con base SQLite temporal, datos `example.invalid` y sin acceso externo. Es el modo empleado por `qa_s01_c2_r02_browser.py` para las 26 comprobaciones E2E. No confundirlo con habilitar un laboratorio expuesto por Railway. La variable `S01_SYNTHETIC_LAB_MODE` se usa **solo como entrada ficticia negativa** en el test de regresión para probar que NO abre las rutas reales; no existe ningún nuevo feature flag de producción.
4. El nuevo ensayo `qa_stg_b01_app_isolation.py` usa un proceso separado con identidad Railway **ficticia**, URL de DB con usuario/password falsos y `socket.socket.connect`/psycopg2/requests prohibidos. Demuestra respuesta de Flask a rutas autorizadas y rechazadas sin DB, email ni proveedores. El subproceso `testing` usa únicamente `TemporaryDirectory`.
5. La base web de producción no cumple ninguna identidad staging y el guard es inerte fuera de staging; debe comprobarse nuevamente por CI y revisión externa. **No habilita Stripe Connect ni restaura PayPal.**

## Gate de staging real, aún pendiente

**NO-GO al despliegue de esta PR sobre el staging actual** porque el conector OAuth no expone los valores de `DATABASE_URL` ni garantiza que la BD del servicio staging tenga exclusivamente datos ficticios. Se requiere que el propietario confirme en la UI solo la **referencia** a `Postgres-zZky`, sin URL, passwords ni tokens, y la revisión Alembic mediante consulta SELECT ejecutada en el editor del propio servicio DB staging, sin PII ni modificaciones.

El bloqueo actual evita ejecutar el E2E real en Railway. Para un ensayo funcional de S01 en staging será necesario **un entorno de laboratorio adicional con una BD nueva y vacía, o una modificación posterior expresamente aprobada** con prueba verificable de dataset sintético, controles de egress, autenticación y ningún proveedor real. No basta con añadir un flag a `FLASK_ENV=staging`. **Ese futuro modo desplegable no forma parte de esta PR**, para no arriesgar los datos existentes.

## Estado, autorización y CI

- Baseline git preescritura: `main=56882073295faae3bd1bc3632288a970acb330da`, PR #60=`d4edd911a343fba15d92ef6c035bd118b6c24fe9`, staging `f421a9c21f99267eb0aedf05705c93b62fba3ba9`.
- Tres ficheros del bloqueo se integran en la candidata desde la rama staging, con sus tests; no se retargeta staging ni se modifica su rama o commit pin.
- Verificar CI Required completa de la nueva cabeza antes de cierre. No autoriza merge ni despliegue.
