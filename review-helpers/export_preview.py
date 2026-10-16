"""Build an offline review derivative; this helper is not committed to the app."""
import base64
import mimetypes
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'fiscal_app_export/static'

def preview_header(text):
    """Offline public header: native disclosure, no session or script dependency.

    This is a review-only adapter. The application keeps its shared header.
    Avoid fixed positioning: document viewers may reflow fixed elements.
    """
    shell=re.search(r'<nav id="site-nav">[\s\S]*?</nav>',text).group(0)
    logo=re.search(r'<a href="/" class="snav-logo">[\s\S]*?</a>',shell).group(0)
    links=re.search(r'<ul class="snav-links">([\s\S]*?)</ul>',shell).group(1)
    mobile_links='\n'.join(re.findall(r'<a\b[^>]*>[\s\S]*?</a>',links))
    header='''<nav id="site-nav" aria-label="Navegación principal">
  <div class="snav-inner">
    '''+logo+'''
    <ul class="snav-links">'''+links+'''</ul>
    <div class="snav-right">
      <a href="/login/" class="snav-btn-login">Iniciar sesión</a>
      <a href="/signup/" class="snav-btn-cta">Crear cuenta</a>
    </div>
    <details class="apple-preview-menu">
      <summary aria-label="Menú principal">
        <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M2 4h16M2 10h16M2 16h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      </summary>
      <nav class="apple-preview-panel" aria-label="Navegación móvil">
        '''+mobile_links+'''
        <a href="/login/">Iniciar sesión</a>
        <a href="/signup/" class="snav-mobile-link-primary">Crear cuenta</a>
      </nav>
    </details>
  </div>
</nav>'''
    text=text.replace(shell,header,1)
    # Keep the header first in document flow, even if a viewer rewrites the
    # positioning of the visually hidden skip link. The link remains focusable.
    skip='<a class="apple-skip" href="#contenido">Saltar al contenido</a>'
    assert text.count(skip)==1
    text=text.replace(skip+'\n','',1).replace(header,header+'\n'+skip,1)
    text,n=re.subn(r'<noscript>[\s\S]*?</noscript>','',text)
    assert n==1
    # Loaded after application styles, and scoped to this exported file only.
    css='''<style id="apple-preview-header-styles">
html{margin:0!important;padding:0!important}
body.apple-home{margin:0!important;padding:0!important}
.apple-home #site-nav{position:relative;top:auto;left:auto;right:auto;margin:0;padding:0;min-height:64px;height:auto;background:#fff;backdrop-filter:none;-webkit-backdrop-filter:none}
.apple-home #site-nav .snav-inner{margin-block:0;padding-block:8px;min-height:64px;height:auto}
.apple-home .apple-skip{position:absolute;top:0;left:0;transform:none;width:1px;height:1px;padding:0;overflow:hidden;clip-path:inset(50%)}
.apple-home .apple-skip:focus{width:auto;height:auto;padding:12px 18px;clip-path:none;z-index:2000}
.apple-home .apple-intro-inner{padding-top:40px}
.apple-home #site-nav .apple-preview-menu{display:none}
.apple-home #site-nav .apple-preview-panel{display:none}
@media(max-width:1200px){
  .apple-home #site-nav .snav-inner{display:flex;justify-content:space-between;gap:16px}
  .apple-home #site-nav .snav-links,.apple-home #site-nav .snav-right{display:none}
  .apple-home #site-nav .apple-preview-menu{display:block;flex:0 0 44px}
  .apple-home #site-nav .apple-preview-menu>summary{display:flex;align-items:center;justify-content:center;width:44px;height:44px;list-style:none;border:1px solid #d8e1dd;border-radius:9px;background:#f3f6f5;color:#1d2428;cursor:pointer}
  .apple-home #site-nav .apple-preview-menu>summary::-webkit-details-marker{display:none}
  .apple-home #site-nav .apple-preview-menu>summary svg{display:block;flex:none}
  .apple-home #site-nav .apple-preview-menu[open] .apple-preview-panel{display:flex;position:absolute;top:100%;left:0;right:0;flex-direction:column;gap:4px;padding:12px var(--apple-pad) 18px;max-height:calc(100vh - 64px);max-height:calc(100dvh - 64px);overflow-y:auto;overscroll-behavior:contain;background:#fff;box-shadow:0 14px 28px rgba(20,34,30,.1)}
  .apple-home #site-nav .apple-preview-panel>a{display:flex;align-items:center;min-height:44px;padding:11px 14px;border-radius:8px;color:var(--muted);font-size:.9375rem;line-height:1.4;text-decoration:none}
  .apple-home #site-nav .apple-preview-panel>a:hover{background:#f1f5f3;color:var(--text)}
  .apple-home #site-nav .apple-preview-panel>a.snav-mobile-link-primary{justify-content:center;min-height:48px;border-radius:999px;background:var(--accent);color:#fff;font-weight:600}
  .apple-home #site-nav .apple-preview-panel>a.snav-mobile-link-primary:hover{background:#00533f}
  .apple-home .apple-intro-inner{padding-top:32px}
}
@media(max-width:640px){.apple-home .apple-intro-inner{padding-top:36px}}
</style>'''
    return text.replace('</head>',css+'\n</head>')

def export(name,title,shared_navigation=False):
    text=(STATIC/'landing_apple.html').read_text()
    if 'apple-exchange-support' in text or 'seguimos añadiendo soporte continuamente.' in text:
        raise ValueError('El bloque de soporte eliminado en V15 no puede volver a la vista previa')
    def link(match):
        tag=match.group(0)
        asset=re.search(r'href="/static/(nav|landing_apple)\.css"',tag)
        if asset:
            return '<style>\n'+(STATIC/(asset.group(1)+'.css')).read_text()+'\n</style>'
        if 'href="/static/' in tag:
            return ''
        return tag
    text=re.sub(r'<link\b[^>]*>',link,text)
    text,n=re.subn(r'<script\b[^>]*src="/static/(?:nav|landing_apple)\.js"[^>]*></script>','',text)
    assert n==2
    if not shared_navigation:
        text=preview_header(text)
    # Native public navigation replaces shared session hydration in offline files.
    # Other Home enhancements remain available when the viewer permits scripts.
    script_names=['nav.js','landing_apple.js'] if shared_navigation else ['landing_apple.js']
    scripts='\n'.join('<script>\n'+(STATIC/name).read_text()+'\n</script>' for name in script_names)
    text=text.replace('</body>',scripts+'\n</body>')
    def embedded_asset(url):
        if not url.startswith('/static/'):
            return url
        name_image=url.removeprefix('/static/')
        asset=STATIC/name_image
        if not asset.is_file():
            asset=ROOT/'review-assets'/name_image
        data=base64.b64encode(asset.read_bytes()).decode()
        mime=mimetypes.guess_type(name_image)[0]
        assert mime in ('image/png','image/webp'),name_image
        return 'data:'+mime+';base64,'+data
    def embedded_attribute(match):
        attribute,value=match.groups()
        if attribute=='srcset':
            candidates=[]
            for candidate in value.split(','):
                url,descriptor=candidate.strip().split()
                candidates.append(embedded_asset(url)+' '+descriptor)
            value=', '.join(candidates)
        else:
            value=embedded_asset(value)
        return attribute+'="'+value+'"'
    text=re.sub(r'\b(src|srcset)="([^"]+)"',embedded_attribute,text)
    text=re.sub(r'href="(/[^\"]*)"',lambda m:'href="https://marianosevilla.com'+m.group(1)+'" target="_blank" rel="noopener noreferrer"',text)
    stub="<script>window.fetch=async function(input){const ok=String(input)==='/api/me';return new Response(JSON.stringify(ok?{user:null}:{error:'Vista previa sin envío de formularios'}),{status:ok?200:503,headers:{'Content-Type':'application/json'}})};</script>"
    text=text.replace('</head>',stub+'</head>')
    text=text.replace('<title>','<title>'+title+' · ',1)
    (ROOT/name).write_text(text)
    (ROOT/'Home_Apple_Vista_Previa.html').write_text(text)
    return ROOT/name

if __name__=='__main__':
    print(export('Home_Apple_v23_header_sin_hueco.html','Vista previa v23'))
