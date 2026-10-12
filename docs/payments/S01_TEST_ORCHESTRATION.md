# S01 · Etapa 3 — Reserva duradera + creación simulada de Stripe Checkout TEST

**Estado:** desarrollo aislado. **NO MERGE / NO DEPLOY / NO PAGOS / NO STRIPE EXTERNO.**

## Contrato de producto

- **S01**: presupuesto personalizado valorado por Rafa.
- Honorarios de Rafa + **30 % de comisión** = total económico previsto para el cliente.
- El cliente pagará en el futuro mediante Stripe Checkout (tarjeta, Apple Pay o
  Google Pay según elegibilidad del dispositivo).
- **La aplicación no emite, almacena ni envía facturas fiscales.**
  Rafa gestiona la facturación por fuera de la aplicación.
- **S02 suscripciones queda fuera de esta PR.**

## Cambios de esta rama

Añade solo `advisory_s01_test_orchestrator.py` y
`tests/test_advisory_s01_test_orchestrator.py`:

1. Barrera de entorno `FLASK_ENV=testing` + clave `sk_test_` +
   `is_test=True` + URL de retorno no productiva.
2. Requiere un presupuesto `quote_sent`, token del expediente,
   desglose de 30 % consistente, precio en céntimos y vencimiento válido.
3. Bajo `SELECT ... FOR UPDATE` del expediente, comprueba la ausencia
   de intentos y actividad de pago anterior.
4. Registra un intento único (`UNIQUE(advisory_id)`) en estado `creating`
   con identificador UUIDv4 y clave de idempotencia; **COMMIT antes** de
   invocar al proveedor inyectado.
5. El adaptador de pruebas sintético representa `Session.create`.
   Este código **no importa Stripe SDK ni construye un cliente API real**.
6. Verifica `cs_test_`, `livemode=False`, `mode=payment`,
   `payment_status=unpaid`, importe EUR, ID del expediente, metadatos
   y host HTTPS de Stripe antes de devolver el enlace.
7. Registra `checkout_session_id` tanto en el intento como en el
   expediente, con un **segundo COMMIT obligatorio** antes de devolver URL.
8. Toda respuesta ambigua, respuesta malformada, timeout o error de
   persistencia bloquea reintentos mediante estados `creating`/`uncertain`.
   Si falla el registro del estado incierto, el estado `creating`
   previamente confirmado sigue bloqueando.
9. **Un intento por expediente**, decisión conservadora de esta fase.
   Una futura funcionalidad de regeneración necesitará conciliación,
   expiración verificada y cambios de esquema/revisión independientes.
10. Ninguna ruta pública, blueprint, botón, webhook ni email está
    conectado a este módulo. Los tests usan datos sintéticos y un
    proveedor simulado, sin credenciales ni llamadas reales.

## Advertencias / NO-GO

- **No se ha probado una llamada a Stripe Test real**. No confundir el
  contrato unitario con un pago funcional, ni afirmar que Apple/Google
  Pay funcionan hasta verificar con un dispositivo elegible.
- La suite de CI usa SQLite para el ciclo sintético; la prueba de Alembic
  usa PostgreSQL 18. FALTAN pruebas de dos procesos simultáneos con DB18
  sobre esta función, SIGKILL, pérdida de ACK COMMIT, red, claves idempotentes
  mayores de 24 horas y compatibilidad integrada con las ramas financieras.
- PR #35 depende de #34 y #33; temporalmente apunta a `main`
  para ejecutar Required CI, por lo que su diff incluye cambios acumulados.
- No desplegar el código aislado: todavía existe en el árbol base el
  webhook Stripe antiguo, pendiente de integrar #32, y PayPal U03.
- Resolver integración con **#30 PREFREEZE**, **#32 firma Stripe** y
  **#29 U04 PayPal** antes de exponer rutas y migraciones reales.
- **No declarar un presupuesto pagado por redirección** ni desde la
  respuesta de creación de Checkout. Faltan webhooks firmados,
  recibos de evento atómicos, conciliación y outbox de notificaciones.
- No alterar Railway, producción, staging, cuenta Stripe, MERU, webhooks,
  credenciales ni datos privados. No ejecutar migrations productivas.

## Siguiente iteración recomendada

Implementar consumidor de webhook Stripe Test **a partir de un evento
previamente verificado con firma**, con deduplicación y confirmación atómica
contra el intento persistido. Solo después integrar endpoints protegidos de
staging, manteniendo producción en estado financiero congelado.

## Prueba CI

Se verificará `Required CI` (backend, PostgreSQL 18, navegador) tras abrir PR
en borrador, sin introducir ninguna dependencia nueva.
