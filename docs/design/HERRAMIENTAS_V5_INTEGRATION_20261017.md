# Incorporación de Herramientas V5 y ajuste de ancho de Home

Aprobación del propietario: «cambios aprobados», 17/10/2026 01:07 Europe/Madrid.
Base: main@a45a3b6dc3435f179445cf878f0b99adf7296234.
Fuente aprobada: design/herramientas-apple-preview-20261017@dcf1759cb5677a3abb155ba573a3c50105595281.

## Cambio público

/herramientas mantiene su ruta y pasa a servir el diseño V5 aprobado. Su HTML
coincide exactamente con la fuente aprobada salvo robots, que conserva la
indexación index/follow de la página pública. Se mantienen canonical, las seis
opciones y sus destinos, cinco FAQs con JSON-LD sincronizado y enlaces legales.
Se conservan los enlaces de creación de cuenta, el aviso de suspensión de
presupuestos/pagos de asesoramiento y el alcance orientativo del informe.

La Home conserva su HTML. landing_apple.css añade exclusivamente una regla
para que los párrafos de .apple-assistance .asistencia-block ocupen el ancho
interior disponible. La navegación compartida y el JS de la Home no cambian.

## Archivos

Existentes modificados: static/herramientas.html, static/landing_apple.css y
el entrypoint de QA tests/qa_responsive_layout.py.
Nuevos: herramientas_apple.css/js, qa_herramientas_redesign.py,
test_herramientas_redesign.py y fixture approved_v5.html, más este documento.
No se incorporan las páginas HTML de vista previa ni su simulador de API.

## Validación y publicación

El CI ejecuta la Home original y Herramientas en sus rutas públicas reales,
con sesiones y datos ficticios. Se conservan las suites de navegación, Flask,
backend y PostgreSQL aislado; no se cambian workflows ni dependencias.
La igualdad con el HTML aprobado se verifica mediante un fixture fijado.
Después del CI se verifica nuevamente main y se publica por la fuente GitHub
existente de Railway. Comprobar SUCCESS del nuevo commit, HTTP 200 en Home,
Herramientas y healthz, y coincidencia de CSS/JS/HTML con la fuente validada.

Despliegue previo identificado para reversión:
6a8530d2-611a-4ae3-967b-c058fcb31ed6 (main@a45a3b6d), SUCCESS.
No se alteran Flask, FIFO, seguridad, pagos, variables ni datos de usuarios.
