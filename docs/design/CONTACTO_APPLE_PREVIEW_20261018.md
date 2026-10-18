# Contacto Apple — preview aislada, 18 de octubre de 2026

El usuario autoriza preparar la preview tras la auditoría de Contacto. Base: main `0024383b68dd16c60f20d108ed5957442d626a04`. No fusionar esta rama como entrega de producción.

## Alcance

Ocho archivos: `static/contacto_apple.html`, `static/contacto_apple.css`, `static/contacto_apple.js`, visor `contacto-apple-preview/index.html`, fixture local `session.json`, QA `tests/qa_contacto_apple.py`, incorporación al runner `qa_responsive_layout.py` y este documento. Las rutas son relativas a fiscal_app_export salvo visor y docs. No se cambia `static/contacto.html`, backend, modelos, migraciones, datos, seguridad, FIFO/721, pagos ni assets compartidos. No se instalan dependencias.

## Diseño

Reutiliza sin cambios nav.css/nav.js y landing_apple.css/landing_apple.js publicados. Hero verde con ancho completo, fuente del sistema, header y footer aprobados. Botón píldora de envío y formulario legible, ayuda lateral en escritorio y apilada en tablet/móvil. Acceso explícito al servicio de Rafael Ramos y FAQ secundaria. No añade un CTA que salte al formulario ni un bloque comercial repetido.

## Formulario

Campos originales: nombre, email, tipo, mensaje y lectura de privacidad. Límites 80/254 caracteres y 20–3000 en mensaje, validación cliente alineada con el servidor actual, errores asociados, resumen alert, foco y estados anunciados. Seleccionar asistencia fiscal conserva datos y ofrece un enlace; no redirige.

Declaración method=post, campos y botón deshabilitados hasta registrar el controlador y alternativa de correo sin JS. Evita GET con datos; no se anuncia un POST nativo compatible con la API JSON. Sin persistencia de borradores en almacenamiento del navegador. Los fallos conservan lo escrito en el formulario y no se reenvía automáticamente.

Primera capa de privacidad alineada con la política publicada: responsable, finalidad, base descrita, proveedores y derechos. La casilla se presenta como lectura de información, no consentimiento comercial ni prueba persistida de aceptación. No cambia la base jurídica en servidor ni añade registro de consentimiento. Las bases específicas de consultas ajenas al servicio deben revisarse antes de publicar; no se presenta una certificación legal.

## Aislamiento y circuito de integración

El HTML variante y el visor fijan `data-contact-mode="preview"`. En ese modo el controlador valida localmente y muestra, solo tras pulsar enviar, que no se ha enviado el mensaje. No llama a /api/contacto, no carga Turnstile ni genera emails/registros. El modo de revisión es el valor seguro por defecto para cualquier valor distinto de live.

La rama incluye un controlador preparado para integración posterior, pero no habilitado en el HTML: el modo live mantiene la API JSON y su payload actual, honeypot y verificación en servidor. Añade callbacks de carga, caducidad/error y reset de Turnstile, prevención de envíos simultáneos y tratamiento de 400/429/500, no JSON y red. No altera el comportamiento del servidor si falta la clave de Turnstile; ese hallazgo de seguridad requiere tarea independiente.

El visor incorpora copias inline de los assets y sustituye exclusivamente el GET /api/me del nav por un fixture visitante local. No intercepta globalmente fetch. Enlaces fuera del documento llevan a páginas públicas de producción; correo y solicitud profesional son acciones explícitas del visitante. No incluye credenciales ni datos reales. `noindex,nofollow`, canonical /contacto.

## Validación

QA prevista: 48 escenarios en 13 anchos: layout/teclado/menú y validación preview, cuatro sin JS, tres con texto 200 %/movimiento reducido, roles sintéticos, sesión demorada, visor móvil/desktop, errores de campos y 18 escenarios del controlador live local. Las solicitudes POST de esos escenarios se satisfacen con respuestas ficticias en Playwright y el widget de seguridad se reemplaza con JS sintético. Cualquier solicitud externa o API no esperada falla la prueba. No importa la app ni se conecta a DB/proveedores.

La validación local se limita a sintaxis/build porque no hay ejecutable Chromium local; la batería visual se ejecuta con el entorno Playwright ya existente de CI. No instalar para esta tarea. Se conservan todas las suites anteriores, incluidas Términos y Privacidad de producción. No afirmar que la prueba ha pasado hasta observar el resultado en el commit final.

## Entrega posterior

Tras aprobación, preparar entrega limpia desde main vigente. Antes de habilitar live, confirmar primera capa según clases de consulta y probar integración con datos sintéticos y proveedores interceptados, incluido token/error/reintento. Revisar HTML final, robots y API en staging; excluir visor y fixture. La publicación y cualquier cambio del backend requieren la autorización correspondiente; esta preview no actualiza producción.

Fuentes: auditoría entregada 18/10/2026; código de la base indicada; RGPD https://www.boe.es/buscar/doc.php?id=DOUE-L-2016-80807 ; W3C https://www.w3.org/WAI/tutorials/forms/notifications/ y https://www.w3.org/WAI/WCAG22/Understanding/on-input.html ; Turnstile https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/ y https://developers.cloudflare.com/turnstile/get-started/server-side-validation/ .
