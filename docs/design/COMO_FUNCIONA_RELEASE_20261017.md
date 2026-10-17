# Cómo funciona · integración V2 aprobada

El propietario aprobó la V2 visual y autorizó integrar/publicar con «procede» el17/10/2026 a las15:43 Europe/Madrid.

Base main ba51cafc19aaab59597615aa6b95ab22fa42ae09. Fuente aprobada c39ec4316e3f3a8a9bddd66391b0fb77bdc1264a, PR98. como-funciona.html contiene exactamente la variante aprobada salvo robots index,follow. Se conservan URL/canonical, siete FAQs y su JSON-LD, seis anclajes, destinos legales y acceso. Cabecera/footer y activos comunes siguen iguales. La ruta Flask no cambia.

Nuevos activos: como_funciona_apple.css/js y apple_cta.css. El componente CTA opt-in solo se adopta en Cómo funciona en esta entrega. CTA de Home y Herramientas intactos. Seis contratos y24 escenarios responsive de la variante adaptados para comprobar el archivo original; entrypoint ya existente ejecuta la suite. Sin cambios de dependencias, FIFO, sesiones, roles, CSRF, pagos, infraestructura, variables ni datos.

Excluidos: página fuente como_funciona_apple.html, raíz Netlify, mock anónimo y documento de trabajo de PR98. No se fusiona la rama de prototipo. El contenido de producción no incluye fetch mock ni noindex.

Criterios: CI completo correcto; diseño y CTA sin overflow320–1440; tabla con cinco columnas disponibles; header sin hueco; teclado, texto200%, movimiento reducido y sinJS correctos. Tras integrar main, verificar estado SUCCESS del despliegue correcto, /healthz y /como-funciona públicos, activos nuevos y continuidad de Home/Herramientas. Reversión limitada al HTML anterior y archivos de esta entrega si hiciese falta, sin cambios de base de datos.
