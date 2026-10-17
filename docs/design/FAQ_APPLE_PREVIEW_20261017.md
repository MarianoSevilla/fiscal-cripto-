# FAQ · variante para revisión

Base: main acd3c08bfb605582813e78f683b58d6ae721053b. Autorización del propietario: preparar la versión de prueba tras auditoría y datos Search Console, 17/10/2026. No autoriza publicación de /faq.

Alcance: nuevo static/faq_apple.html, faq_apple.css y faq_apple.js; raíz estática faq-apple-preview/index.html para Netlify; qa_faq_apple.py e incorporación al runner responsive ya existente. Se reutilizan header/footer y activos Home sin modificarlos. No se cambian FAQ original, rutas, motores FIFO, app.py, políticas, pagos, servicios, configuraciones ni dependencias.

20 preguntas en cuatro grupos; orden inicial historial/FIFO por consultas reales de Search Console (España, web, 17/07–14/10/2026). Las impresiones no equivalen a volumen de mercado. Preguntas nativas details/summary, varias abiertas, soporte sin JS, enlaces de categorías y apertura por ancla con mejora JS. Hero de ancho completo y CTA con clases Home aprobadas. Sin buscador ni terceros de analítica. Noindex/nofollow en variante y preview; canonical /faq. WebPage existente de producción no se modifica. No se añade marcado FAQ para prometer resultados enriquecidos.

## Revisión editorial antes de cualquier integración

- Rafa debe revisar las nueve respuestas de Declaración e impuestos y el criterio FIFO entre plataformas. Se distingue generar renta de estar obligado a presentar; no se publican casillas universales ni mínimos exentos de cripto. En staking/airdrops se conserva deliberadamente una redacción de alcance y casuística, sin atribuir revisión profesional ya hecha.
- Referencias oficiales consultadas: manual AEAT IRPF 2025, compra/venta/permuta de monedas virtuales; FAQ AEAT Modelo 721; fuentes detalladas en Auditoria_FAQ_marianosevilla_2026-10-17.md. No se afirma que una plataforma concreta comunica determinados datos a Hacienda en un ejercicio específico.
- Tratamiento de datos: la nueva respuesta reconoce temporales y registro de datos de informes que existen en app.py. Falta confirmar plazos, finalidad detallada y limpieza de todos los casos; no se inventan garantías. La política actual conserva contradicciones identificadas en auditoría: su corrección necesita alcance y validación propios antes de publicar esta variante.
- Cuenta/precio: crear cuenta gratis no equivale a informe completo gratuito. Completar condiciones comerciales cuando estén definidas; no se inventa un producto descargable gratis ni se promete asesoramiento activo.
- Compatibilidad: catálogo mantenido por exchange; no se promete consolidación global automática ni cobertura de todos los tipos de operación.

Estas observaciones son para revisión interna y no aparecen como mensajes provisionales en el contenido de la página. La variante no se debe fusionar hasta cerrar revisión fiscal, privacidad y condiciones comerciales.

## Verificación

Suite responsive añadida: 13 anchos, geometría del header sin espacio inicial, menú, 20 preguntas, teclado, varias abiertas, cuatro anchos sin JS, zoom de texto 200%, anclas, movimiento reducido y roles sintéticos. Intercepta API de sesión y prohíbe solicitudes externas/escrituras. Capturas en artefactos CI. La preview autónoma simula visitante y bloquea llamadas de backend; enlaces ordinarios llevan a las páginas reales. El mock no debe integrarse en producción.

Entorno local: Playwright de Node preinstalado, pero no hay ejecutable Chromium disponible. No se descarga ni instala. Se usa el navegador disponible para revisión visual y la dependencia de navegador del flujo CI ya existente para la matriz. No dar la matriz por superada antes de comprobar CI.
