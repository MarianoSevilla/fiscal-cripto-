# Contacto — publicación aprobada, 18 de octubre de 2026

El usuario aprueba la preview #108 y autoriza expresamente su publicación. Entrega limpia desde main `0024383b68dd16c60f20d108ed5957442d626a04`, sin integrar rama de preview, visor, fixture o variante HTML.

Nueve archivos: `fiscal_app_export/static/contacto.html`, `contacto_apple.css`, `contacto_apple.js`; `tests/qa_contacto_apple.py`, `qa_contacto_integration.py`, incorporación al runner `qa_responsive_layout.py` y a `qa_flask_navigation.py`, mapa local /contacto en `qa_responsive_nav.py`; este documento. Assets compartidos, API/backend, modelos, datos, variables, seguridad, FIFO/721 y pagos sin modificaciones.

El HTML coincide con la preview aprobada `d96c47179e7d79a2392fc6504be90db1e95f96ff` salvo robots index, follow y modo live. CSS/JS específicos idénticos a los revisados. Hero, header/footer, fuente y botones coherentes con Home. Selección de asesoramiento sin redirección, ayuda y correo alternativo visibles, errores asociados, foco y estados anunciados.

El controlador activo envía JSON a la API /api/contacto existente, mantiene campos/payload y honeypot y exige token Turnstile para enviar. Carga el widget oficial con tema claro y maneja caducidad/error y reinicio tras cada intento; no se modifica la verificación en servidor. Sin reenvíos automáticos ni almacenamiento de borradores. Con JS ausente o fallido, campos y botón deshabilitados y alternativa de correo hasta inicializar; method post impide GET con datos. No se anuncia soporte POST nativo en la API JSON.

La primera capa y la casilla son las aprobadas: lectura de información de privacidad, no alta comercial ni registro nuevo de consentimiento. Se mantiene el tratamiento existente descrito en Privacidad; no se añaden finalidades, destinatarios o promesas de borrado. La publicación no certifica cumplimiento jurídico total ni sustituye la evaluación de bases específicas de cada clase de consulta.

QA de producción: 46 escenarios sintéticos en 13 anchos en /contacto del servidor local (se eliminan los dos exclusivos del visor). API y seguridad ficticias en navegador. Mantiene todas las regresiones previas. Se añaden siete escenarios de integración contra Flask real en la SQLite temporal de qa_flask_navigation: tres anchos con envío, persistencia y email simulado; cuatro rechazos de servidor sin registro/email. La protección del entorno y los mocks no alteran app.py ni acceden a proveedores o datos reales.

Las comprobaciones de sintaxis e igualdad de HTML/assets preceden CI. No informar de publicación antes de CI correcto, merge autorizado y Railway SUCCESS con el commit coincidente. Tras publicar: verificar GET /contacto, assets, modo live, robots/canonical, diseño, carga/estado de verificación y /healthz. No generar consultas ni correos ficticios en producción; la entrega efectiva de correo no queda acreditada por una prueba simulada.

Fuentes: auditoría entregada 18/10/2026 y revisión #108; API app.py:3912–4008 y modelo Contacto en la base indicada. Documentación oficial Turnstile: https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/ y https://developers.cloudflare.com/turnstile/get-started/server-side-validation/ .
