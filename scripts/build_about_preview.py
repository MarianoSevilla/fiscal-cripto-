"""Build the isolated About preview from the approved Home; no production writes."""
from pathlib import Path
import json,re

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'fiscal_app_export/static'
OUT=BASE
home=(BASE/'landing.html').read_text()
header=home.split('<body class="apple-home">',1)[1].split('<main ',1)[0]
header=header.replace('<nav id="site-nav">','<nav id="site-nav" aria-label="Principal">')
footer=re.search(r'<footer class="apple-footer".*?</footer>',home,re.S)[0]
footer=footer.replace('href="/about"','href="/about" aria-current="page"')
description='Conoce a Mariano Sevilla, desarrollador de la plataforma, y a Rafael Ramos, economista colegiado que define sus criterios fiscales y presta asesoramiento profesional.'
schema={'@context':'https://schema.org','@type':'AboutPage','@id':'https://marianosevilla.com/about','url':'https://marianosevilla.com/about','name':'Mariano Sevilla y Rafael Ramos | Quiénes somos','description':description,'inLanguage':'es','isPartOf':{'@id':'https://marianosevilla.com/#website'},'mainEntity':[
 {'@type':'Person','@id':'https://marianosevilla.com/about#mariano','name':'Mariano Sevilla','jobTitle':'Desarrollo de la plataforma','sameAs':['https://www.youtube.com/@MarianoSevilla'],'alumniOf':{'@type':'CollegeOrUniversity','name':'Universitat Politècnica de València','url':'https://www.upv.es/'}},
 {'@type':'Person','@id':'https://marianosevilla.com/about#rafael','name':'Rafael Ramos Martínez','jobTitle':'Economista colegiado','description':'Define los criterios fiscales y funcionales de la herramienta y presta asesoramiento profesional por separado.','memberOf':{'@type':'Organization','name':'Colegio de Economistas de Valencia','url':'https://www.coev.com/'}}
]}
head='''<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mariano Sevilla y Rafael Ramos | Quiénes somos</title>
<meta name="description" content="'''+description+'''">
<meta name="robots" content="noindex, nofollow"><link rel="canonical" href="https://marianosevilla.com/about"><link rel="icon" href="/static/favicon.ico">
<meta property="og:type" content="website"><meta property="og:url" content="https://marianosevilla.com/about"><meta property="og:title" content="Mariano Sevilla y Rafael Ramos | Quiénes somos"><meta property="og:description" content="'''+description+'''"><meta property="og:image" content="https://marianosevilla.com/static/og-image.png"><meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="/static/nav.css"><link rel="stylesheet" href="/static/landing_apple.css"><link rel="stylesheet" href="/static/about_apple.css">
<script src="/static/landing_apple.js" defer></script><script type="application/ld+json">'''+json.dumps(schema,ensure_ascii=False)+'''</script></head><body class="apple-home apple-about-page">'''
def portrait(person,name):
 return f'<img class="about-portrait" src="/static/home-apple-{person}-264.webp" srcset="/static/home-apple-{person}-88.webp 88w, /static/home-apple-{person}-176.webp 176w, /static/home-apple-{person}-264.webp 264w" sizes="(max-width:640px) 88px, 132px" alt="{name}" width="132" height="132" loading="lazy" decoding="async">'
main='''<main id="contenido" tabindex="-1">
<section class="apple-intro about-intro" aria-labelledby="about-title"><div class="apple-container">
<p class="apple-eyebrow">Mariano Sevilla y Rafael Ramos</p>
<h1 id="about-title">Las personas detrás de <em>este proyecto.</em></h1>
<p class="about-lead">Mariano desarrolla la plataforma a partir de los criterios de Rafael, economista colegiado. Tecnología y conocimiento fiscal, con responsabilidades claras.</p>
</div></section>
<section class="about-section about-people" aria-label="Personas y responsabilidades"><div class="apple-container"><div class="about-people-grid">
<article class="about-profile" aria-labelledby="mariano-name"><div class="about-person-heading">'''+portrait('mariano','Mariano Sevilla')+'''<div class="about-person-identity"><h2 id="mariano-name">Mariano Sevilla</h2><p class="about-role">Desarrollo de la plataforma</p></div></div>
<div class="about-bio"><p>Diplomado en Informática de Gestión por la <a href="https://www.upv.es/" target="_blank" rel="noopener noreferrer">Universitat Politècnica de València</a>, con experiencia en ERP y CRM, automatización de procesos y dirección técnica de startups.</p>
<p>Impulsa marianosevilla.com, desarrolla la herramienta e implementa los criterios fiscales y funcionales que define Rafael Ramos. También crea contenido sobre criptomonedas en su canal de YouTube.</p></div>
<a class="apple-text-link about-person-link" href="https://www.youtube.com/@MarianoSevilla" target="_blank" rel="noopener noreferrer">YouTube de Mariano Sevilla</a></article>
<article class="about-profile" aria-labelledby="rafael-name"><div class="about-person-heading">'''+portrait('rafa','Rafael Ramos Martínez')+'''<div class="about-person-identity"><h2 id="rafael-name">Rafael Ramos Martínez</h2><p class="about-role">Criterio fiscal y asesoramiento</p></div></div>
<div class="about-bio"><p>Economista colegiado n.º 4.579 del <a href="https://www.coev.com/" target="_blank" rel="noopener noreferrer">Colegio de Economistas de Valencia</a>, con más de 25 años de experiencia en gestión fiscal, contabilidad y dirección financiera.</p>
<p>Define cómo debe funcionar la herramienta desde el punto de vista fiscal y funcional. Además, presta asesoramiento personalizado, que el usuario contrata directamente con él.</p></div>
<a class="apple-text-link about-person-link" href="/pedir-asesoramiento">Consultar mi caso</a></article>
</div></div></section>
<section class="about-section about-scope" aria-labelledby="scope-title"><div class="apple-container">
<div class="about-heading"><h2 id="scope-title">Qué hace la herramienta.<br>Qué aporta el profesional.</h2><p>Dos funciones complementarias, con un alcance diferente.</p></div>
<div class="about-scope-grid"><div><h3>El informe automático</h3><p>Organiza el historial importado y sus cálculos para ayudarte a revisar tus operaciones. Debes comprobar los datos, las advertencias y que el historial esté completo.</p><p>Generar un informe no incluye una revisión profesional individual ni presenta tu declaración ante Hacienda. <a href="/como-funciona">Conoce el alcance de la herramienta</a>.</p></div>
<div><h3>El asesoramiento personalizado</h3><p>Rafael valora tu situación y concreta contigo el alcance y los honorarios antes de contratar. La web tramita la solicitud; el cliente contrata y paga directamente al profesional.</p><p>Mariano recibe una comisión por la intermediación. Puedes consultar este funcionamiento en los <a href="/terminos#asesoramiento">términos del servicio</a>.</p></div></div>
</div></section>
<section class="about-section about-help" aria-labelledby="help-title"><div class="apple-container"><div class="asistencia-block">
<p class="apple-eyebrow">Asesoramiento fiscal de criptomonedas</p><h2 id="help-title">¿Quieres que un profesional revise tu caso?</h2>
<p>Cuéntanos tu situación para valorar el asesoramiento que necesitas. El alcance y los honorarios se concretan con Rafael antes de contratar.</p>
<div class="about-help-actions"><a class="apple-button" href="/pedir-asesoramiento">Solicitar asesoramiento fiscal</a><a class="apple-text-link" href="/herramientas">Ver herramientas fiscales</a></div>
</div></div></section></main>'''
html=head+header+main+footer+'</body></html>'
(OUT/'about_apple.html').write_text(html)
viewer=html
for name in ['nav.css','landing_apple.css','about_apple.css']:
 viewer=viewer.replace(f'<link rel="stylesheet" href="/static/{name}">','<style>'+(BASE/name).read_text()+'</style>')
for name in ['nav.js','landing_apple.js']:
 script=(BASE/name).read_text()
 if name=='nav.js':
  assert "fetch('/api/me'" in script
  script=script.replace("fetch('/api/me'","fetch('/about-apple-preview/session.json'")
 script=script.replace('</script','<\\/script')
 tag=f'<script src="/static/{name}"'+(' defer' if name!='nav.js' else '')+'></script>'
 if name=='nav.js':viewer=viewer.replace(tag,'<script>'+script+'</script>')
 else:viewer=viewer.replace(tag,'').replace('</body>','<script>'+script+'</script></body>')
viewer=viewer.replace('/static/home-apple-','/fiscal_app_export/static/home-apple-')
viewer=re.sub(r'href="(/(?!/)[^"]*)"',lambda m:'href="https://marianosevilla.com'+m[1]+'"',viewer)
v=ROOT/'about-apple-preview';v.mkdir(exist_ok=True)
(v/'index.html').write_text(viewer)
(v/'session.json').write_text('{"user":null}\n')
print('Built About source and isolated viewer. Production about.html is untouched.')
