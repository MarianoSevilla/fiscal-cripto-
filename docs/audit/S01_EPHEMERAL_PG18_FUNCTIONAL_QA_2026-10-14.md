# S01 QA: PostgreSQL 18 desechable local a un contenedor (14/10/2026)

**No crear un tercer PostgreSQL persistente:** la nueva prueba `s01-qa-disposable-pg18` usa PostgreSQL 18 oficial dentro de su mismo contenedor efímero. `initdb`, datos y socket se crean exclusivamente en un directorio TemporalDirectory de /tmp **sin volumen Railway**, y el PDF usa otro subdirectorio temporal; al terminar se detiene el servidor y elimina todo. PostgreSQL acepta **solo Unix sockets**, sin listener TCP y sin dominio ni proxy público.

El contenedor valida antes de cualquier conexión proyecto/env/servicio (ID exacto), variable de aprobación **sólo para QA efímero**, ausencia de DATABASE_URL/TARGET_DATABASE_URL y de credenciales de Stripe, PayPal, Resend, Google. Tras validación borra del proceso las variables RAILWAY_ y reconstruye exclusivamente la configuración sintética testing con una URL a su socket privado. Esta sustitución está prohibida salvo en este contenedor y no modifica la configuración de la web LAB.

Prueba: esquema PostgreSQL 18 con `db.create_all`, Alembic stamp `m6n7o8p9q0r1` y upgrade `z9a0b1c2d3e4` **exclusivamente en el cluster efímero**. Usuario/asesor .invalid, autenticación real, CSV Bitvavo generado en código (compra/venta BTC), FIFO, PDF, prueba de acceso ajeno y uso único, nota/estado asesor con CSRF, rutas financieras negadas, bloqueo requests/Resend/TCP. Al concluir imprime un único resultado PASS/NO-GO sin datos privados.

**Importante:** la autorización no incluye ejecutar DDL en `Postgres` ni `Postgres-Im3h`, abrir endpoints de `s01-lab-web`, cambiar `main`, staging, producción, pagos o email. Service `47fa01c4-777e-4d7f-87b2-5b698341ff93` preparado en staged, sin despliegue hasta pasar guardias + CI. La ejecución es de **un solo uso**, sin reintentos; un fallo se documenta sin relanzar automáticamente.

Previsto: reinicio NEVER, cron ausente, 0 dominios, 0 TCP proxies, 0 volúmenes, sin variables de conexión a DB externa. Concluir documentando el resultado en PR #90 sin cerrarla ni integrarla.
