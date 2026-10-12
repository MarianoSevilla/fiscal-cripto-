# S01 — PostgreSQL 18, concurrencia real del consumidor de webhooks TEST

**PR en borrador; NO MERGE, NO DEPLOY, NO PAGOS.**

Punto de partida: PR #37, head exacto `9a6e674de7f61f610bcc5f27aaebd91d57a5e21f`. Sin modificación de `main`, PR anteriores, Railway, credenciales, Stripe, PayPal, MERU o datos reales.

## Prueba nueva

Archivo: `fiscal_app_export/tests/qa_s01_stripe_pg18_concurrency.py`.
Ejecución: **solo** `postgres-bootstrap` de Required CI sobre servicio `postgres:18` aislado de GitHub Actions.
La prueba requiere simultáneamente `GITHUB_ACTIONS=true`, `CI=true`, `FLASK_ENV=testing`, credenciales sintéticas codificadas de CI, conexión a `127.0.0.1:5432`, usuario `postgres`, servidor PostgreSQL 18 y DB de nombre fijo `s01_concurrency_pg18_ci`. No acepta DSN arbitrarias ni secretos de entorno y elimina su base efímera al terminar.

Se insertan **solo expedientes inventados** marcados `is_test=True`, presupuesto de 200 € en honorarios + 60 € de comisión, intento único y sesión de Stripe inexistente `cs_test_`. Se generan dos eventos con HMAC artificial que validará el SDK local. **No se invoca ningún endpoint ni API de Stripe.**

Cada carrera utiliza **dos procesos independientes de Python** con conexiones PostgreSQL separadas, una barrera simultánea y un retardo mientras se mantiene `SELECT FOR UPDATE` del expediente; fuerza contención de bloqueo real. Se repiten las tres primeras carreras dos veces con nuevos registros:

1. **Mismo `event.id` simultáneo:** un proceso `paid`, otro `duplicate`; un solo recibo y un solo historial.
2. **Dos `event.id` distintos, mismo PaymentIntent:** `paid` + `already_paid`; dos recibos, un único historial.
3. **Dos PaymentIntents distintos para el mismo expediente:** un `paid`, otro rechazo; solo uno se acepta, nunca se reemplaza el PI.
4. **Intento en estado `uncertain`:** ambos eventos rechazados sin marcar pago.
5. **Excepción en INSERT de historial:** rollback conjunto de expediente, intento y recibo, seguido de recuperación mediante **reenvío del mismo evento firmado**, sin un segundo pago.

Se consulta el estado real de tablas después de cada carrera; no basta verificar valores de retorno. Se aborta ante subprocess crash o deadlock. La prueba compara que cada instancia confirme a lo sumo un pago y solo la referencia esperada.

## Límites / NO-GO

- Prueba contención de bloqueo y fallo inyectado; **no prueba caídas SIGKILL**, particiones de red, pérdida de ACK del COMMIT, reintentos agotados de Stripe, envíos de email ni tolerancia a eventos fuera de orden en producción.
- El **consumidor permanece TEST-ONLY** (requiere `FLASK_ENV=testing`), sin HTTP endpoint y sin llamada real a Stripe.
- **PREFREEZE sigue bloqueando el webhook público con 503**; este ensayo no constituye permiso de reactivación.
- Falta outbox transaccional y una solución de conciliación de PayPal #29 o decisión de retirada auditada, además de ordenar ramas Alembic.
- Nunca registrar, almacenar ni emitir facturas fiscales en la web: las gestiona Rafa fuera de la aplicación.

La CI completa **debe ejecutarse en el nuevo commit** (backend-tests, postgres-bootstrap y browser-navigation). No declarar éxito antes de que termine.
