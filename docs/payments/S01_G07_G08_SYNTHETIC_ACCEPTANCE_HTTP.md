# S01 — G07/G08 · Aceptación explícita y Checkout HTTP simulado

**13/10/2026 · PR de pruebas aisladas (apilada sobre #49) · NO MERGE · NO DEPLOY · NO STRIPE TEST EXTERNO · NO PAGOS.**

## 1. Qué se ha revisado antes de modificar

- `advisory_s01_pricing.calculate_s01_quote`: honorarios que introduce Rafa y comisión del **30 %**, redondeo HALF_UP, en céntimos. Es un **criterio económico provisional**, pendiente de confirmación de impuestos/IVA y comerciante de registro (G06); no es factura.
- `advisory_s01_checkout.build_test_checkout_request`: contrato puro de Stripe-hosted Checkout TEST; confirma importes y expiración, sin contactar a Stripe.
- `advisory_s01_test_orchestrator.create_synthetic_checkout`: asegura reserva duradera única con `SELECT FOR UPDATE` y COMMIT *antes* de llamada de proveedor, valida `cs_test_`, importe EUR, fingerprint y sesión; ante timeout deja el intento `uncertain` y bloquea el segundo.
- `advisory_s01_test_http`: receptor de webhooks exclusivamente sintético; no se fusiona con el nuevo flujo. PREFREEZE mantiene `/pagar/<token>`, APIs y webhook legacy en 503. El nuevo módulo **no se importa ni registra desde `app.py`**.
- La base real ya posee `quote_accepted_at`, `quote_acceptance_user_agent` y `quote_acceptance_ip`; no es necesaria una migración para registrar la aceptación.

## 2. Nuevo flujo G07 — exclusivamente en Flask TESTING ficticio

`advisory_s01_synthetic_acceptance_http.py` exporta **solo** una factory `build_s01_synthetic_acceptance_blueprint`; no tiene registro automático de rutas y **no** realiza red:

1. GET `/__synthetic__/s01/quotes/<int:advisory_id>` con cabecera `X-S01-Quote-Token` (32–64 caracteres URL-safe); devuelve exclusivamente honorarios/comisión/total, EUR, y token CSRF nuevo en sesión. **GET no escribe la base ni acepta el presupuesto**. Token opaco permanece fuera de la URL y del JSON de respuesta. No se publican datos identificativos ni notas.
2. POST `/__synthetic__/s01/quotes/<int:advisory_id>/accept` exige `FLASK_ENV=testing`, `current_app.testing`, flag de fixture aislada, `Origin` exacto `https://checkout-test.example.invalid`, JSON acotado, una aceptación explícita `confirm: true`, `total_cents` entero exacto y CSRF de un solo uso vinculado a sesión/expediente/huella del token.
3. Se valida que el presupuesto sea **ficticio**, `status=quote_sent`, desglose matemáticamente correcto, vencimiento mínimo de 30 minutos, ningún pago, orden, intento, provider o aceptación anterior. Tras bloquear el expediente y revalidar el importe exacto, se persiste `quote_accepted_at` **antes** de llamar al orquestador y sin introducir identidad, IP real ni PII de cliente.
4. Se reutiliza `create_synthetic_checkout` con `_InProcessFakeStripeProvider` fijo, sin SDK/API ni credenciales, para representar una sesión `cs_test_...` ficticia. Una sola reserva duradera por expediente; ante fallo de la llamada queda `uncertain`, sin reintentar. La respuesta HTTP 202 indica **solo** `synthetic_checkout_reserved_not_paid`, `payment_confirmed=false` y `external_stripe_called=false`; **no devuelve URL `checkout.stripe.com` ficticia**.
5. Toda recepción de Checkout/webhook, reembolsos, cancelaciones, incidencias, facturas, correos y payouts quedan fuera de este módulo. Rafa gestiona facturación externamente.

### Garantías testadas

- GET sin mutación SQL ni exposición de nombre/email/documentos.
- Rechazo de token erróneo, expediente no ficticio o expirado.
- CSRF vinculado a sesión, token y expediente; denegación de otro origen, confirmación ambigua, importe incorrecto, JSON inválido/redundante, replay de petición o token gastado.
- Caducidad/cambio de presupuesto **entre preview y aceptación**: rechazo.
- `quote_accepted_at` persistido **antes** de reserva, estado no pagado en todos los casos, intento único por expediente, timeout ambiguo bloqueado; el navegador no recibe URL de cobro real.
- No se registra ruta alguna en app Flask de producción, no se cambia PREFREEZE ni las constantes de entorno. Nunca se instala credencial `sk_test_` externa; el valor usado por el orquestador es fijo y ficticio.

## 3. Diferencia entre G07/G08 TEST y autorización para Stripe Test externo

**Esta PR NO cierra G07/G08 para uso real.** Solo prueba el contrato HTTP sintético y el paso de intención. La aceptación en producción futura requiere una revisión independiente de cookies/CSRF, token de pago, rate limiting, autenticación/autorización, ergonomía y accesibilidad y capturar el consentimiento legal final aprobado (G06). El primer Checkout auténtico en `stripe.com` requiere **autorización expresa de acceso de escritura Stripe TEST** y una rama/PR posterior, revisada con claves ficticias, restricciones de egress y entornos. Las pruebas actuales no dan por acreditados Apple Pay/Google Pay.

Antes de exponer cualquier ruta pública: G04 despliegue y migrations por separado; G05 declaración del propietario de que no ha habido cobros PayPal y conteos actuales limitados; G06 términos completos y merchant-of-record con Rafa; G09 firma HTTP y eventos; G10 recuperación de ACK y objetos inciertos; G11 refunds/chargebacks; G12 outbox de envío; G13 payout MERU; G14 QA; G15 release y G16 monitorización.

## 4. Prohibiciones

No usar en producción, staging conectado a Internet, Railway, Stripe TEST real, Stripe Live, PayPal, MERU o cuenta bancaria; no cambiar variables, secretos, roles, webhook, datos, tablas, DNS o paquetes. No añadir factura en aplicación. No merge/deploy/suscripciones S02. Esta factory es solamente un **harness Flask local sin egress** para probar seguridad y UX contractual, NO un botón de cobro.
