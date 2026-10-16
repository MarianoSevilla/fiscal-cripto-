# Preparación de incorporación del Home V24

Base verificada: main@8cbb38fc96e9ba47f5e4657182c8ea4a2855a6e4.
Diseño aprobado: design/home-apple-preview-20261015@2116d76d33c1d3e98a03fc9f01bef9a965d86c3c.
El propietario confirma V24 en sus dispositivos y autoriza preparar la integración.
No autoriza publicación en producción: la propuesta se mantiene en rama aislada.

## Cambio preparado

Se sustituye exclusivamente static/landing.html por el HTML de V24. La única
diferencia respecto a la variante aprobada es robots: se conserva index, follow
del Home original. Se mantienen título, canonical, Open Graph, doce FAQs con
JSON-LD sincronizado, enlaces de destino, aviso legal y autenticación existente.
Los cambios fiscales son los ya autorizados durante la revisión editorial.

Se añaden landing_apple.css/js y doce retratos locales WebP/PNG, copiados por
SHA desde la rama aprobada. No se copian las vistas HTML descargables, su
adaptador Netlify, las versiones de revisión ni una segunda ruta pública.
Flask ya sirve landing.html en /: no necesita modificación.

La base main no cambió desde la rama de diseño; el Home y la navegación
compartida conservan sus hashes de referencia. Esta preparación no fusiona
la rama de diseño completa, para evitar incorporar artefactos auxiliares.

## Pruebas

- Contratos de conservación contra una copia fijada del Home anterior y las
  excepciones editoriales autorizadas.
- Igualdad exacta con el HTML V24 aprobado salvo la política de indexación.
- Navegación, sesión, permisos visibles, autenticación inline y tabla conservados.
- qa_responsive_layout.py ejecuta ahora la auditoría V24 sobre /, en lugar de
  requerir las fuentes externas y la estructura del hero anterior. No cambia
  qa_responsive_nav.py ni el workflow Required CI.
- 26 escenarios Chromium en 13 anchuras entre 320 y 1440 px, incluyendo texto
  ampliado, teclado, roles, sesión tardía y alternativa sin JS en móvil/tablet.
- El CI existente mantiene las pruebas de Flask, backend y PostgreSQL aislados.

Los fixtures contienen solo HTML anterior/aprobado y datos ficticios; no se
accede a cuentas de usuarios, CSV reales ni servicios de pago.

## Revisión antes de publicar

Revisar el diff, comprobar que main no ha cambiado y confirmar el CI del SHA
final. Se conservan sin cambios nav.css, nav.js, app.py, configuración, FIFO,
suscripciones, seguridad, pagos, DB y variables. No se modifica index.html de
Netlify, que no es el Home servido por Flask.

La propuesta requiere autorización posterior para merge/despliegue de
producción. Los casos particulares de recompensas siguen sujetos a revisión
fiscal de Rafa; la redacción del Home es condicionada.
