# Herramientas · propuesta aislada V1

Base: main@a45a3b6dc3435f179445cf878f0b99adf7296234, Home V24 aprobada y publicada.
Alcance autorizado: preparar, probar y mostrar una variante aislada de Herramientas.
No sustituye herramientas.html ni altera rutas Flask o configuración de Railway.

## Diseño

Introducción breve, seis tarjetas visibles en todos los dispositivos, bloque
compacto de alcance/equipo, cinco FAQs nativas y cierre de contacto. Escritorio:
tres columnas; tablet: dos; móvil: una. Se reutilizan sin cambios nav.css,
nav.js, landing_apple.css y landing_apple.js para conservar el header/footer
aprobados, la sesión y los permisos. Las mejoras Home que buscan elementos
exclusivos del informe no encuentran esos elementos en Herramientas.

El footer es idéntico al de la Home. El header solo añade nombre accesible y
estado de página actual. herramientas_apple.js conserva ese estado al recrear
nav.js el menú móvil; no modifica autenticación ni peticiones.

## Contenido

Se conservan los seis destinos originales, el aviso legal y los enlaces legales.
La tarjeta 721 se presenta como guía; no promete un diagnóstico interactivo.
Se retiran promesas de informe completo gratuito y presentación por el asesor.
Se conserva el aviso vigente de suspensión de presupuestos/pagos de asesoría.
El texto sobre FIFO y alcance del informe adapta la redacción ya aprobada de
la Home. FAQ visible y JSON-LD se generan en paralelo y se comparan en tests.
No se eliminan funcionalidades ni se cambia el estado de acceso de ninguna.

La variante tiene noindex/nofollow y canonical a /herramientas. La futura
integración requerirá restaurar index/follow y validar los metadatos finales.
El original indexable permanece intacto durante esta revisión.

## Vista pública de pruebas

herramientas-apple-preview.html es una derivación autocontenida con el mismo
HTML/CSS y scripts compartidos. Simula únicamente /api/me anónimo; rechaza
otras operaciones fetch. Sus enlaces llevan a producción. No sirve para probar
una sesión real ni contratar servicios. Los permisos se verifican en CI con
usuarios ficticios y APIs interceptadas; no se accede a datos de usuarios.

## Verificación

Cuatro contratos de contenido/SEO/accesos. QA Chromium en el CI existente:
13 anchos de 320 a 1440, cuadrícula 1/2/3, seis destinos visibles, ausencia de
overflow, header sin hueco, menú/teclado/FAQ, roles sintéticos, texto 200%,
movimiento reducido y menú sin JavaScript. El entrypoint de QA conserva la
suite Home y añade la nueva suite. No se cambian workflows ni dependencias.
Las capturas home_herramientas_*.png utilizan el artefacto CI existente.

## Incorporación posterior

Solo después de aprobación visual y autorización de integración: reemplazar
herramientas.html por el HTML aprobado con política de indexación original;
conservar la URL /herramientas y añadir sus CSS/JS. Revisar canonical/schema,
CI completo y captura de cada dispositivo. No fusionar esta rama automáticamente.
