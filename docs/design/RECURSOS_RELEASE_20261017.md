# Recursos · integración del diseño aprobado

Autorización: propietario aprueba V5 y solicita «actualiza»,17/10/2026 19:57 Europe/Madrid. Base main2d39aec1d280fde31dd99f163cf1b1a1794e41c9. Origen aprobado: PR100,9d1b770fffa7406f69fed4608f2bc7c87652a172.

Se sustituyen únicamente templates/recursos.html y recurso.html; app.py y rutas permanecen sin cambios. Tres parciales nuevos de Recursos reutilizan header/footer Home. CSS/JS nuevos y aislados. El head usa index,follow y canonical de las rutas reales. Catálogo dinámico desde Resource, siete productos de pago con destinos individuales existentes, checklist con aportación libre desde0EUR, Bitvavo/Gate con referral exacto, disclosure sponsored y enlace al vídeo público del propietario. No se afirma seguridad absoluta ni se inventan ventajas o incentivos. Hero sin CTA redundante.

Formulario conserva campos, valores, consentimientos obligatorios, endpoint y payload. Bitvavo/Binance siguen siendo las opciones existentes: los colaboradores del catálogo no modifican las reglas de elegibilidad. Se preservan los contenidos/requisitos dinámicos del recurso, textos legales y advertencia de riesgo. Correcciones de presentación: errores accesibles, prevención de doble envío y confirmación fuera del formulario oculto.

Fuera de la integración: raíces Netlify, mocks de fetch/sesión, objetos Resource ficticios en plantillas, variantes duplicadas *_apple.html, documentos/referencias del prototipo. Fixture sintética exclusiva de tests. Ninguna dependencia, variable, DB, migración, servicio de pago, FIFO o control de seguridad modificado. Sin cambios a Home, Herramientas o Cómo funciona.

Validación: suite existente incorpora48 escenarios de Recursos con13anchos, zoom200%, noJS, reduced motion, roles y POST interceptados; siete contratos Jinja ahora apuntan a las plantillas de producción y exigen indexabilidad/ausencia de mocks. Tests previos de GET públicos y API ResourceRequest se conservan. CI de integración pendiente; despliegue solo después de verde.

Publicación por integración en main y despliegue automático del servicio Flask existente, sin cambiar configuración Railway. Verificar estado SUCCESS y GET públicos/healthz/recursos y ficha publicada, sin enviar formulario. Reversión: revertir el commit de esta integración si aparecen incidencias.
