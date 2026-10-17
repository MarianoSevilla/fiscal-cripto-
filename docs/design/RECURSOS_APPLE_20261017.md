# Recursos · variante aislada V1

Base main 2d39aec1d280fde31dd99f163cf1b1a1794e41c9. Autorización del propietario: «procede»,17/10/2026 16:08 Europe/Madrid, para preparar catálogo y ficha aislados tras auditoría. No publicar ni fusionar sin revisión visual y definición de acceso.

Plantillas recursos_apple.html y recurso_apple.html, con tres parciales nuevos. Header/footer de Home y estilos compartidos sin cambios. Nuevo recursos_apple.css/js; apple_cta.css reutilizado. Hero verde, tarjetas Home, tres pasos de acceso, afiliación legible antes de enlaces, CTA de ayuda. Ficha conserva campos, opciones Bitvavo/Binance, condiciones dinámicas, consentimientos obligatorios y endpoint/payload. Mejoras de foco/errores, bloqueo de doble envío y confirmación fuera del formulario oculto. Sin JavaScript se ofrece contacto. No cambia elegibilidad ni backend.

Catálogo y ficha reciben objetos Resource como los originales. Se preservan título/headline/subtitle/description/contenidos/requisitos/CTA dinámicos. Enlaces de afiliación exactos (incluidos parámetros), sponsored/noopener y destinos legales conservados. Recurso y slug de la vista son ficticios; no se consulta producción ni se envían solicitudes reales. Previews noindex/nofollow y canonical original. Las raíces Netlify simulan solo /api/me y rechazan otros fetch. No incorporar esas raíces a la integración final.

Pruebas: seis contratos con Jinja real, casos sin recursos/múltiples/títulos largos, campos y afiliación, éxito fuera del formulario y footer idéntico. Suite navegador nueva incorporada al entrypoint actual: dos plantillas, trece anchos, texto200%, noJS, movimiento reducido, roles ficticios, API simulada en éxito/error/reintento/desconexión y UID. Capturas home_resources_*.png. Sin instalaciones ni cambios de workflows/dependencias.

Antes de publicar: resolver discrepancia catálogo (Bitvavo/BingX/Bitget/Bitunix) vs formulario/API (Bitvavo/Binance), requisitos de cuentas existentes y condición de registro referido. La propuesta deja de afirmar que todos los enlaces desbloquean todos los recursos; cada ficha conserva sus requisitos. No dar por aprobada una ampliación de exchanges ni alterar consentimiento comercial. No cambios en app.py, modelos, DB, variables, Railway, pagos, FIFO o seguridad.

Los originales templates/recursos.html y recurso.html, y todas las páginas publicadas permanecen intactos. Pendiente CI y revisión visual.
