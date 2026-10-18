# Exchanges — diseño y publicación

Base: main 2d5ffad00eec1f2ac0bc8117245dce3d5aa03a4d. El propietario aprobó el diseño, los logos y los textos del preview y autorizó actualizar producción el 18/10/2026 a las 18:07 (Europe/Madrid).

## Publicación autorizada

El generador escribe static/exchanges.html con index,follow y mantiene static/exchanges_apple.html y el viewer con noindex,nofollow. La única diferencia entre las dos plantillas es esa directiva; el contenido aprobado, los logos, los enlaces, el canonical y los estilos son idénticos. La ruta Flask existente /exchanges sigue sirviendo exchanges.html y no se modifica app.py. El sitemap cambia únicamente lastmod de /exchanges al 18/10/2026. La sesión ficticia se utiliza solo en el viewer; la página real conserva nav.js con el funcionamiento habitual.

La suite responsive pasa a comprobar la plantilla de producción en las 13 anchuras existentes y mantiene dos escenarios para la variante no indexable. Las pruebas finales y el despliegue se documentan en la PR una vez verificados. La autorización incluye las correcciones visuales de captions ya aprobadas en esta rama; no hay cambios de motor, endpoints, pagos, seguridad, variables o base de datos.

## Resultado

Catálogo único de 11 plataformas con el componente verde del home, hero común, enlaces útiles, preparación del historial, alcance por exchange, 11 FAQs nativas y CTA de asesoramiento. Header/footer y recursos compartidos se reutilizan sin modificar sus archivos. No se incorporan afiliaciones ni se anuncia Gate como plataforma compatible.

Las tarjetas incorporan los 11 logos existentes del repositorio. Logo de 44 px y nombre comparten una fila; el formato y enlace quedan debajo. Se conserva el fondo verde y la interacción del home. El contenedor blanco con radio de 10 px unifica la presentación sin recolorear ni recortar las marcas (object-fit:contain). Las dimensiones explícitas reservan el espacio; alt vacío evita duplicar el nombre ya visible. El viewer sirve los mismos archivos desde el propio origen Netlify, sin depender de imágenes externas ni añadir binarios. La suite responsive comprueba que los 11 archivos cargan también sin JavaScript y con texto ampliado.

MEXC indica XLS/XLSX; Crypto.com delimita el CSV a la App. Bit2Me no promete Excel universal porque el camino depende de la configuración activa. KuCoin aparece en el catálogo y sus varios archivos no se confunden con consolidación entre exchanges. Se retiran promesas de soporte completo, casillas universales y revisión profesional de cada descarga.

Las siete guías existentes se enlazan sin registro; Bitget, KuCoin, MEXC y Uphold llevan a sus herramientas existentes con acceso autenticado, explicado debajo del catálogo. No se crean URL de guías inexistentes.

## Contenido y SEO

Actualización aprobada de las tarjetas: 11 descripciones únicas orientadas a preparar el informe, conservando referencias útiles a CSV, Ledger, App, spot o Excel. Las siete guías utilizan «Ver cómo generar el informe»; las cuatro herramientas, «Preparar informe FIFO». No se promete una descarga directa, un informe gratuito ni cobertura fiscal adicional. Se retiran las flechas de estas llamadas a la acción. Los destinos, logos, estilos y orden permanecen.

Base editorial: Search Console a través de Windsor.ai, consulta del 18/10/2026, período solicitado 01/04/2026–15/10/2026. Consultas y páginas individuales: «informe fiscal binance» 275 impresiones/0 clics; «extracto binance para hacienda» 238/0; «coinbase informe fiscal» 70/0; «informe fiscal kraken» 29/1. Son impresiones del sitio, no volúmenes mensuales de mercado. Para Nexo, Crypto.com, Bitget, KuCoin y Uphold no aparecieron consultas en los resultados recuperados; las formulaciones de esas marcas son hipótesis editoriales basadas en las capacidades verificadas. El catálogo /exchanges tiene muy pocos datos y no permite estimar un efecto de posicionamiento. Los términos por marca se desarrollan en las guías de destino; el catálogo facilita su descubrimiento. No se afirma mejora de CTR, ventas o descargas sin medición posterior.

Referencia de enlaces descriptivos y naturales: https://developers.google.com/search/docs/crawling-indexing/links-crawlable . La precisión de MEXC XLS/XLSX se mantiene en la FAQ; la tarjeta resume Excel. No se suprime información de compatibilidad del documento.

Se mantienen los temas útiles de las ocho FAQs anteriores, corregidos y reorganizados; se añaden preguntas sobre formatos y varios archivos. La explicación general de FIFO, obligaciones informativas y comparaciones se conserva en respuestas; se enlazan las guías de FIFO/721 y FAQ. Se elimina la descripción de prestaciones no verificadas, no funcionalidades.

CollectionPage con ItemList derivado del mismo inventario que las tarjetas. Preview noindex/nofollow con canonical a /exchanges. No se promete beneficio de FAQ rich results: Google retiró esa función en mayo de 2026.

Fuentes editoriales: Manual AEAT IRPF 2025 sobre compra/venta y permutas; LIRPF consolidada art.37; FAQ AEAT de modelos 173 y 721; Comisión Europea DAC8; Google Search Central, actualizaciones mayo/junio 2026. Fecha de consulta: 18/10/2026. El texto delimita particulares en territorio común y no modifica ni certifica el motor fiscal.

## Archivos

- static/exchanges_apple.html y exchanges_apple.css: variante aislada; no cambia static/exchanges.html.
- exchanges-apple-preview/index.html y session.json: vista autocontenida para Netlify, sesión anónima local. Los enlaces públicos salen a marianosevilla.com; no se suben archivos ni se ejecutan análisis en esta vista.
- scripts/build_exchanges_preview.py: reconstrucción desde el home y recursos actuales del repositorio. Ejecutar desde raíz con python3; no instala dependencias.
- tests/qa_exchanges_apple.py: navegación, geometría, contenido crítico y accesibilidad funcional en navegador con sesiones sintéticas.
- tests/qa_responsive_nav.py: una entrada de ruta al servidor estático local de QA; no añade una ruta Flask.
- tests/qa_responsive_layout.py: registra la suite nueva en el job de navegador existente.

## Verificación

Contratos estáticos locales correctos: inventario de 11 enlaces, origen/viewer con idéntico contenido principal, 11 disclosures nativos, noindex y sesión local del viewer. Sintaxis Python verificada. Las pruebas de navegador se ejecutan mediante Required CI existente, sin cambiar workflows ni dependencias.

La suite contempla las 13 anchuras 320–1440 px, header sin espacio superior, menú, teclado, ampliación de texto 200 %, movimiento reducido, sin JS y sesiones ficticias. La evidencia ejecutada de CI se documentará en la PR; esta declaración de cobertura no constituye un resultado anticipado.

## Fuera de alcance funcional

Motor FIFO, endpoints de análisis, seguridad, pagos, base de datos, variables, retención y guías individuales permanecen intactos. La actualización pública se limita a la presentación y contenido de /exchanges y a las etiquetas visuales previamente aprobadas.
