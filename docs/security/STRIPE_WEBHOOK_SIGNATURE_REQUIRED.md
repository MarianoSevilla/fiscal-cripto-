# SEC-STRIPE-SIG-001 — Firma obligatoria de webhooks Stripe

Estado: **cambio propuesto y no desplegado**. Rama independiente basada en `main` `56882073295faae3bd1bc3632288a970acb330da` (12/10/2026).

## Hallazgo

El controlador `POST /api/webhooks/stripe` de `fiscal_app_export/app.py` aceptaba eventos JSON sin verificar cuando `STRIPE_SECRET_KEY` estaba presente pero `STRIPE_WEBHOOK_SECRET` estaba vacío. Una carga `checkout.session.completed` construida por un tercero podía alcanzar el flujo de confirmación si coincidía con una sesión pendiente, sin demostrar que procediese de Stripe.

**Riesgo alto condicionado**, sin evidencia de explotación ni de esa configuración concreta en producción. La integración de Stripe Test tenía un webhook habilitado hacia `https://marianosevilla.com/api/webhooks/stripe`; el webhook de pruebas `we_1TWJPr1Bbv71AKgzE8g3goEX` fue deshabilitado por separado antes de esta corrección.

## Contrato de comportamiento propuesto

1. Si el SDK Stripe no está disponible o faltan `STRIPE_SECRET_KEY` **o** `STRIPE_WEBHOOK_SECRET`, responder **503** sin leer ni procesar el evento, registrar únicamente una categoría técnica sin secretos.
2. Exigir cabecera `Stripe-Signature`. Si está ausente, responder **400**, sin acceso a expedientes.
3. Validar la autenticidad y antigüedad de la firma utilizando `stripe.Webhook.construct_event(payload, signature, secret)` con los **bytes originales** del cuerpo. Si la firma o el JSON no son válidos, responder **400**; nunca aceptar `json.loads` sin firma.
4. No registrar cuerpos, firmas, excepciones de verificación ni datos financieros en logs.
5. Solo después de verificar la firma aplicar la lógica existente de eventos `checkout.session.completed`. No cambiar estados ni modelos, conciliación, pagos reales o comportamiento de PayPal.
6. Los errores inesperados se propagan como errores del servidor (sin confirmación HTTP 2xx). Los errores durante la confirmación de pago conservan el rollback y el HTTP 500 existentes.

## Pruebas

`fiscal_app_export/tests/test_stripe_webhook_signature_required.py` ejecuta la función original extraída por AST en Flask sintético para **evitar el bootstrap de la base de datos**. Usa SDK real Stripe y firmas HMAC SHA-256 generadas con secretos ficticios, sin credenciales, red, base de datos o pagos reales. Casos de ausencia de SDK/claves, firma ausente/incorrecta/caducada, cuerpo manipulado, JSON inválido con firma real, filtración en logs, evento no relevante, sesión inexistente, sesión pendiente válida, duplicado ya pagado y error de persistencia.

La CI `Required CI` es la autoridad para declarar el resultado de la suite completa y las pruebas de PostgreSQL/Playwright. No afirmar éxito antes de que concluya.

## Riesgos y puertas de integración

- **Cambio funcional deliberado**: una instalación de producción sin `STRIPE_WEBHOOK_SECRET` ahora respondería 503 (antes podía devolver 200 y/o aceptar JSON sin firma). **No desplegar** sin verificar por un operador, sin revelar valor, la presencia del secreto correcto y la firma de un webhook Stripe legítimo.
- El preflight de Railway staging de la PR #31 exige que las credenciales Stripe estén vacías y devuelve 503 a webhooks: este cambio no las habilita ni anula el lockdown.
- Las PR #29 U04 y #30 PREFREEZE modifican también `app.py`: revisar la futura integración de ramas, evitar sustituir inadvertidamente controles PayPal o de suspensión financiera.
- **No soluciona** el contrato de conciliación ni los estados de cobro incierto, ni valida eventos Stripe con API de conciliación, ni confirma idempotencia entre entregas. Es una corrección acotada a autenticidad.
- El endpoint Stripe Test hacia producción sigue deshabilitado; no redirigirlo/reactivarlo ni iniciar sesiones de Checkout sin autorización separada.

## Límites operativos

**Autorizado aquí:** cambio de código, pruebas automatizadas y PR en borrador. **Prohibido:** fusionar, desplegar, cambiar Railway/Stripe, reactivar webhooks, introducir claves, hacer pagos o escribir datos reales.
