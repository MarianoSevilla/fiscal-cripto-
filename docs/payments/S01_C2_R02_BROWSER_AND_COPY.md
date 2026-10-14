# S01 C2-R02 — Corrección de mensajes y navegador E2E

**13/10/2026 · DRAFT · base PR #57:** `3945a97eac76451579c95e90fe571bbdf1f7c05e`.

## Autorización y alcance

Exclusivamente corregir C2-F01 (copy obsoleta) y C2-F02 (cobertura de navegador) en rama separada. No fusionar, desplegar, modificar variables de Railway, migrar BD productiva, consultar PII ni operar Stripe/PayPal/MERU.

- Landing: elimina promesa fija de respuesta de Rafa durante la suspensión.
- URL histórica `/asesoramiento-fiscal-confirmado`: devuelve **503 / no-store**, informa que la página no acredita solicitud ni pago; conserva una página informativa sin acción de cobro ni redirect a checkout.
- Panel: corrige textos y señales visuales que sugerían cobrar o enviar presupuestos nuevos; preserva las etiquetas del historial.
- `qa_s01_c2_r02_browser.py` levanta **Flask real** con fichero SQLite temporal en localhost, sin acceso a proveedores, y ejecuta Chromium sobre formulario, permisos, CSRF, panel, nota, estado, expediente histórico, enlaces financieros bloqueados y móvil/escritorio.
- CI: se añade el paso E2E al job existente `browser-navigation`. No se alteran migraciones, modelos, Stripe Connect, motor PayPal ni esquema G04.

## Criterios de aceptación

1. SHA base y diff propios intactos.
2. Suite completa backend, PostgreSQL 18 y browser incluyendo C2-R02: SUCCESS en SHA final.
3. Revisar el resultado independientemente; sin CI verde no se afirma cobertura E2E ni cierre C2-R02.
4. Conservan sus restricciones los gates G04/G05, los históricos PayPal y la revisión de privacidad C2-06; futura integración y producción exigen autorización específica.
