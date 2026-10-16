# Home Apple: variante aislada para revisión

Base: `main@8cbb38fc96e9ba47f5e4657182c8ea4a2855a6e4`.
Estado: propuesta visual. No sustituye la Home, no se despliega y no autoriza merge.

## Alcance

- Nuevos `static/landing_apple.html`, `landing_apple.css`, `landing_apple.js`.
- Documento de revisión y pruebas de preservación/navegador.
- Una llamada adicional en `qa_responsive_layout.py` permite que el CI existente
  compruebe esta variante con las herramientas ya declaradas. No cambia workflows.
- Sin cambios a `landing.html`, `nav.css`, `nav.js`, `app.py`, rutas, pagos,
  seguridad, motor FIFO, configuración o base de datos.

## Decisiones visuales

Interfaz clara, con apertura verde profundo en V7, tipografía de sistema sin
fuentes externas y verde de acción en el resto de la página.
Mensaje principal, CTA y ejemplo ficticio al inicio; funcionamiento, informe,
exchanges, asesoramiento y equipo después; contenido SEO íntegro al final.
FAQ con detalles nativos, teclado y contenido en el HTML. Tablas del ejemplo
conservan las cinco columnas mediante scroll local. Estilos bajo `.apple-home`.

Se preserva el contenido original, con las dos correcciones de redacción
autorizadas en la revisión v6 (descritas abajo). Se mantienen los enlaces de
destino, datos estructurados, canonical, campos y script de autenticación de
la Home de referencia. Se añade
una indicación de datos ficticios y el aviso de suspensión de presupuestos/pagos
que ya rige en las páginas de asesoramiento de la base.

`noindex,nofollow` identifica la variante. No se enlaza desde navegación o sitemap.
Esto es una medida de indexación, no un control de acceso: la privacidad de la
revisión depende de mantener la rama sin despliegue y de compartir solo los
artefactos de prueba. No se crea una ruta pública ni se modifica Flask.

## Pruebas

`python -m unittest discover -s fiscal_app_export/tests -p test_home_apple.py -v`

Protege contenido, párrafos, enlaces, JSON-LD, canonical, IDs, archivo original y
script de autenticación. No importa la aplicación ni requiere Flask o DB.

El CI existente ejecuta `qa_responsive_layout.py`, que conserva la prueba original
y llama además `qa_home_apple.run_home_apple`. La ampliación comprueba 12 anchuras,
estados de navegación con roles sintéticos, acordeones, diálogo, texto 200%,
movimiento reducido, menú de altura baja y navegación sin JS. Toda petición API
se intercepta con fixtures; las escrituras y tráfico externo hacen fallar la prueba.
Capturas: `qa-artifacts/home_apple_*.png`, recogidas por el artefacto existente.

El autor debe revisar los resultados y las capturas del SHA final. Hasta entonces,
el código de un test no constituye evidencia de que haya pasado.

Pendiente de validación física Safari/iOS y lector de pantalla. No se afirma
conformidad WCAG completa ni mejora de Core Web Vitals sin mediciones.

## Revisión del propietario

Valorar color, tipografía, claridad, orden, presencia del ejemplo, confianza y
experiencia móvil. Iterar en la misma rama. La incorporación al original requiere
aprobación visual, pruebas satisfactorias y una comparación contra el `main`
vigente que preserve cambios paralelos. Publicar requiere autorización separada.

## Revisión de exchanges (15/10/2026)

Selección manual a partir de las capturas agregadas aportadas por el propietario,
no a partir de fixtures: Binance, Bitvavo, Nexo, Coinbase, Kraken y Bitget.
El primer gráfico ordena por cantidad de informes generados correctamente;
el segundo ordena por media de filas CSV, solo con al menos cinco informes y
csv_rows registrado. El ancho de sus barras sigue siendo número de informes.
No se infieren cifras exactas de las barras ni un desempate estable entre
Coinbase y Kraken: la consulta de conteo no define un segundo criterio.

Se muestran seis tarjetas en orden de la primera captura: 3 columnas desktop,
2 tablet y 1 móvil. Bit2Me conserva su texto y enlace en un bloque secundario,
y se añade el acceso a todos los exchanges junto a esta sección. Bitget enlaza
a la herramienta existente /bitget (incluye instrucciones); no existe una guía
/exchanges/bitget en esta base. No se crea una ruta ni una consulta de producción.

## V6: revisión apple-design aplicada

Revisión documental de la skill original de Emil Kowalski:
https://github.com/emilkowalski/skills/blob/main/skills/apple-design/SKILL.md
(blob leído: adf68c517f2d7d2781587d619de07f4de286da57). No se instala la skill,
ninguna librería ni dependencia adicional. Se aplican feedback, claridad y
accesibilidad a la interfaz existente; sin animaciones físicas nuevas.

- Dos correcciones de texto autorizadas: el párrafo del PDF indica descarga
  desde la cuenta y el cierre de exchanges confirma compatibilidad antes de
  ofrecer ayuda. Se conservan los nombres Nexo, Crypto.com y Uphold. El test
  protege expresamente estas dos sustituciones y todo el resto del contenido.
- Tabla HTML nativa con caption y cinco encabezados scope=col; se conservan
  las 25 celdas de datos y el desplazamiento horizontal local. La captura usa
  siempre los mismos datos ficticios. Referencia: https://www.w3.org/WAI/tutorials/tables/.
- Estados de pulsación con color inmediato, sin movimiento ni cambio de tamaño;
  estilo explícito para el estado deshabilitado del formulario ya existente.
  No se modifica su envío, validación, endpoints ni script de autenticación.
- Las cuatro ventajas se leen después del ejemplo en el DOM y visualmente,
  sin duplicarlas u ocultarlas. El hero móvil tiene menos espacio antes del
  mensaje; el ejemplo se presenta antes. Se mantienen los anchos aprobados.
- La flecha de «Cómo funciona» apunta hacia abajo y conserva el enlace interno.

La prueba de navegador valida roles nativos de tabla, scroll con teclado,
feedback presionado sin seguir enlaces, aparición más temprana del ejemplo
móvil y conservación de los anchos de fiscalidad, FIFO y FAQ.
Pendientes Safari/iOS y lector de pantalla físico. La estructura semántica y
los roles comprobados no sustituyen esa validación manual.

## V7: composición visual para comparar con V6

Estado: cambios locales para revisión. No se han enviado a GitHub ni ejecutado
en CI. La PR #91 sigue apuntando a c3e23b07fb0d03ba9c4d327b5b41860688e73433 (V6).
Se observó una integración de Netlify que despliega automáticamente las
actualizaciones de esa PR. Se evita actualizar la rama para respetar la
restricción de no desplegar. No se cambia la configuración de la integración.

- Apertura en verde profundo, texto blanco y acento menta. CTA blanco en esta
  superficie; el verde de acción permanece en el resto de la página.
- Mensaje e informe en dos columnas por encima de 1200px, con lectura vertical
  por debajo. Mismo orden en HTML; ningún contenido se duplica ni se oculta.
- Informe blanco, KPIs en dos columnas en la apertura de escritorio y aviso
  visible del desplazamiento local de la tabla. Se conservan todos sus datos.
- Pasos con numeración de mayor tamaño; contenidos del informe agrupados en
  superficies blancas sobre gris claro. Exchanges sobre blanco con tarjetas
  suaves, nombres más destacados y la misma selección y orden.
- Ritmo de espaciado y tamaños de títulos revisados. Los contenedores de
  fiscalidad, FIFO y FAQ mantienen el ancho general aprobado, sin columnas de
  texto adicionales ni topes de ancho particulares.
- Misma tipografía de sistema, recursos locales, JS y script de autenticación.
  Sin cambios de contenido respecto de V6, incluidos textos SEO y legales.

Archivos de aplicación afectados respecto de V6: landing_apple.html y
landing_apple.css. Se amplía la comprobación ya existente en qa_home_apple.py
para verificar las columnas y su apilado; se actualiza este documento.

Entregables locales: Home_Apple_v7_composicion.html y
Comparador_Home_v6_v7.html. El comparador incrusta ambas versiones completas,
permite alternarlas a igual ancho y no necesita un servidor ni dependencias.
La vista offline simula solo la sesión anónima; no envía formularios.

Validación local: seis pruebas de preservación superadas; palabras visibles,
párrafos, enlaces y JSON-LD idénticos a V6; sintaxis de scripts comprobada con
node --check. Los cuatro pares de color principales de la apertura superan
4,5:1 mediante cálculo estático. No equivale a una auditoría WCAG completa.
La QA responsive en navegador, capturas V7, Safari/iOS y lector
de pantalla quedan pendientes; los resultados satisfactorios de V6 no validan
esta nueva composición. La V7 requiere esa verificación antes de incorporarse
al Home original.


## V8: revisión móvil aprobada (16/10/2026)

Estado: propuesta local, sin commit, actualización de PR, merge ni despliegue.
Se mantiene la restricción por el despliegue automático observado en Netlify.

Cambios respecto de V7:

- CTA de registro y de generación a todo el ancho del contenido hasta 640px,
  con texto centrado. Los márgenes laterales permanecen iguales.
- Cuatro ventajas intactas y enlace «Consultar exchanges compatibles →» en un
  único bloque. El texto anterior con nombres de exchanges se conserva dentro
  del apartado ampliable de exchanges, sin borrarlo ni duplicarlo.
- En móvil, Binance y Bitvavo visibles; Nexo, Coinbase, Kraken y Bitget en un
  details nativo. El bloque Bit2Me también pasa dentro de ese desplegable.
  Todo se incluye en el HTML inicial. La guía completa mantiene su enlace.
- En tablet/escritorio, JS coloca las cuatro tarjetas adicionales en la misma
  cuadrícula para conservar filas de 2/3 columnas. Se respeta su orden.
  Al volver a móvil se restauran al details; se evita dejar el foco dentro de
  contenido que va a cerrarse. Sin JS, el details permanece abierto y todas
  las guías siguen disponibles.
- FAQ: doce preguntas y todas las respuestas conservadas, cerradas inicialmente
  en acordeones nativos. No se reduce ni se reescribe su contenido.
- Cierre de soporte con fondo suave, borde lateral, pregunta destacada y enlace
  de contacto de al menos 44px de alto. Se conserva íntegro su párrafo.
- Entre exchanges y asistencia, padding móvil de 24px + 24px y sin margen
  inferior del párrafo de soporte: separación objetivo de 48px.

Única sustitución textual respecto de V7: los dos enlaces «Ver todos los
exchanges compatibles →» pasan a «Consultar exchanges compatibles →», tal como
aprobó el propietario. El test incorpora esta excepción explícita sin relajar
la conservación del resto de palabras, párrafos, enlaces o datos estructurados.

Archivos afectados en esta iteración:

- fiscal_app_export/static/landing_apple.html
- fiscal_app_export/static/landing_apple.css
- fiscal_app_export/static/landing_apple.js
- fiscal_app_export/tests/test_home_apple.py
- fiscal_app_export/tests/qa_home_apple.py
- docs/design/HOME_APPLE_PREVIEW_20261015.md

Validación local: seis contratos de conservación satisfactorios; sintaxis JS
comprobada; pruebas de estados, orden y foco del cambio de breakpoint mediante
un DOM simulado en Node (inicio móvil y escritorio, varios ciclos). Estas
simulaciones no sustituyen las pruebas en un navegador real. Se amplía la QA
existente para comprobar ancho de CTA, expansión por teclado, seis tarjetas en
pantallas amplias y alternativa sin JS, pero esa QA no se ha ejecutado en V8.

Entregables: Home_Apple_v8_movil.html y Comparador_Home_v7_v8.html. Los dos HTML
completos se incrustan en el comparador y se verifican byte a byte. API simulada
solo para sesión anónima; formularios sin envío. Continúan pendientes navegador,
capturas V8, Safari/iOS y lector de pantalla antes de incorporar al original.


## V9: espaciado móvil y retirada del bloque redundante (16/10/2026)

A partir de las tres capturas del propietario (00:39:17, 00:41:11 y 00:43:21):

- Hasta 640px, deja de mostrarse el bloque «¿Necesitas ayuda? Escríbenos» que
  precedía a «Asistencia especializada». Se conserva la tarjeta de asistencia.
  La retirada afecta a la vista móvil; el contenido permanece en HTML y se
  sigue mostrando en tablet/escritorio.
- Escala común móvil: 1,5rem arriba/abajo de cada sección (24px con raíz de
  16px), 1,25rem dentro de tarjetas (20px) y 1rem para separaciones internas
  compactas (16px). Dos secciones consecutivas suman 48px entre superficies
  de contenido, salvo sus bordes y márgenes internos específicos.
- Se compactan títulos, entradas de sección, pasos, tarjetas, equipo, textos
  editoriales y FAQ. Se conserva el espacio superior de la apertura necesario
  para la navegación fija, así como la geometría y controles de la tabla.
- Los tokens están en rem para acompañar el aumento de texto. No se reducen
  áreas de pulsación, se reordenan elementos o se modifica la autenticación.

Archivos modificados respecto de V8:

- fiscal_app_export/static/landing_apple.css (solo @media max-width:640px).
- docs/design/HOME_APPLE_PREVIEW_20261015.md (esta documentación).

Comprobado: seis contratos de preservación satisfactorios; HTML y JS idénticos
byte a byte a V8; todas las reglas CSS fuera del bloque móvil idénticas; hashes
originales de landing.html, nav.css y nav.js intactos. No se añaden pruebas ni
se ejecutan de nuevo simulaciones de JS porque no cambia su implementación.

Entregables locales: Home_Apple_v9_espaciado_movil.html y
Comparador_Home_v8_v9.html, con ambas versiones exactas incrustadas. El
comparador abre V9 a 390px (o al máximo disponible si la ventana es menor).
Pendiente de validación visual en navegador, Safari/iOS y lector de pantalla.
Sin actualización de rama/PR ni despliegue.


## V10: CTA sin promesa de informe gratuito (16/10/2026)

Aprobado por el propietario:

- «Genera tu informe gratis» pasa a «Preparar mi informe» en todos los anchos.
  Conserva /signup/ como destino y el registro como primer paso.
- «Cómo funciona ↓» deja de mostrarse en el hero hasta 640px. Su sección,
  ancla y enlace de navegación se conservan. Tablet/escritorio sin cambios.
- Se mantiene «Crea tu cuenta gratis». Las menciones «Gratis» en metadatos y
  el precio 0 del JSON-LD se dejan pendientes de la definición de la oferta,
  tal como se comunicó antes de aplicar esta iteración. No se presenta esta
  revisión como una actualización completa del modelo comercial.

Archivos afectados respecto de V9:

- fiscal_app_export/static/landing_apple.html
- fiscal_app_export/static/landing_apple.css
- fiscal_app_export/tests/test_home_apple.py
- fiscal_app_export/tests/qa_home_apple.py
- docs/design/HOME_APPLE_PREVIEW_20261015.md

Se incorpora una excepción textual específica al contrato de conservación;
los seis contratos pasan. El runner de navegador comprueba la nueva etiqueta
por su nombre accesible y la visibilidad del enlace según el ancho. Esta QA
real en navegador sigue pendiente, igual que en V9. No cambia JavaScript,
autenticación, pagos, rutas ni la Home original. Sin commit, actualización de
PR o despliegue.

Entregables: Home_Apple_v10_textos_CTA.html y Comparador_Home_v9_v10.html.


## V11: revisión de tablet (16/10/2026)

Capturas de referencia del propietario: 00:56:45, 00:59:15, 01:00:47 y 01:02:14.
Alcance: tablet de 641 a 1200px. Las reglas de móvil aprobadas permanecen
idénticas a V10 y no cambia JavaScript.

- Descripción inicial sin max-width de 56ch: ocupa el ancho de su contenedor.
- Se retira del hero de tablet «Cómo funciona ↓», manteniendo sección/ancla
  y navegación. En escritorio de más de 1200px el enlace sigue visible.
- La línea auxiliar añade «Datos para tu declaración», visible solo en tablet.
  Describe información para la declaración y no una presentación automática.
  Se mantiene el texto previo íntegro. Letra entre 13 y 14px a tamaño normal,
  sin max-width:54ch. No se fuerza nowrap ni se recorta: con ampliación de texto
  puede envolver para preservar la accesibilidad. El ajuste a una línea con
  tamaño normal requiere confirmación en navegador.
- Escala común tablet: 2rem de relleno vertical de sección (32px a raíz 16px),
  1,5rem dentro de tarjetas y 1,25rem en separaciones compactas. Reduce los
  grandes huecos heredados de escritorio, incluidos pasos, equipo, FAQ y
  contenidos editoriales. La apertura reserva 96px para cabecera y separación.
- «Preparar mi informe» tiene una franja blanca propia, centrada, del ancho de
  la cuadrícula, dentro de la sección del informe y próxima a las cuatro fichas.
  El wrapper es un bloque sin presentación adicional fuera de tablet; el
  botón mantiene /signup/ y las reglas móviles ya aprobadas.
- Se retira el bloque repetido de soporte en tablet. Se mantiene «Asistencia
  especializada» y el aviso de suspensión vigente. El soporte sigue en HTML
  para escritorio de más de 1200px, igual que antes.

Archivos afectados respecto de V10:

- fiscal_app_export/static/landing_apple.html
- fiscal_app_export/static/landing_apple.css
- fiscal_app_export/tests/test_home_apple.py
- fiscal_app_export/tests/qa_home_apple.py
- docs/design/HOME_APPLE_PREVIEW_20261015.md

Validación local: seis contratos de conservación superados; se incorpora solo
la adición aprobada al párrafo auxiliar. Reglas CSS del bloque móvil y JS
idénticos byte a byte a V10. Al retirar las dos adiciones HTML (span de tablet
 y wrapper de CTA), se recupera V10 byte a byte. La QA futura incluye el límite
641px (13 anchos), descripción al ancho disponible y línea auxiliar sin salto
con tamaño normal. Esa QA real de navegador no se ha ejecutado; las pruebas
V6 no certifican V11. Pendientes capturas reales, Safari/iOS y lector de pantalla.

Entregables: Home_Apple_v11_tablet.html y Comparador_Home_v10_v11.html,
comparador inicial a 768px con las dos versiones completas exactas incrustadas.
Sin cambios a la Home original, rama/PR, infraestructura, pagos o despliegues.


## V12: botones consistentes y ejercicio ficticio automático (16/10/2026)

A partir de las capturas 09:00:57 y 09:05:50 del propietario:

- Botones de acción con cápsula de 999px, verde #006b54, texto blanco centrado,
  altura mínima 48px y estados hover/pulsación coherentes. Se incluyen registro
  de header, registro del menú móvil/tablet, inicio de sesión en header, CTA de
  apertura, informe, asistencia y envío de formularios. Los controles de icono
  (abrir/cerrar menú o diálogo) conservan su tipo de control.
- Se elimina la variante blanca del CTA de apertura. Borde menta compartido para
  que el botón verde tenga un límite visible sobre el fondo verde profundo.
- No se sobrescribe display de los botones del header: las reglas compartidas
  siguen ocultándolos según breakpoint/estado de sesión. Menú en cápsula y
  centrado, con los mismos colores que los CTA de contenido.
- «Crear cuenta» sustituye a «Crea tu cuenta gratis» en apertura y alternativa
  sin JS. La variante cambia también el texto del botón generado del header;
  nav.js conserva su código y copia esa etiqueta al abrir su menú.
- La barra del ejemplo muestra «Informe FIFO de criptomonedas» como descripción
  del contenido, sin afirmar una mejora SEO ni un volumen de búsqueda medido.
- Cinco fechas de muestra pasan de 2024 a un respaldo HTML de 2025, con time y
  datetime coherentes. Al abrir la página, JS calcula año actual en Europe/Madrid
  menos uno y actualiza solo esas cinco fechas ficticias. En 2026 muestra 2025;
  en 2027 mostrará 2026. Sin JS permanece el respaldo de 2025. No cambian los
  años de ejemplos fiscales editoriales, las cantidades o los activos.

Archivos afectados respecto de V11:

- fiscal_app_export/static/landing_apple.html
- fiscal_app_export/static/landing_apple.css
- fiscal_app_export/static/landing_apple.js
- fiscal_app_export/tests/test_home_apple.py
- fiscal_app_export/tests/qa_home_apple.py
- docs/design/HOME_APPLE_PREVIEW_20261015.md

Validación: seis contratos pasan con excepciones explícitas de etiqueta/título
 y cinco fechas; todos los demás datos/párrafos, enlaces, JSON-LD y script de
 autenticación siguen protegidos. Simulación Node con el script real y reloj
 de 2026, 2027 y 2030, más cambio de año en Madrid: las cinco fechas y la etiqueta
 de registro actualizan correctamente. Sintaxis JS y hashes de archivos
 originales compartidos comprobados. La QA de navegador se amplía para etiqueta,
 forma/color del botón del menú y fechas, pero su ejecución real sigue pendiente.

Entregables: Home_Apple_v12_botones_informe.html y Comparador_Home_v11_v12.html,
comparador inicial en móvil a 390px. Revisión local sin commit, actualización de
PR ni despliegue. Pendientes navegador real, Safari/iOS y lector de pantalla.


## V13: espaciado de escritorio (16/10/2026)

Alcance solicitado: reducir y unificar los huecos antes y después de bloques
 en escritorio, siguiendo el sistema ya aplicado en móvil y tablet.

- Solo @media min-width:1201px. Secciones y ventajas con 2,5rem de padding
  arriba/abajo (40px a raíz 16px), sustituyendo el clamp de hasta 112px.
- 2rem para separación entre título y contenido y para interior de tarjetas
  amplias; 1,5rem en grupos y elementos compactos. Párrafos editoriales a 1rem.
- Se aplica a funcionamiento, informe, exchanges, asistencia, equipo, fiscalidad,
  FIFO, FAQ y cierre legal. Se conservan columnas, tipografía, color y controles.
- Apertura: 104px arriba para reservar navegación fija + 40px, y 40px abajo,
  frente a 136px/80px anteriores. Se mantiene el orden y la composición.
- Sin cambios de contenido, HTML o JS. Las fechas automáticas del ejemplo,
  etiquetas, destinos y estilos de botones de V12 permanecen.

Archivos afectados:

- fiscal_app_export/static/landing_apple.css (solo el bloque >1200px).
- docs/design/HOME_APPLE_PREVIEW_20261015.md.

Validación: seis contratos satisfactorios. Comparación byte a byte confirma
que el CSS fuera del bloque de escritorio y los archivos HTML/JS son idénticos
a V12. No se añaden pruebas de la simple escala de CSS. La comprobación visual
real en navegador sigue pendiente; no se usan resultados de V6 como validación
 de esta versión.

Entregables: Home_Apple_v13_espaciado_escritorio.html y
Comparador_Home_v12_v13.html; comparador inicial al ancho disponible para ver
escritorio cuando la ventana supera 1200px. Sin actualización de rama/PR,
merge ni despliegue.


## V14: jerarquía y diseño del header (16/10/2026)

Solicitud: el propietario rechaza las dos cápsulas de igual peso del header y
pide una solución profesional, con investigación de skills/herramientas.
Referencia visual: captura 09:46:28.

Fuentes revisadas:

- frontend-design original de Anthropic, lectura completa del SKILL.md desde
  https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md?plain=1
- Apple Human Interface Guidelines: Buttons,
  https://developer.apple.com/design/human-interface-guidelines/buttons
- apple-design original ya revisada en V6, de Emil Kowalski.

Seguridad/utilidad: el SKILL.md de frontend-design contiene pautas de diseño,
planificación y crítica; para esta intervención no requiere instalar paquetes
ni ejecutar código externo. Se usa como referencia documental, sin instalación.
No se descarga ni ejecuta su código. No se añaden plugins ni dependencias.
El acceso raw y Markdown falló; la lectura íntegra de la skill se obtuvo de la
vista de código de GitHub y Apple se contrastó mediante su resultado indexado.

Decisión de diseño: un único acceso destacado para registro. Paleta existente
#ffffff, #1d2428, #53616b, #006b54, #e1e6e3 y #edf3ef. Se mantiene la tipografía
de sistema. Tres áreas alineadas para marca, navegación y acceso; sin iconos
nuevos, rótulos adicionales ni animaciones. Se distingue la acción secundaria
por su tratamiento tipográfico. Es una excepción de jerarquía del header a la
uniformidad de botones pedida en V12, autorizada por la petición actual.

Implementación:

- «Iniciar sesión» pasa a enlace discreto: sin relleno ni borde permanente;
  hover subrayado y foco de teclado visible. Área de interacción mínima 44px.
- «Crear cuenta» es la única cápsula destacada del header, verde y más compacta:
  44px mínimo, tipografía de 14px y borde transparente sobre blanco.
- En escritorio, grid de tres áreas, separaciones consistentes y divisor tenue
  que agrupa los accesos. Mismas etiquetas, href, estados y acciones.
- Reglas dentro de .apple-home #site-nav. Se respetan display/hidden de nav.css:
  el botón de registro sigue en el menú hasta 1200px, y el acceso de sesión se
  oculta en la barra móvil según las reglas existentes. El CTA del menú móvil
  conserva la cápsula grande de V12 y los botones del cuerpo permanecen iguales.

Archivos afectados respecto de V13:

- fiscal_app_export/static/landing_apple.css (solo reglas de #site-nav).
- docs/design/HOME_APPLE_PREVIEW_20261015.md.

Validación: seis contratos satisfactorios. HTML/JS idénticos a V13; al retirar
las nuevas reglas del header se recupera el CSS anterior byte a byte. Se
preserva el script de autenticación y no cambia ningún recurso compartido.
Pendiente la comprobación visual real de alineación, estados por rol, teclado,
Safari/iOS y texto ampliado. No se afirma QA visual superada.

Entregables: Home_Apple_v14_header.html y Comparador_Header_v13_v14.html.
El comparador abre al ancho disponible. Revisión local; sin commit, PR,
publicación o despliegue.


## V15: retirada completa del bloque redundante y regresión (16/10/2026)

Captura de referencia: 09:53:52. Causa: el bloque «¿Necesitas ayuda? Escríbenos»
seguía en el HTML y se ocultaba únicamente hasta 1200px. En escritorio seguía
visible; V14 no lo había vuelto a insertar, pero la retirada previa era parcial.
La instrucción actual exige retirarlo de la variante completa.

- Se elimina el div apple-exchange-support y su único párrafo/enlace de contacto.
- Se retiran sus siete reglas CSS, incluidas las que solo lo ocultaban.
- Se mantiene «Asistencia especializada», su enlace, textos y aviso de suspensión.
- El acceso a Contacto permanece en la navegación. El resto del contenido,
  enlaces, FAQ, metadata, fechas automáticas y header V14 no se modifican.

Protección: nuevo contrato test_removed_support_block_does_not_return detecta
la clase, el texto antiguo/revisado y el cierre de soporte, y exige conservar
la asistencia principal. La eliminación de ese párrafo y su único enlace son
excepciones explícitas del contrato general; no se relaja la protección del
resto. El runner de navegador exige ausencia del bloque en todas las anchuras.
El helper local de exportación rechaza fuentes que vuelvan a incluirlo antes
de escribir una nueva vista previa.

Archivos afectados:

- fiscal_app_export/static/landing_apple.html
- fiscal_app_export/static/landing_apple.css
- fiscal_app_export/tests/test_home_apple.py
- fiscal_app_export/tests/qa_home_apple.py
- docs/design/HOME_APPLE_PREVIEW_20261015.md
- review-helpers/export_preview.py (helper local de revisión, no parte de la app).

Validación: siete contratos satisfactorios. Se probó la reintroducción en memoria
con su clase original y con clases renombradas: ambos casos fallan correctamente.
La exportación rechaza una fuente V14 con el bloque; el HTML V15 generado no lo
contiene y sí conserva asistencia. JavaScript y script de autenticación intactos.
QA real de navegador pendiente; la ausencia estructural es independiente del CSS.

Entregable limpio: Home_Apple_v15_sin_bloque_duplicado.html. No se genera un
comparador con una copia antigua del bloque. Versiones anteriores archivadas
no se reescriben. El archivo nuevo es la referencia vigente para revisión.
Sin actualización de rama/PR ni despliegue; no se modifica la Home en producción.


## V16: tabla del ejemplo completa en escritorio (16/10/2026)

Referencia: captura 09:55:53. Causa: la tabla conservaba min-width:36.875rem
(590px con raíz 16px), aunque el panel del ejemplo en la apertura a dos
columnas solo dispone de aproximadamente 515px interiores.

- Solo en escritorio >1200px, mínimo de tabla 31.25rem (500px a raíz 16px).
  Columnas Fecha/Activo/Tipo/Transmisión/G-P: 24/12/14/26/24 por ciento.
- Relleno horizontal de celdas de 16 a 8px, misma fuente de 14px a tamaño normal,
  cifras completas, fechas y encabezados. No se ocultan columnas ni datos.
- Se preserva el mínimo en rem: con aumento de texto, se permite scroll local
  cuando sea necesario para leer. Reglas de tabla móvil y tablet intactas.
- El aviso «Desliza...» se sincroniza con scrollWidth/clientWidth reales.
  ResizeObserver observa panel y tabla para cubrir ancho y tamaño de texto;
  fallback con resize. Sin JS el aviso permanece como ayuda estática.

Archivos afectados:

- fiscal_app_export/static/landing_apple.css
- fiscal_app_export/static/landing_apple.js
- fiscal_app_export/tests/qa_home_apple.py
- docs/design/HOME_APPLE_PREVIEW_20261015.md

Validación: siete contratos de conservación satisfactorios; HTML intacto.
Simulación Node del script real: aviso oculto cuando cabe, visible en panel
estrecho o con texto ampliado, y oculto al recuperar espacio, con observer y
fallback. No sustituye un navegador. La QA futura comprueba ausencia de scroll
 y última columna dentro del panel en todos los anchos de escritorio; pendiente
 ejecución y revisión visual real. Sigue activa la regresión del bloque retirado.

Entregable: Home_Apple_v16_tabla_escritorio.html. Revisión local, sin modificar
la PR, la Home original, infraestructura o proveedores; sin despliegue.

## V17: correcciones de la auditoría de cierre (16/10/2026)

Autorización del propietario: «procede con las mejoras identificadas». Se
conserva la composición visual V16 aprobada en móvil, tablet y escritorio.
La fuente anterior se preserva en `review-v16/source/` y coincide con los
SHA-256 del informe de auditoría. No se actualiza la PR #91: continúa vigente
la restricción por su integración de despliegue automático.

### Cambios aplicados

- H01: description, Open Graph y Twitter describen el informe sin prometer
  gratuidad. Se retira únicamente `offers` con precio 0 del JSON-LD de la app,
  conservando el resto del grafo. La oferta y el precio reales siguen por
  definir; sin oferta no se certifica elegibilidad para el resultado
  enriquecido SoftwareApplication de Google. No se inventan precios ni ratings.
- H02: se corrige exclusivamente el rango confirmado de la FAQ de Bitcoin
  y su respuesta JSON-LD: ejercicio 2025, territorio común, base liquidable del
  ahorro por tramos del 19 % al 30 %. AEAT publica las escalas estatal y
  autonómica de 2025 en los enlaces siguientes. No se alteran cálculos FIFO,
  informes, clasificaciones ni casillas. Los otros cinco puntos editoriales
  del informe siguen pendientes de validación de Rafa; no se dan por aprobados.
- H03: el rojo de «Cerrar sesión» se ajusta solo bajo `.apple-home #site-nav`.
  Contrastes calculados: 6,57:1 en blanco, 5,97:1 en hover y 5,43:1 pulsado.
- H04: nuevos retratos específicos de Home a 88, 176 y 264 px, WebP y PNG.
  `picture/srcset/sizes` permite elegir tamaño y formato; se conservan transparencia,
  proporción, lazy loading, textos alternativos y los originales de 512 px.
  La pareja WebP pesa 6.972/15.998/26.758 bytes a 1x/2x/3x de escritorio,
  frente a 837.405 bytes originales. A 2x supone un 98,09 % menos de bytes
  de retrato, no un porcentaje de mejora del rendimiento global de la página.
- H05: respaldo de presentación exclusivo de Home tras cuatro segundos de
  espera de `/api/me`. Añade enlaces públicos de login/registro en escritorio
  y menú móvil; no altera la petición, la sesión, sus roles ni controles.
  Cuando responde el script compartido, se retiran ambos respaldos y el
  observador, se cancela el temporizador y se conserva el foco. Se contempla
  la reconstrucción del menú y la llegada tardía de una sesión autenticada.
  `nav.js` y `nav.css` siguen intactos. No se modifica el ancho aprobado del
  header; el riesgo de CLS se mantiene como medición pendiente, no como
  una regresión demostrada ni una métrica resuelta.
- H06: caption con «Importes en euros» y nombre accesible «Ganancia o pérdida»
  para G/P. Las cinco columnas, anchos y datos del ejemplo permanecen.

Fuentes H02 verificadas en esta implementación:

- https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c15-calculo-impuesto-determinacion-cuotas-integras/gravamen-base-liquidable-ahorro/gravamen-estatal.html
- https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c15-calculo-impuesto-determinacion-cuotas-integras/gravamen-base-liquidable-ahorro/gravamen-autonomico.html

### Archivos afectados

- `fiscal_app_export/static/landing_apple.html`, `.css` y `.js`.
- Doce imágenes nuevas `fiscal_app_export/static/home-apple-{mariano,rafa}-{88,176,264}.{webp,png}`.
- `fiscal_app_export/tests/test_home_apple.py`: contratos originales conservados
  con excepciones explícitas para la corrección fiscal y la oferta retirada;
  nuevas comprobaciones de metadatos y activos responsive.
- `fiscal_app_export/tests/test_home_apple_session.js`: pruebas sintéticas Node
  de los scripts reales de Home y del renderizador compartido de sesión/menú.
- `fiscal_app_export/tests/qa_home_apple.py`: caption/nombre accesible actualizado,
  contraste renderizado de logout y cuatro casos futuros de sesión retenida.
- `review-helpers/export_preview.py`: incrusta WebP/PNG y srcsets; el comando
  por defecto genera V17 y ya no sobrescribe una vista de V6.
- Esta documentación; inventario de imágenes en `review-v17/portrait-assets.json`.

### Validación ejecutada

- Nueve contratos Python: PASS, incluida la ausencia del bloque retirado.
- Doce escenarios Node: PASS. Visitante, usuario, asesor y admin; respuestas
  rápidas/tardías, rechazo de red, espera de diez segundos simulada, menú
  reconstruido y recuperación de foco en escritorio/móvil. Usa DOM mínimo
  y reloj sintético, no un navegador ni cuentas reales. Verifica una única
  petición de sesión, sin peticiones añadidas por la variante.
- `node --check` de ambos scripts y sintaxis Python del runner/exportador: PASS.
- Inspección visual de los retratos WebP a 176 px. PNG idéntico al resize
  esperado y máscara alpha WebP idéntica al original redimensionado en los
  tres tamaños, mediante Pillow ya instalado.
- Hashes Git de `landing.html`, `nav.css`, `nav.js`: idénticos a la base.
- Vista offline: CSS/JS V17 coinciden con la fuente; navegación coincide tras
  la transformación documentada de enlaces a producción. Los doce derivados
  están incrustados y sus bytes coinciden. Vista genérica sincronizada.

El runner de navegador queda preparado con 25 escenarios, pero no se ejecuta:
no hay herramienta de navegador autorizada disponible y no se instala ninguna.
G01 sigue pendiente, igual que Safari/iOS, lector de pantalla, capturas V17 y
Core Web Vitals. Los resultados V6 no validan V17. La revisión fiscal integral
de Rafa sigue pendiente y es independiente de esta corrección confirmada.

Entregable: `Home_Apple_v17_cierre_auditoria.html` (722.769 bytes offline).
No se integra en la Home original ni se publica. No se crean commits, se
actualizan PR, se contacta con terceros ni se cambia infraestructura o servicios.

## V18: footer de marca y navegación (16/10/2026)

Autorización: «procede», después de la auditoría del footer y su propuesta
visual en escritorio, tablet y móvil. Se conserva V17 en
`review-v17/source/` y la vista V17 permanece disponible.

Se sustituye únicamente el footer de la variante por:

- Marca enlazada al inicio y descripción «Informes FIFO de criptomonedas».
- Navegación «Explorar»: Herramientas, Cómo funciona y Exchanges compatibles.
- Navegación «Ayuda»: Preguntas frecuentes, Contacto y Equipo.
- Franja inferior con el aviso fiscal íntegro, los cuatro enlaces legales
  originales y copyright de Mariano Sevilla.

Fondo blanco, tipografía y colores de Home; el mismo `.apple-container`
proporciona márgenes y ancho común. En escritorio, marca y dos grupos forman
tres columnas. Hasta 1.200 px, marca arriba y dos grupos debajo. En móvil,
políticas en dos columnas y enlaces de al menos 44 px; también 44 px con
puntero grueso en otros anchos. No se ocultan enlaces ni se añaden acordeones.
La marca admite reflujo al ampliar texto. No se fija la altura del footer.

Los únicos cambios de aplicación son `landing_apple.html`, `.css` y `.js`.
JavaScript solo añade la actualización del copyright al año actual de
Europe/Madrid, reutilizando el año calculado para el ejemplo. Fallback sin JS:
2026. No hay nuevas peticiones, activos, dependencias ni cambios de sesión.
Se retiran las reglas viejas de `.legal-bar`, incluidos sus overrides de
espaciado. El resto de los estilos aprobados se conserva.

Verificaciones ejecutadas:

- Nueve contratos Python PASS. El contrato de preservación comprueba ahora
  expresamente el aviso fiscal y todos los destinos del footer original.
- Doce escenarios sintéticos de sesión PASS.
- Cuatro simulaciones del script completo con fechas de 2026, 2027 y 2030,
  incluido el cambio de año en Madrid antes del cambio UTC: copyright actual
  y fechas ficticias del ejercicio anterior correctos.
- HTML fuera del footer idéntico a V17; única diferencia JS: año del copyright.
- Once enlaces de footer y tres navegaciones con nombre accesible. Todos los
  destinos existían en el snapshot de rutas revisado en la auditoría.
- Home original, nav.css y nav.js conservan sus hashes Git originales.
- Vista offline con footer idéntico al de aplicación, tras la transformación
  documentada de enlaces para revisión. CSS y JS propios incrustados coinciden
  con los de aplicación y la vista genérica está sincronizada.
- Bloque de ayuda retirado en V15 ausente; su regresión sigue pasando.

El runner futuro añade verificaciones del ancho común, estructura de columnas,
enlaces visibles y objetivos móviles de 44 px. Su sintaxis Python pasa, pero no
se ha ejecutado en navegador. Siguen pendientes navegador real, capturas V18,
Safari/iOS, zoom/lector de pantalla y métricas de rendimiento. No se presentan
las simulaciones como QA visual ni se atribuyen a V18 las capturas antiguas.

Entregable: `Home_Apple_v18_footer.html`. Sin commits, actualización de PR,
traslado a Home original ni despliegues. La variante mantiene noindex/nofollow.

## V19: ejemplo de informe sin cabecera exterior (16/10/2026)

Corrección solicitada sobre la captura aportada: se eliminan «Tu informe, de
un vistazo.» y «Ejemplo de informe · Datos ficticios» de todas las versiones.
Se elimina su contenedor y sus siete reglas CSS de base/breakpoints, de modo
que no queda su margen como hueco vacío. La sección mantiene un nombre
accesible mediante aria-label; el caption de la tabla conserva la indicación
de datos ficticios e importes en euros para lectores de pantalla. Se mantiene
el título interior del panel «Informe FIFO de criptomonedas».

Archivos afectados: landing_apple.html y landing_apple.css; exportador de
revisión actualizado a V19 y esta documentación. JavaScript no cambia.
V18 se preserva en review-v18/source/ y su vista previa sigue disponible.

Verificación: nueve contratos Python y doce escenarios sintéticos de sesión
PASS; comparación exacta del HTML confirma que solo cambia esa cabecera y su
etiquetado accesible. El footer V18, los datos de ejemplo y los originales
compartidos están intactos. La vista genérica está sincronizada con
`Home_Apple_v19_informe_sin_titulo.html`. Navegador real pendiente. Sin commits,
actualización de PR, incorporación a Home original ni despliegues.

## V20: revisión editorial fiscal (16/10/2026)

Se aplica la revisión autorizada tras contrastar la investigación aportada con
fuentes oficiales. Se conserva íntegramente el CSS y JavaScript de V19, cuya
fuente queda preservada en `review-v19/source/`. No cambia el diseño, las rutas,
los datos ficticios del panel, la autenticación ni el motor fiscal.

Cambios editoriales:

- Eliminadas las referencias fijas a las casillas 0033 y 1626.
- Diferenciadas la generación de rentas y la obligación de presentar el IRPF.
  Retirada la afirmación de que la obligación nació en 2019.
- FIFO explicado como criterio recogido por AEAT para unidades homogéneas,
  sin atribuir a cripto directamente el artículo 37.2 ni prometer que resuelve
  toda la fiscalidad. Ejemplo corregido: 0,5 BTC, precios expresados en €/BTC,
  coste de 15.000 €, venta de 20.000 € y ganancia de 5.000 €, sin comisiones.
- Recompensas: redacción condicionada al producto y sus condiciones, sin
  clasificación universal ni garantía de detección fiscal automática.
- Retirada la promesa no verificada de consolidación automática multiexchange;
  se explica la necesidad de revisar el historial global y las transferencias.
- Renta 2025: autoliquidación rectificativa con carácter general. Otros ejercicios
  requieren su procedimiento; no se promete una reducción de sanciones.
- Conservación de justificantes vinculada a la tenencia y a la prescripción de
  las declaraciones afectadas, no a cuatro años desde la compra.
- PDF como documento de apoyo, no anexo rutinario ni modelo oficial homologado.
- Las doce respuestas JSON-LD coinciden ahora con su texto visible. Se mantienen
  las doce preguntas, salvo la formulación autorizada de la pregunta sobre FIFO,
  los enlaces, canonical y noindex/nofollow. Se conserva el rango 2025 del 19–30 %
  para la base liquidable del ahorro en territorio común.

Fuentes oficiales contrastadas (consulta 16/10/2026):

- AEAT, compra y venta de monedas virtuales, Manual IRPF 2025:
  https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c11-ganancias-perdidas-patrimoniales/monedas-virtuales/compra-venta-monedas-virtuales-tributacion-inversor.html
- AEAT, modificación de declaración presentada, Renta 2025:
  https://sede.agenciatributaria.gob.es/Sede/ayuda/consultas-informaticas/renta-ayuda-tecnica/modificar-declaracion-presentada.html
- AEAT, delimitación de la obligación de declarar, Manual IRPF 2025:
  https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c01-campana-declaracion-renta/quienes-estan-obligados-presentar-declaracion-irpf/delimitacion-obligacion-declarar-irpf.html
- BOE, modelo 100 del ejercicio 2025:
  https://www.boe.es/boe/dias/2026/03/27/pdfs/BOE-A-2026-7041.pdf
- Ley General Tributaria, en especial artículos 27 y 70.3:
  https://www.boe.es/buscar/act.php?id=BOE-A-2003-23186

Las consultas DGT específicas de recompensas no se consideran verificadas en
texto íntegro: se mantiene formulación prudente y queda pendiente revisión con
Rafa por modalidad. Esta edición tampoco certifica capacidades del backend.

Verificación: 10 contratos Python y 12 escenarios sintéticos de sesión PASS.
El manifiesto `tests/home_apple_v20_copy.json` acota las excepciones editoriales;
el resto de contenido, enlaces y avisos legales continúa protegido. Se comprueba
la correspondencia exacta entre respuestas visibles y JSON-LD y la ausencia de
las afirmaciones retiradas. Los hashes Git del Home original, nav.css y nav.js
siguen siendo los originales. Vista genérica sincronizada con
`Home_Apple_v20_revision_fiscal.html`.

Pendiente revisión visual de los nuevos saltos de línea en navegador real; no
se han generado capturas ni métricas nuevas. Sin instalaciones, commits, PR,
traslado al Home original ni despliegue. Esta versión es editorial, no una
validación fiscal integral ni una auditoría funcional del cálculo.

## V21: cabecera móvil alternativa sin JavaScript (16/10/2026)

La captura del visor de archivos de iPhone muestra enlaces en varias filas y
ningún activador del menú. La fuente contiene una causa coherente con ese
resultado: el bloque noscript anterior imponía display:flex a los enlaces,
flex-wrap al contenedor y posición estática al header en todos los anchos.
Ese bloque ya existía en V19; no fue introducido por la revisión fiscal V20.
No se ha inspeccionado el visor del dispositivo para confirmar su ejecución.

Se sustituye exclusivamente el bloque noscript. Hasta 1200 px mantiene el
header fijo y compacto, con logo y un desplegable nativo details/summary de
44 px; contiene los cinco destinos públicos y acceso/registro. No depende de
JavaScript, no añade un botón inoperante y no fuerza atributos ARIA de estado
que quedarían desactualizados. Panel con scroll limitado al viewport. La
alternativa desktop conserva su comportamiento previo; con JavaScript activo
el menú compartido, los estados de sesión y los permisos siguen intactos.

Archivos afectados: landing_apple.html (solo noscript), test_home_apple.py,
review-helpers/export_preview.py y este registro. CSS y JS externos idénticos
a V20/V19, textos fiscales V20 y resto del HTML byte a byte intactos. V20
preservada en review-v20/source/ y su vista previa numerada no se sobrescribe.

Verificación local: 11 contratos Python y 12 escenarios sintéticos PASS.
Nueva regresión limita la modificación a noscript y comprueba que la alternativa
incluye desplegable nativo cerrado, destinos correctos y objetivo de 44 px.
Los originales compartidos conservan sus hashes. Sin navegador real disponible:
pendiente comprobar el resultado en el visor iPhone de la captura y en Safari,
con y sin JavaScript. No se presentan estas pruebas como QA visual.

Entregable: Home_Apple_v21_header_movil.html; vista genérica sincronizada.
Sin instalación, cambios en navegación compartida, commits, PR ni despliegue.

## V22: adaptador de cabecera para el archivo de revisión (16/10/2026)

La segunda captura de iPhone confirma que V21 sigue sin mostrar el activador
y presenta un hueco superior. La solución anterior no valida el visor real.
No se afirma conocer su política exacta de scripts, noscript o posicionamiento.

Se modifica únicamente el exportador de revisión: el archivo offline recibe
una cabecera pública con details/summary nativo directamente en el HTML,
fuera de noscript, y un icono SVG explícito. La cabecera participa del flujo
normal (sin posición fija) y el enlace de salto se oculta de forma accesible,
sin depender de una traslación de un elemento fijo. El espacio superior del
hero descuenta los 64 px que ya aporta la cabecera en el flujo. El menú incluye
los cinco enlaces de la fuente y acceso/registro; objetivo de 44 px, panel
con scroll y botón de registro verde y redondeado. No se hidrata ese header
offline mediante nav.js, para evitar duplicados o dependencia de /api/me.

Es una adaptación explícita de la vista previa, no una prueba del comportamiento
de la navegación de producción. El resto de mejoras JS sigue incrustado.
La fuente de aplicación, su autenticación, CSS/JS compartidos y todos los textos
fiscales quedan intactos. V21 sigue disponible sin sobrescritura.

Archivos afectados: review-helpers/export_preview.py, nuevo contrato
tests/test_home_apple_preview.py, este registro y los archivos exportados.
Verificación: 13 contratos Python y 12 escenarios sintéticos PASS. Se exige
identidad del main, JSON-LD y del resto de la fuente fuera del adaptador.
Vista genérica idéntica a Home_Apple_v22_header_vista_previa.html. Hashes
originales preservados. Pendiente validación visual en el visor iPhone;
no se dispone de navegador real ni se presentan capturas nuevas.
Sin instalaciones, commits, PR, modificación de Home original ni despliegue.

## V23: inicio del documento de revisión sin reserva superior (16/10/2026)

La captura V22 confirma menú visible pero un espacio blanco anterior a su fila.
Sin acceso al motor del visor no se atribuye a una causa única comprobada.
Se normalizan explícitamente margen y padding de html/body a cero en el archivo
offline y margen/padding del nav; la fila conserva mínimo de 64 px y 8 px de
padding vertical. El header es el primer elemento del body; el enlace accesible
de salto se conserva inmediatamente después para que una reinterpretación de
su posicionamiento no reserve espacio antes de la cabecera. No se utilizan
desplazamientos negativos para compensar un hueco de origen no confirmado.

Cambian solo el exportador, su contrato y este registro, además de la nueva
vista Home_Apple_v23_header_sin_hueco.html y la vista genérica sincronizada.
Fuente de aplicación, contenido principal y textos fiscales sin cambios.
13 contratos locales PASS; comprobación visual en el visor del usuario pendiente.
Los márgenes que imponga el propio visor fuera del documento no pueden
controlarse con este CSS. Sin cambios en producción ni despliegues.

## Publicación autorizada de la vista de pruebas (16/10/2026, noche)

El propietario solicita localizar la URL existente y actualizarla. Se verifica
la PR #91 y el bot de Netlify: deploy-preview-91--fiscal-cripto.netlify.app.
Se añade home-apple-preview.html en la rama design/home-apple-preview-20261015,
como copia exacta del artefacto V23, junto con su nota de alcance. Commit:
84db7bb7f6697350c6346858d186252328fd8713. Solo dos archivos añadidos; ningún
archivo preexistente modificado. La portada index.html, variante fuente V6
remota y todos los archivos de aplicación permanecen como estaban en la rama.

URL actualizada: https://deploy-preview-91--fiscal-cripto.netlify.app/home-apple-preview.html

Netlify devuelve estado success / Deploy Preview ready, despliegue
6ad28dc1ff2cbe081aa65b28. HTTP 200; diferencia respecto al artefacto local:
una inserción de 221 caracteres del propio Netlify antes de cerrar body.
No se confunde la publicación estática con una validación de Flask/sesiones.
Pendiente revisión del propietario en Safari móvil y tablet. Sin merge,
actualización de main, Railway, bases de datos, variables ni servicios de pago.

## V24: sincronización de fuentes y navegación compartida (16/10/2026, noche)

El propietario confirma la vista de Netlify en móvil y tablet, además del
escritorio, y autoriza continuar con la sincronización y validación funcional.
Se actualiza exclusivamente la rama de diseño de PR #91, cuya fuente era V6.
La URL de la V23 aprobada se conserva como referencia visual sin sobrescribirla.

Se sincronizan landing_apple.html/.css/.js, retratos locales WebP/PNG, contratos,
fixtures de versiones anteriores y QA de navegador. El exportador incorpora
un modo adicional con nav.js real en vez del menú nativo usado en el artefacto
V23. Nuevo artefacto estático: home-apple-functional-preview.html. Simula solo
visitante y bloquea llamadas de escritura; no valida sesiones reales del servidor.

La cabecera de aplicación adopta la geometría aprobada en flujo normal, fondo
blanco y padding superior del hero de 40/32/36 px según el breakpoint. Se oculta
el acceso de texto de tablet como en V23; el menú sigue incluyendo acceso y
registro, y conserva las acciones según el rol de la sesión. Se mantiene el
avatar autenticado. La alternativa móvil sin JS usa details nativo y deja de
fijarse al viewport para acompañar al header al hacer scroll.

No cambia nav.js, nav.css, el script de autenticación, la Home original, rutas,
Flask, permisos, FIFO, servicios de pago ni datos. No se fusiona la PR ni se
actualiza main o Railway. La integración sobre main vigente queda pendiente
de un paso posterior que preserve trabajo paralelo.

Verificación local previa al CI: 13 contratos Python y 12 escenarios sintéticos
PASS. QA de navegador actualizada para geometría de header, 13 anchuras,
estados de visitante/usuario/asesor/admin, respuesta de sesión tardía y menú
nativo sin JS en móvil/tablet. Su resultado no se presume antes del CI.
