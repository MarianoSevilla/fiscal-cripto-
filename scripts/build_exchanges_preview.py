from pathlib import Path
from html import escape
import json,re

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'fiscal_app_export/static'
OUT=ROOT/'fiscal_app_export/static'; OUT.mkdir(parents=True,exist_ok=True)
home=(BASE/'landing.html').read_text()
header=home.split('<body class="apple-home">',1)[1].split('<main ',1)[0]
header=header.replace('<nav id="site-nav">','<nav id="site-nav" aria-label="Principal">')
footer=re.search(r'<footer class="apple-footer".*?</footer>',home,re.S)[0]
footer=footer.replace('href="/exchanges"','href="/exchanges" aria-current="page"')

# One inventory supplies both the visible catalogue and structured list.
# Four platforms have a tool route but no public exchange guide.
EXCHANGES=[
 ('Binance','CSV · Historial de transacciones.','/exchanges/binance','Ver guía'),
 ('Bitvavo','CSV · Historial de operaciones.','/exchanges/bitvavo','Ver guía'),
 ('Kraken','CSV · Historial Ledger.','/exchanges/kraken','Ver guía'),
 ('Coinbase','CSV · Historial de transacciones.','/exchanges/coinbase','Ver guía'),
 ('Bit2Me','CSV · Consulta el formato admitido.','/exchanges/bit2me','Ver guía'),
 ('Nexo','CSV · Historial de transacciones.','/exchanges/nexo','Ver guía'),
 ('Crypto.com','CSV · Historial de la App.','/exchanges/cryptocom','Ver guía'),
 ('Bitget','CSV · Operaciones spot y movimientos.','/bitget','Acceder a herramienta'),
 ('KuCoin','CSV · Varios historiales de tu cuenta.','/kucoin','Acceder a herramienta'),
 ('MEXC','Excel · Historial en XLS o XLSX.','/mexc','Acceder a herramienta'),
 ('Uphold','CSV · Historial de transacciones.','/uphold','Acceder a herramienta'),
]
cards='\n'.join('<a class="apple-exchange-card" href="'+url+'"><h3>'+escape(name)+'</h3><p>'+escape(desc)+'</p><span>'+action+' <span aria-hidden="true">→</span></span></a>' for name,desc,url,action in EXCHANGES)
AEAT='https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c11-ganancias-perdidas-patrimoniales/monedas-virtuales/compra-venta-monedas-virtuales-tributacion-inversor.html'
FAQS=[
 ('¿Qué archivo necesito y cómo lo exporto?', '<p>Consulta el formato de tu exchange antes de empezar: no todos los CSV contienen la misma información. Las siete guías del catálogo son públicas; las otras cuatro opciones abren la herramienta correspondiente, que requiere iniciar sesión y muestra las instrucciones.</p><p>MEXC utiliza Excel en formato XLS o XLSX, no CSV. Crypto.com utiliza el historial de la App; esta compatibilidad no equivale a unificar los archivos de la App y de Crypto.com Exchange. En Bit2Me, utiliza el formato que ofrezca la herramienta: no conviertas un Excel a CSV por tu cuenta.</p>'),
 ('¿Necesito todo el historial o solo el año que declaro?', '<p>Necesitas también las adquisiciones de años anteriores que permitan determinar el coste de las unidades transmitidas. Exporta el historial desde el inicio y comprueba las fechas que incluye cada archivo. Si tu exchange limita el período de exportación, sigue su guía para preparar los datos sin perder operaciones ni duplicarlas.</p><p>No elimines las compras antiguas solo porque no pertenecen al ejercicio que quieres revisar. <a href="/metodo-fifo-criptomonedas">Consultar cómo se aplica FIFO →</a></p>'),
 ('¿Puedo unir varios exchanges en un único informe?', '<p>Actualmente el análisis se realiza por exchange. Los informes separados no equivalen a un FIFO global consolidado de todas tus plataformas y carteras. Si has movido una misma criptomoneda entre ellas, hay que revisar el historial conjunto y los costes de adquisición antes de preparar la declaración.</p><p>Subir varios archivos de KuCoin o Bitget permite incorporar distintos historiales de esa misma plataforma; no mezcla exchanges diferentes. Si necesitas revisar el conjunto, <a href="/pedir-asesoramiento">solicita asesoramiento fiscal</a>.</p>'),
 ('¿Cómo funcionan los varios archivos de Bitget y KuCoin?', '<p>En Bitget, el historial de operaciones spot es el archivo principal; puedes añadir el historial de depósitos y retiros. En KuCoin, aporta los historiales que correspondan a tu actividad: cuenta de trading, cuenta de financiación, órdenes fiat y depósitos. Sigue las indicaciones del formulario para comprobar qué archivos ha reconocido.</p><p>Estos flujos son específicos de cada plataforma. No adjuntes historiales de otros exchanges ni des por incluida una operación solo por haber subido un archivo.</p>'),
 ('¿Qué ocurre si me falta historial o el archivo da un error?', '<p>Un historial incompleto puede dejar adquisiciones sin identificar o costes pendientes de verificar. Revisa los avisos y completa la documentación antes de utilizar el resultado para tu declaración.</p><p>Si el archivo se rechaza, comprueba el exchange, el tipo de exportación y el formato. Puedes <a href="/contacto">explicarnos la incidencia</a> sin enviar inicialmente tu documentación fiscal. Cualquier entrega posterior de un archivo para su estudio será una decisión tuya.</p>'),
 ('¿Se incluyen staking, intereses, préstamos y otras recompensas?', '<p>La compatibilidad con una plataforma no significa que todos sus productos estén cubiertos. Las operaciones reconocidas dependen del formato y del historial importado. Revisa los avisos y no presupongas cobertura completa de margin, derivados, préstamos o productos Earn.</p><p>Los intereses, las permutas, el staking, los airdrops y el cashback no comparten necesariamente tratamiento fiscal. Su naturaleza, valoración e imputación deben revisarse según el caso; no existe una única casilla válida para todos. <a href="/faq">Consultar las preguntas fiscales →</a></p>'),
 ('¿El informe presenta mi declaración ante Hacienda?', '<p>No. El informe organiza las operaciones importadas y sus cálculos para ayudarte a preparar la información de tu declaración. Debes comprobar que los datos estén completos, revisar las advertencias y confirmar el tratamiento fiscal aplicable. La generación automática no incluye una revisión profesional individual ni presenta tu declaración ante la Agencia Tributaria.</p><p>El servicio profesional de Rafael Ramos, economista colegiado, se solicita y contrata por separado, directamente con él. <a href="/como-funciona">Conocer el alcance de la herramienta →</a></p>'),
 ('¿Qué criterio fiscal se utiliza para las ventas y permutas?', '<p>Para particulares en territorio común, fuera de una actividad económica, la AEAT recoge el criterio FIFO para identificar las unidades transmitidas de una misma criptomoneda homogénea: se consideran transmitidas primero las adquiridas antes. Las ventas y permutas pueden generar ganancias o pérdidas patrimoniales.</p><p>El cálculo realizado sobre un historial importado no acredita por sí solo que se haya incluido toda tu actividad. <a href="'+AEAT+'">Consultar el criterio de la Agencia Tributaria →</a></p>'),
 ('¿Mi exchange informa a Hacienda? ¿Tengo que presentar el Modelo 721?', '<p>Las obligaciones de información dependen de la entidad que presta el servicio, su actividad y la normativa aplicable. Los modelos 172 y 173 no se exigen por igual a todos los exchanges. DAC8 amplía el intercambio de información: distingue los datos recopilados desde 2026 de su primer ciclo de comunicación en 2027.</p><p>El Modelo 721 es una obligación distinta del IRPF y depende, entre otros requisitos, de la custodia en el extranjero y de los importes y circunstancias aplicables. El nombre comercial o un registro del exchange no permiten asegurar por sí solos una exención. <a href="/modelo-721-criptomonedas">Consultar la guía del Modelo 721 →</a></p>'),
 ('¿Cómo comparo esta herramienta con otras soluciones fiscales?', '<p>Comprueba en cada solución los formatos y operaciones admitidos, el alcance de la consolidación entre plataformas, las advertencias de valoración y si incluye revisión profesional. Son prestaciones distintas; no deben darse por supuestas por el hecho de generar un PDF.</p><p>En esta herramienta, el análisis se realiza por exchange y el asesoramiento profesional se contrata por separado. <a href="/terminos">Consultar las condiciones del servicio →</a></p>'),
 ('¿Qué hago si mi exchange no aparece?', '<p>El catálogo reúne las 11 plataformas con integración disponible en la herramienta. Si no encuentras la tuya, <a href="/contacto">indícanos qué exchange y qué tipo de historial utilizas</a>. No es necesario adjuntar datos fiscales para hacer la consulta. Estudiaremos la petición, sin garantizar una fecha de incorporación.</p>'),
]
faq='\n'.join('<details class="apple-faq-item"><summary>'+q+'</summary><div class="apple-faq-answer">'+a+'</div></details>' for q,a in FAQS)
description='Consulta los exchanges y formatos compatibles con el informe FIFO. Encuentra cómo exportar tu historial y revisa qué datos necesitas antes de empezar.'
schema={'@context':'https://schema.org','@type':'CollectionPage','@id':'https://marianosevilla.com/exchanges','url':'https://marianosevilla.com/exchanges','name':'Exchanges compatibles con el informe FIFO','description':description,'inLanguage':'es','isPartOf':{'@id':'https://marianosevilla.com/#website'},'mainEntity':{'@type':'ItemList','numberOfItems':len(EXCHANGES),'itemListElement':[dict({'@type':'ListItem','position':i,'name':row[0]},**({'url':'https://marianosevilla.com'+row[2]} if row[2].startswith('/exchanges/') else {})) for i,row in enumerate(EXCHANGES,1)]}}
head='''<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Exchanges compatibles con el informe FIFO | Mariano Sevilla</title>
<meta name="description" content="'''+description+'''">
<meta name="robots" content="noindex, nofollow"><link rel="canonical" href="https://marianosevilla.com/exchanges"><link rel="icon" href="/static/favicon.ico">
<meta property="og:type" content="website"><meta property="og:url" content="https://marianosevilla.com/exchanges"><meta property="og:title" content="Exchanges compatibles con el informe FIFO | Mariano Sevilla"><meta property="og:description" content="'''+description+'''"><meta property="og:image" content="https://marianosevilla.com/static/og-image.png"><meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="/static/nav.css"><link rel="stylesheet" href="/static/landing_apple.css"><link rel="stylesheet" href="/static/exchanges_apple.css">
<script src="/static/landing_apple.js" defer></script>
<script type="application/ld+json">'''+json.dumps(schema,ensure_ascii=False)+'''</script></head><body class="apple-home apple-exchanges-page">'''
main='''<main id="contenido" tabindex="-1">
<section class="apple-intro exchanges-intro" aria-labelledby="exchanges-title"><div class="apple-container">
<p class="apple-eyebrow">Informe FIFO de criptomonedas</p>
<h1 id="exchanges-title">Exchanges compatibles con <em>tu informe FIFO.</em></h1>
<p class="exchanges-lead">Encuentra tu exchange, consulta el formato admitido y prepara tu historial antes de generar el informe.</p>
<a class="apple-button" href="/signup/">Crear cuenta</a>
</div></section>
<section class="exchanges-section exchanges-catalogue" aria-labelledby="catalogue-title"><div class="apple-container">
<div class="exchanges-heading"><h2 id="catalogue-title">Encuentra tu exchange.</h2><p>11 plataformas. El formato adecuado para cada historial.</p></div>
<div class="apple-catalog-grid" aria-label="Exchanges compatibles">'''+cards+'''</div>
<p class="exchanges-note">Las guías se consultan sin cuenta. Para acceder a una herramienta e importar archivos necesitas iniciar sesión. La compatibilidad depende del formato y de las operaciones incluidas.</p>
</div></section>
<section class="exchanges-section exchanges-preparation" aria-labelledby="preparation-title"><div class="apple-container">
<div class="exchanges-heading"><h2 id="preparation-title">Un buen cálculo empieza por tu historial.</h2><p>Prepara los datos antes de importar tus archivos.</p></div>
<ol class="exchanges-steps">
<li><h3>Recupera el historial completo.</h3><p>Incluye las compras de años anteriores que necesitas para identificar el coste de tus ventas y permutas.</p></li>
<li><h3>Usa la exportación correcta.</h3><p>Sigue las instrucciones de tu plataforma. Conserva el archivo original y no lo conviertas a otro formato.</p></li>
<li><h3>Revisa el resultado y los avisos.</h3><p>Comprueba las operaciones reconocidas, los datos que faltan y las valoraciones antes de preparar tu declaración.</p></li>
</ol>
<aside class="exchanges-scope" aria-labelledby="scope-title"><h3 id="scope-title">¿Operas en varias plataformas?</h3><p>El análisis se realiza por exchange. Los informes separados no equivalen a un FIFO global consolidado. Si has transferido criptomonedas entre plataformas o carteras, revisa el historial conjunto y los costes de adquisición.</p><a class="apple-text-link" href="/como-funciona">Conocer el alcance del informe <span aria-hidden="true">→</span></a></aside>
</div></section>
<section class="exchanges-section exchanges-faq" aria-labelledby="faq-title"><div class="apple-container">
<div class="exchanges-heading"><h2 id="faq-title">Antes de importar, resuelve tus dudas.</h2><p>Archivos, compatibilidad y alcance del informe fiscal.</p></div>
<div class="apple-faq-list">'''+faq+'''</div>
</div></section>
<section class="exchanges-section exchanges-help" aria-labelledby="help-title"><div class="apple-container">
<div class="asistencia-block"><p class="apple-eyebrow">Asesoramiento fiscal de criptomonedas</p>
<h2 id="help-title">¿Tu historial necesita una revisión profesional?</h2>
<p>Si utilizas varias plataformas o tienes operaciones complejas, solicita una valoración a Rafael Ramos, economista colegiado. El servicio profesional se contrata directamente con él.</p>
<ul class="asistencia-bullets"><li>Historial en varios exchanges</li><li>Transferencias y datos incompletos</li><li>Operaciones que requieren revisión</li></ul>
<a class="apple-button" href="/pedir-asesoramiento">Solicitar asesoramiento fiscal</a>
</div></div></section>
</main>'''
html=head+header+main+footer+'</body></html>'
(OUT/'exchanges_apple.html').write_text(html)
viewer=html
for name in ['nav.css','landing_apple.css','exchanges_apple.css']:
 path=(OUT if name=='exchanges_apple.css' else BASE)/name
 viewer=viewer.replace(f'<link rel="stylesheet" href="/static/{name}">','<style>'+path.read_text()+'</style>')
for name in ['nav.js','landing_apple.js']:
 script=(BASE/name).read_text()
 if name=='nav.js':
  assert "fetch('/api/me'" in script
  script=script.replace("fetch('/api/me'","fetch('/exchanges-apple-preview/session.json'")
 script=script.replace('</script','<\\/script')
 tag=f'<script src="/static/{name}"'+(' defer' if name!='nav.js' else '')+'></script>'
 if name=='nav.js': viewer=viewer.replace(tag,'<script>'+script+'</script>')
 else: viewer=viewer.replace(tag,'').replace('</body>','<script>'+script+'</script></body>')
viewer=re.sub(r'href="(/(?!/)[^"]*)"',lambda m:'href="https://marianosevilla.com'+m[1]+'"',viewer)
v=ROOT/'exchanges-apple-preview';v.mkdir(exist_ok=True)
(v/'index.html').write_text(viewer)
(v/'session.json').write_text('{"user":null}\n')
print('Built source and isolated viewer; no production API requests or analysis actions.')
