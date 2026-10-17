# Recursos · variante aislada V1

Base main 2d39aec1d280fde31dd99f163cf1b1a1794e41c9. Autorización del propietario: «procede»,17/10/2026 16:08 Europe/Madrid, para preparar catálogo y ficha aislados tras auditoría. No publicar ni fusionar sin revisión visual y definición de acceso.

Plantillas recursos_apple.html y recurso_apple.html, con tres parciales nuevos. Header/footer de Home y estilos compartidos sin cambios. Nuevo recursos_apple.css/js; apple_cta.css reutilizado. Hero verde, tarjetas Home, tres pasos de acceso, afiliación legible antes de enlaces, CTA de ayuda. Ficha conserva campos, opciones Bitvavo/Binance, condiciones dinámicas, consentimientos obligatorios y endpoint/payload. Mejoras de foco/errores, bloqueo de doble envío y confirmación fuera del formulario oculto. Sin JavaScript se ofrece contacto. No cambia elegibilidad ni backend.

Catálogo y ficha reciben objetos Resource como los originales. Se preservan título/headline/subtitle/description/contenidos/requisitos/CTA dinámicos. Enlaces de afiliación exactos (incluidos parámetros), sponsored/noopener y destinos legales conservados. Recurso y slug de la vista son ficticios; no se consulta producción ni se envían solicitudes reales. Previews noindex/nofollow y canonical original. Las raíces Netlify simulan solo /api/me y rechazan otros fetch. No incorporar esas raíces a la integración final.

Pruebas: seis contratos con Jinja real, casos sin recursos/múltiples/títulos largos, campos y afiliación, éxito fuera del formulario y footer idéntico. Suite navegador nueva incorporada al entrypoint actual: dos plantillas, trece anchos, texto200%, noJS, movimiento reducido, roles ficticios, API simulada en éxito/error/reintento/desconexión y UID. Capturas home_resources_*.png. Sin instalaciones ni cambios de workflows/dependencias.

Antes de publicar: resolver discrepancia catálogo (Bitvavo/BingX/Bitget/Bitunix) vs formulario/API (Bitvavo/Binance), requisitos de cuentas existentes y condición de registro referido. La propuesta deja de afirmar que todos los enlaces desbloquean todos los recursos; cada ficha conserva sus requisitos. No dar por aprobada una ampliación de exchanges ni alterar consentimiento comercial. No cambios en app.py, modelos, DB, variables, Railway, pagos, FIFO o seguridad.

Los originales templates/recursos.html y recurso.html, y todas las páginas publicadas permanecen intactos. Pendiente CI y revisión visual.

## V2 · catálogo real y colaboradores actuales

Petición del propietario 17/10/2026 16:37 Europe/Madrid: eliminar el aviso visible de prototipo, añadir recursos de su tienda y mostrar solo Bitvavo/Gate como colaboradores. Se retira la nota de ambas raíces y su CSS. Sesión anónima simulada y bloqueo de envíos se mantienen internamente; no se habilitan envíos reales.

La tienda pública masetru.gumroad.com y sus ocho fichas respondieron200 el17/10/2026: siete materiales de pago (Algorand, VELO, XDC, ISO20022, SHX, HBAR y Mapa del nuevo dinero) y una checklist con precio mínimo0EUR y aportación libre. Cada tarjeta enlaza directamente a su ficha, conservando URL y layout=profile. No se copian precios de los materiales de pago: se consultan en Gumroad para evitar desactualización. Catálogo separa gratuitos/de pago. Bitcoin conserva su formulario; Gumroad gestiona las compras/descargas existentes, sin integración nueva de pagos. Los pasos de solicitud se refieren únicamente al dossier gratuito.

Colaboradores: Bitvavo conserva su URL; Gate usa exactamente la campaña facilitada previamente por el propietario: https://www.gate.com/es-eu/campaigns/76?ref=VFKRXV1ACA&ref_type=132 . Se eliminan BingX, Bitget y Bitunix de esta variante. Gate devolvió403 en la comprobación pública: no se afirma vigencia de promociones; verificar campaña antes de publicar. No se añade Gate al formulario ni se elimina Binance de la API, porque esta petición afecta al bloque de colaboradores y no autoriza cambiar las reglas de acceso.

Se amplían contratos a siete y se conserva la matriz de48 escenarios. Pendiente CI de V2 y revisión visual. Producción intacta.

## V3 · compra y registro como objetivos principales

Petición del propietario 17/10/2026: retirar las menciones visibles a la plataforma de venta, concretar las acciones y orientar Recursos a ventas y registros. Se conservan los destinos individuales y parámetros de afiliación exactos. CTA de pago: Comprar informe (5), Comprar guía y Comprar el mapa; checklist: Descargar checklist con aportación libre desde0EUR. Comprar refleja el paso previo a descargar. Partners: Registrarse en Bitvavo / Registrarse en Gate.

Jerarquía: hero con acceso a informes y atajo a colaboradores; informes y guías primero, colaboradores después, recursos gratuitos y pasos de solicitud a continuación. Mantiene tarjetas Home, hover/foco/movimiento reducido y aviso de afiliación antes de los enlaces. Ninguna promoción, urgencia, testimonio o resultado financiero inventado. No se añade seguimiento ni scripts de terceros. El cambio persigue facilitar conversiones, no acredita un aumento de CTR.

Criterio UX contrastado: Nielsen Norman Group, “Learn More Links: You Can Do Better” y “Better Link Labels: 4Ss for Encouraging Clicks”: etiquetas descriptivas y expectativas coherentes con el destino. Medición propuesta tras aprobación: clic por recurso/exchange y compras/registros confirmados, diferenciados por dispositivo y fuente; no atribuir ventas a meros clics. La configuración de medición requiere revisión posterior y no forma parte de este cambio.

Se refuerzan contratos y los48 escenarios con orden de secciones, etiquetas de compra/registro y ausencia de branding visible de la plataforma. Pendiente CI de V3. Producción intacta.
