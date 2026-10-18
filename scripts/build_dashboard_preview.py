"""Build a protected workspace variant and an inert, synthetic public viewer.

Never overwrites static/dashboard.html or changes either fiscal engine.
"""
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'fiscal_app_export/static'
TEMPLATES=ROOT/'fiscal_app_export/templates'
OUT=ROOT/'dashboard-apple-preview'
EXCHANGES=[
 ('binance','Binance','binance.jpg','Historial de transacciones de Binance.'),
 ('bit2me','Bit2Me','bit2me.jpg','CSV del Informe Fiscal de Bit2Me.'),
 ('bitget','Bitget','bitget.png','Archivos de operaciones de Bitget.'),
 ('bitvavo','Bitvavo','bitvavo.png','Historial completo de operaciones de Bitvavo.'),
 ('coinbase','Coinbase','coinbase.png','Historial de transacciones de Coinbase.'),
 ('cryptocom','Crypto.com','crypto.png','Historial de operaciones de Crypto.com.'),
 ('kraken','Kraken','kraken.png','Historial de movimientos de Kraken.'),
 ('kucoin','KuCoin','kucoin.png','Archivos CSV exportados desde KuCoin.'),
 ('mexc','MEXC','mexc.png','Archivo Excel original, en formato XLS o XLSX.'),
 ('nexo','Nexo','nexo.jpg','Historial de transacciones de Nexo.'),
 ('uphold','Uphold','uphold.png','Historial de actividad de Uphold.'),
]
PRIVATE={'/dashboard','/dashboard-apple-preview','/modelo721','/account','/stats','/pricing',
 '/admin/asesoramiento','/admin/comunicaciones','/admin/recursos','/admin/contactos',
 '/mis-solicitudes-fiscales','/pedir-asesoramiento','/login','/signup',
 *('/'+e[0] for e in EXCHANGES)}

def card(title,description,caption,href):
 return f'<a class="apple-exchange-card" href="{href}"><h3>{title}</h3><p>{description}</p><span>{caption}</span></a>'

def make():
 home=(STATIC/'landing.html').read_text()
 nav=re.search(r'<nav id="site-nav".*?</nav>',home,re.S).group(0)
 footer=re.search(r'<footer class="apple-footer">.*?</footer>',home,re.S).group(0)
 cards='\n'.join(f'''<a class="apple-exchange-card" data-exchange-name="{name}" href="/{slug}">
<div class="dash-card-heading"><img class="dash-logo" src="/static/images/{image}" alt="" width="44" height="44"><h3>{name}</h3></div>
<p>{description}</p><span>Preparar informe</span></a>''' for slug,name,image,description in EXCHANGES)
 primary=card('Informe FIFO','Prepara el cálculo y el detalle de tus operaciones para revisar tu declaración de la renta.','Elegir mi exchange','#fifo')+card('Modelo 721','Revisa tus saldos en el extranjero y prepara el borrador XML cuando completes los datos necesarios.','Preparar Modelo 721','/modelo721')
 support=card('Mi cuenta','Revisa tu nombre, tus datos de cuenta y las opciones de acceso.','Abrir mi cuenta','/account')+card('Guías y recursos','Consulta la documentación de apoyo para organizar tus operaciones y entender tus informes.','Consultar recursos','/recursos')+card('Asesoramiento fiscal','Envía tu consulta para que el asesor pueda revisar tu caso. Presupuestos y pagos temporalmente suspendidos.','Enviar consulta','/pedir-asesoramiento')
 return f'''<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mi espacio fiscal | Mariano Sevilla</title><meta name="robots" content="noindex, nofollow"><link rel="canonical" href="https://marianosevilla.com/dashboard"><link rel="icon" href="/static/favicon.ico">
<link rel="stylesheet" href="/static/nav.css"><link rel="stylesheet" href="/static/landing_apple.css"><link rel="stylesheet" href="/static/dashboard_apple.css">
<script src="/static/landing_apple.js" defer></script><script src="/static/dashboard_apple.js" defer></script></head>
<body class="apple-home apple-dashboard" data-dashboard-state="loading"><a class="apple-skip" href="#contenido">Saltar al contenido</a>
{nav}<script src="/static/nav.js"></script>
<main id="contenido" tabindex="-1">
<section class="dash-intro" aria-labelledby="dashTitle"><div class="apple-container"><p class="apple-eyebrow">Tu área de trabajo</p><h1 id="dashTitle">Mi espacio fiscal</h1><p class="dash-lead">Prepara tus informes y reúne la información para revisar tu fiscalidad.</p></div></section>
<section id="dashAccess" class="dash-access" aria-labelledby="dashAccessTitle"><div class="apple-container"><div role="status" aria-live="polite"><h2 id="dashAccessTitle">Comprobando tu sesión</h2><p id="dashAccessDescription">Tus herramientas aparecerán en cuanto confirmemos el acceso.</p></div><button class="apple-button" id="dashRetry" type="button" hidden>Volver a comprobar</button><a class="apple-button" id="dashResume" href="/login/?next=%2Fdashboard" hidden>Iniciar sesión</a></div></section>
<div id="dashWorkspace" hidden>
<section class="dash-section" aria-labelledby="dashTasksTitle"><div class="apple-container"><div class="dash-heading"><h2 id="dashTasksTitle">¿Qué necesitas preparar?</h2><p>Elige la herramienta adecuada para tu tarea.</p></div><div class="apple-catalog-grid dash-primary-grid">{primary}</div></div></section>
<section class="dash-section" id="fifo" tabindex="-1" aria-labelledby="dashFifoTitle"><div class="apple-container"><div class="dash-heading"><div class="dash-heading-row"><h2 id="dashFifoTitle">Tu informe FIFO, por exchange</h2><p id="dashCount" class="dash-count" role="status" aria-live="polite">11 exchanges disponibles</p></div><p>Abre tu exchange y sigue sus instrucciones para importar el historial completo.</p></div>
<div class="dash-search" id="dashSearchWrap" hidden><label for="dashSearch">Busca tu exchange</label><div class="dash-search-controls"><input id="dashSearch" type="search" placeholder="Por ejemplo, Bitvavo" autocomplete="off" spellcheck="false" aria-controls="dashExchanges" maxlength="100"><button class="dash-text-button" id="dashSearchClear" type="button" hidden>Limpiar</button></div></div>
<div class="apple-catalog-grid" id="dashExchanges">{cards}</div>
<p class="dash-empty" id="dashEmpty" hidden>No encontramos ese exchange. Prueba con otro nombre o <a href="/exchanges">consulta los exchanges compatibles</a>.</p>
<p class="dash-note">Utiliza los archivos originales. El cálculo depende del historial que aportes; si operas en varios exchanges, revisa el conjunto de tus operaciones. <a href="/como-funciona">Cómo preparar tus archivos</a></p>
</div></section>
<section class="dash-section" aria-labelledby="dashMoreTitle"><div class="apple-container"><div class="dash-heading"><h2 id="dashMoreTitle">Cuenta y apoyo</h2><p>Gestiona tus datos y encuentra ayuda cuando la necesites.</p></div><div class="apple-catalog-grid">{support}</div></div></section>
<section class="dash-section" id="dashManagement" aria-labelledby="dashManagementTitle" hidden><div class="apple-container"><div class="dash-heading"><h2 id="dashManagementTitle">Gestión</h2><p>Accesos disponibles para tu perfil profesional.</p></div><ul class="dash-role-links" id="dashRoleLinks"></ul></div></section>
<section class="dash-section dash-help" aria-labelledby="dashHelpTitle"><div class="apple-container"><div class="asistencia-block"><p class="apple-eyebrow">Te ayudamos a continuar</p><h2 id="dashHelpTitle">¿Necesitas ayuda con tus archivos?</h2><p>Cuéntanos qué exchange utilizas y en qué paso te has quedado. Evita incluir contraseñas, claves privadas o documentación fiscal en tu primera consulta.</p><a class="apple-button" href="/contacto">Contactar</a></div></div></section>
</div>
<noscript><style>#dashAccess{{display:none}}#dashWorkspace[hidden]{{display:block!important}}</style><div class="apple-container dash-nojs"><p>La búsqueda y el menú de cuenta requieren JavaScript. Puedes abrir directamente las herramientas y tu cuenta.</p><a href="/account">Mi cuenta</a><a href="/faq">Preguntas frecuentes</a></div></noscript>
</main>{footer}</body></html>'''

MOCK='''<script>
(() => {
 const profile=new URLSearchParams(location.search).get('perfil')||'usuario';
 const user=profile==='caducada'?null:{full_name:'Usuario de prueba',email:'preview@example.invalid',plan:'free',is_admin:profile==='administrador',is_fiscal_advisor:['administrador','asesor'].includes(profile)};
 window.fetch=async(input,options={})=>{
  const path=new URL(typeof input==='string'?input:input.url,location.origin).pathname;
  if(path==='/api/me'&&(!options.method||options.method==='GET')){
   return new Response(JSON.stringify(profile==='error'?{error:'Synthetic unavailable'}:{user}),{status:profile==='error'?503:200,headers:{'Content-Type':'application/json'}});
  }
  throw new Error('Viewer blocks all other requests');
 };
 document.addEventListener('click',event=>{
  const target=event.target.closest('a,button');if(!target)return;
  if((target.getAttribute('href')||'').startsWith('#vista-')||target.textContent.trim()==='Cerrar sesión'){
   event.preventDefault();event.stopImmediatePropagation();
   const notice=document.getElementById('dashViewerNotice');notice.hidden=false;
   notice.querySelector('p').textContent='Esta vista previa no abre herramientas privadas ni envía datos. El acceso funciona en las rutas protegidas de la aplicación.';
  }
 },true);
})();</script>'''

def inert_href(match):
 value=match[1]
 if not value.startswith('/') or value.startswith('//'):return match[0]
 path=urlsplit(value).path.rstrip('/')
 if path in PRIVATE:return 'href="#vista-'+path.strip('/').replace('/','-')+'"'
 if path.startswith('/static/'):return 'href="/fiscal_app_export'+value+'"'
 return 'href="https://marianosevilla.com'+value+'"'

def main():
 html=make();(TEMPLATES/'dashboard_apple.html').write_text(html)
 viewer=html.replace('data-dashboard-state="loading"','data-dashboard-state="loading" data-dashboard-preview="true"')
 for css in ['nav.css','landing_apple.css','dashboard_apple.css']:
  viewer=viewer.replace(f'<link rel="stylesheet" href="/static/{css}">','<style>'+(STATIC/css).read_text()+'</style>')
 deferred=[]
 for js in ['nav.js','landing_apple.js','dashboard_apple.js']:
  code=(STATIC/js).read_text().replace('</script','<\\/script')
  code=re.sub(r'href="([^"]+)"',inert_href,code)
  code=code.replace("a.href='/admin/contactos'","a.href='#vista-admin-contactos'")
  tag='<script>'+code+'</script>'
  if js=='nav.js':viewer=viewer.replace('<script src="/static/nav.js"></script>',tag)
  else:
   viewer=viewer.replace(f'<script src="/static/{js}" defer></script>','');deferred.append(tag)
 viewer=re.sub(r'href="([^"]+)"',inert_href,viewer)
 viewer=viewer.replace('/static/images/','/fiscal_app_export/static/images/')
 notice='<div id="dashViewerNotice" class="apple-container" role="status" hidden><p></p><button class="dash-text-button" type="button" onclick="this.parentElement.hidden=true">Cerrar aviso</button></div>'
 viewer=viewer.replace('<body class="apple-home apple-dashboard"','<body class="apple-home apple-dashboard"')
 viewer=viewer.replace('<main id="contenido"',MOCK+'<main id="contenido"')
 # Mock must be in place BEFORE nav.js performs its one session request.
 viewer=viewer.replace(MOCK,'').replace('<nav id="site-nav"',MOCK+'<nav id="site-nav"',1)
 viewer=viewer.replace('</body>',notice+''.join(deferred)+'</body>')
 OUT.mkdir(exist_ok=True);(OUT/'index.html').write_text(viewer)
 print('Built protected dashboard template and inert synthetic viewer; original dashboard unchanged.')

if __name__=='__main__':main()
