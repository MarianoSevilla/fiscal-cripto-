# S01 STG-B10G — Verificación de huella PostgreSQL real

Fecha: 14 de octubre de 2026.

El propietario aportó de la consulta **de solo lectura** ejecutada en Railway Postgres > Database > Query:
- DB `railway`; `server_version_num=180006`; `system_identifier=7696213098351943739`; `inet_server_addr=127.0.0.1`; puerto 5432.
- `127.0.0.1` representa la interfaz local de esa sesión y **no debe exigirse** como IP de conexión del ejecutor privado. La huella PostgreSQL es el elemento comparable.

## Permiso y delimitación de riesgo

La respuesta explícita `Autorizo` después de presentar la prueba del ejecutor privado se interpreta **solo como aprobación de prueba de conexión de solo lectura**, no como autorización de DDL, bootstrap, restauración del volumen original, merges, web deploy ni pagos/correos.

## Comportamiento de código

`private_maintenance_identity.py` comprueba proyecto/entorno/ID exacto maintenance, dominio privado, `FLASK_ENV=staging`, rechazo de URLs públicas y secretos de proveedores, destino PostgreSQL privado `postgres.railway.internal:5432/railway`, y `sslmode=require`. Esta validación es anterior a importar `psycopg2` y a abrir socket.

En una sola conexión obligatoriamente `READ ONLY`, hace dos lecturas independientes:
1. Preflight B10A de esquema vacío (tablas, relaciones, funciones, tipos, schemas, extensiones, event triggers) + identidad DB/PG18.
2. `pg_catalog.pg_control_system().system_identifier` + PG18 + DB y `transaction_read_only=on`; exige exactamente `7696213098351943739`.

Se ejecuta una sola vez, registra exclusivamente estado PASS/NO-GO y la huella pública, *nunca* el DSN, contraseña o error del driver. El código no importa `app.py`, `bootstrap_db.py`, Flask, pagos ni modelos; no tiene rutas HTTP ni SQL modificador.

**Límites:** `sslmode=require` cifra, pero no equivale a verificación estricta de identidad del certificado servidor como `verify-full`. La huella comprueba la identidad del clúster, no reemplaza la validación de variables de Railway o de TLS. El rol de BD podría tener poderes de escritura, pero este proceso trabaja en transacciones READ ONLY y termina. No hay un mecanismo de autorización de DDL.

**NO-GO permanente:** no activar `bootstrap_db.py`, `alembic upgrade`, `db.create_all`, cambios de rol o esquemas; no conectar Web service, no borrar/restaurar volúmenes, no tocar staging/producción.

## Pasos operativos condicionales

1. CI offline verde y revisión de commit.
2. Validar nuevo inventario de `lab`, servicio maintenance sin source y datos públicos, política NEVER/cron=none, referencia nativa Postgres, id DB service esperado.
3. Fijar en **servicio maintenance lab** un comando de arranque exclusivo `python -u private_maintenance_identity.py` y root `/fiscal_app_export`; comprobar antes de conectar fuente. Mantener variables y secretos externos ausentes.
4. Conectar fuente GitHub **anclada al SHA exacto**; primer deploy tiene una única finalidad: ejecutar la inspección READ ONLY. Registrar resultado de logs redacted.
5. Si NO-GO, detener; no arreglar variables ni activar código distinto automáticamente. Documentar bloqueo y requerir revisión.
6. Si PASS, retirar o inmovilizar la fuente ejecutable bajo procedimiento seguro; conservar evidencias y retornar servicio a modo inerte.

En todo caso **no se modifica** `main`, otras PR, el servicio web ni PostgreSQL original.
