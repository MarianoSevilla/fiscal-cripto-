# Home Apple: vista Netlify V23 para dispositivos reales

Autorización del propietario: 16/10/2026, actualizar la URL de pruebas existente.

- Rama exclusiva: design/home-apple-preview-20261015, PR #91 en borrador.
- URL: https://deploy-preview-91--fiscal-cripto.netlify.app/home-apple-preview.html
- Archivo publicado: home-apple-preview.html.
- Versión: copia exacta de Home_Apple_v23_header_sin_hueco.html.
- SHA-256: f9bb4e5bd164bf0e3f6926584f78796f720732de12019e0fe222ffccf7b7654b.

Incluye la revisión fiscal V20 y la cabecera nativa de la vista previa V23.
Es un artefacto estático de revisión, con noindex/nofollow y sesión pública
simulada; las llamadas fetch quedan bloqueadas salvo /api/me, que devuelve
usuario anónimo. No valida Flask, roles, sesiones, exportación ni cálculo FIFO.
Los enlaces a otras páginas llevan al sitio existente; no son páginas rediseñadas.

No sustituye index.html ni fiscal_app_export/static/landing.html y no actualiza
main, Railway, datos, variables, pagos ni seguridad. La variante fuente de la
PR continúa en V6: este cambio publica solo el artefacto visual V23. No se debe
fusionar esta rama para incorporar el rediseño sin sincronizar antes las fuentes
actuales y ejecutar la validación final correspondiente.

Verificación local del diseño actual: 13 contratos de contenido/estructura y
12 escenarios sintéticos de sesión satisfactorios; no son QA de navegador real.
Pendiente revisión móvil/tablet sobre esta URL para investigar el hueco que
solo se ha observado dentro del visor de archivos del iPhone.
