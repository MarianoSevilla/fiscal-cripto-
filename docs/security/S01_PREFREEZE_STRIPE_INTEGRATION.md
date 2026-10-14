# S01 — Integración controlada PREFREEZE + firma Stripe

**BORRADOR / NO MERGE / NO DEPLOY / NO COBROS.**
Base exacta: commit `a44e33afa47e38d9b40350f707a0c28526dbc193`
de la PR #35. Incluye todas las etapas S01 #33, #34 y #35.

## Propósito y decisiones

- Superponer sin fusionar PR externas la protección **U04-PREFREEZE #30**
  sobre rutas PayPal/Stripe, expediente, presupuesto y webhooks existentes.
- Incorporar **firma obligatoria Stripe #32** al código del webhook, pero
  mantener un decorador incondicional que responde **503** antes de acceder
  al cuerpo del evento; la firma se comprueba solo en ensayos de un handler
  sintético aislado, sin afectar a la ruta pública.
- Revisar **U04 PayPal #29 en lectura**, pero **NO integrarlo** en esta etapa:
  su migración es paralela a la nueva cadena S01 y modifica extensamente
  `app.py`, `models.py`, `qa_db_bootstrap_postgres.py` y rutas financieras.
  Requerirá rama de integración propia y validación transaccional.
- Conservar el orquestador S01 de Checkout **exclusivamente de pruebas
  sintéticas**, sin endpoint HTTP ni invocación al SDK Stripe.
- La aplicación **no crea ni gestiona facturas**. Rafa se encarga
  de la facturación externa; no se añaden tablas ni endpoints de facturas.

## Orden de ejecución y garantías

1. `@app.route` registra la función envuelta; `@limiter.limit`
   permanece como guardia externa de tasa. El decorador
   `@advisory_financial_prefreeze()` se ejecuta **antes del cuerpo**
   de `stripe_webhook`, devolviendo 503 sin leer JSON ni invocar Stripe.
2. El cuerpo del webhook exige de todos modos `STRIPE_SECRET_KEY` y
   `STRIPE_WEBHOOK_SECRET`, firma válida sobre bytes originales,
   firma no caducada y no tiene fallback JSON sin autenticar.
3. El finalizador `_on_payment_completed`, los creadores/capturadores
   PayPal, las rutas de reemisión y la API de estado siguen suspendidos.
4. La página `/pagar/<token>` pasa a mantenimiento sin botón PayPal.
   No se crean nuevos botones ni enlaces Stripe.
5. Intentos S01 sintéticos se pueden probar por llamada a módulo sin
   habilitar rutas web; su esquema usa revisiones
   `x7y8z9a0b1c2` -> `y8z9a0b1c2d3` desde
   `v5w6x7y8z9a0`, y CI PostgreSQL 18 comprueba el head.
6. El flujo de presupuesto real permanece congelado; es imprescindible
   introducir en fase posterior una vía *nueva* y revisada para S01.
   **No retirar PREFREEZE simplemente habilitando Stripe.**

## Comprobaciones necesarias antes de aprobar la PR

- Full Python regression incluidas las pruebas de prefreeze, firma
  aislada y S01 de etapas anteriores.
- PostgreSQL 18 bootstrap y QA de pref review sin proveedores.
- Browser navigation y página de mantenimiento para móvil y escritorio.
- Test de composición que exige decorador incondicional, firma
  sin fallback y auxiliares financieros bloqueados.
- Revisar superposición y cambios de las PR dependientes antes de integrar
  en `main`. Reconfirmar el SHA de main y el alcance de despliegue.

## NO-GO

Sin pruebas de pago real, sin Stripe Test externo ni MERU, sin
migración productiva, sin cambios de Railway, sin emailing, sin
fusionar #29/#30/#32/#33/#34/#35, sin habilitar PayPal. La
implementación de webhooks nuevos de S01 (deduplicación atómica,
correlación con importe y PaymentIntent, manejo de refund/dispute) y
la conciliación de intentos inciertos quedan pendientes.
