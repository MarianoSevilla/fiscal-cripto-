"""Build approved production auth pages and a provider-free review viewer."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'fiscal_app_export/static'
OUT=ROOT/'auth-apple-preview'
GOOGLE='''<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>'''
PAGES={
 'login':('login_apple.html','login','Iniciar sesión','Accede a tu cuenta para continuar con tus herramientas fiscales.','Iniciar sesión'),
 'signup':('signup_apple.html','signup','Crear cuenta','Regístrate para acceder a las herramientas fiscales de criptomonedas.','Crear cuenta'),
 'forgot':('forgot_password_apple.html','recuperar','Recuperar contraseña','Introduce el correo de tu cuenta. Si corresponde, recibirás un enlace para crear una nueva contraseña.','Enviar enlace'),
 'reset':('reset_password_apple.html','restablecer','Nueva contraseña','Elige una contraseña que no utilices en otros servicios.','Guardar contraseña'),
 'verify':('verify_email_apple.html','verificar','Verifica tu correo','Abre el enlace de verificación de tu correo para continuar.','Solicitar otro enlace'),
}

def field(key,label,kind='text',autocomplete='',hint='',forgot=False):
    link='<a href="/recuperar-contrasena" data-auth-next>¿Olvidaste tu contraseña?</a>' if forgot else ''
    control=f'<div class="auth-label-row"><label for="{key}">{label}</label>{link}</div>'
    error_id=key+'Error'
    hint_id=key+'Hint'
    input_html=f'<input id="{key}" name="'+{'authName':'full_name','authEmail':'email','authPassword':'password','authConfirm':'confirm_password'}[key]+f'" type="{kind}" autocomplete="{autocomplete}" required aria-describedby="{error_id}'+(' '+hint_id if hint else '')+'"'
    if kind=='email':input_html+=' maxlength="254" inputmode="email" autocapitalize="none" spellcheck="false"'
    if key=='authName':input_html+=' maxlength="150"'
    input_html+='>'
    if kind=='password':input_html='<div class="auth-input-wrap">'+input_html+f'<button class="auth-reveal" type="button" aria-controls="{key}" aria-pressed="false">Mostrar</button></div>'
    return '<div class="auth-field">'+control+input_html+(f'<p class="auth-hint" id="{hint_id}">{hint}</p>' if hint else '')+f'<p class="auth-field-error" id="{error_id}" hidden></p></div>'

def make(view):
    filename,slug,title,description,caption=PAGES[view]
    inputs=''
    if view=='signup':inputs+=field('authName','Nombre y apellidos',autocomplete='name')
    if view in {'login','signup','forgot','verify'}:inputs+=field('authEmail','Correo electrónico','email','username' if view=='login' else 'email')
    if view in {'login','signup','reset'}:inputs+=field('authPassword','Contraseña' if view!='reset' else 'Nueva contraseña','password','current-password' if view=='login' else 'new-password',hint='' if view=='login' else 'Al menos 15 caracteres. Puedes usar una frase con espacios.',forgot=view=='login')
    if view=='reset':inputs+=field('authConfirm','Repetir contraseña','password','new-password')
    google=f'<div data-auth-entry><a class="auth-google" href="/auth/google" data-auth-next>{GOOGLE}Continuar con Google</a><div class="auth-divider">O utiliza tu correo</div></div>' if view in {'login','signup'} else ''
    legal='<p class="auth-legal" data-auth-entry>Al crear tu cuenta aceptas los <a href="/terminos">Términos del servicio</a>. Consulta cómo tratamos tus datos en la <a href="/privacidad">Política de privacidad</a>.</p>' if view=='signup' else ''
    if view=='login':legal='<p class="auth-legal">Si es tu primer acceso con Google, se creará una cuenta. Consulta los <a href="/terminos">Términos del servicio</a> y la <a href="/privacidad">Política de privacidad</a>.</p>'
    recovery='<p class="auth-switch" id="authRecovery" hidden><a href="/recuperar-contrasena" data-auth-next>Si ya tenías cuenta, puedes recuperar la contraseña</a>.</p>' if view=='signup' else ''
    switch={'login':'¿No tienes cuenta? <a href="/signup/" data-auth-next>Crear cuenta</a>','signup':'¿Ya tienes cuenta? <a href="/login/" data-auth-next>Iniciar sesión</a>'}.get(view,'<a href="/login/" data-auth-next>Volver al inicio de sesión</a>')
    path={'login':'/login','signup':'/signup','forgot':'/recuperar-contrasena','reset':'/reset-password','verify':'/verify-email-result'}[view]
    return f'''<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | Mariano Sevilla</title><meta name="robots" content="noindex, nofollow"><link rel="canonical" href="https://marianosevilla.com{path}"><link rel="icon" href="/static/favicon.ico">
<link rel="stylesheet" href="/static/landing_apple.css"><link rel="stylesheet" href="/static/auth_apple.css"><script src="/static/auth_apple.js" defer></script></head>
<body class="apple-home apple-auth" data-auth-view="{view}"><a class="apple-skip" href="#contenido">Saltar al contenido</a>
<header class="auth-header"><a href="/" class="auth-brand" aria-label="marianosevilla.com">mariano<span>sevilla</span>.com</a><a href="/" class="auth-back">Volver al inicio</a></header>
<main class="auth-layout" id="contenido" tabindex="-1">
<aside class="auth-story" aria-label="Sobre el proyecto"><div class="auth-orbit" aria-hidden="true">
<img src="/static/auth-assets/btc.svg" alt="" width="48" height="48"><img src="/static/auth-assets/xrp.svg" alt="" width="42" height="42"><img src="/static/auth-assets/xlm.svg" alt="" width="42" height="42"><img src="/static/images/bitvavo.png" alt="" width="42" height="42"><img src="/static/images/binance.jpg" alt="" width="30" height="30"></div>
<p class="apple-eyebrow">Informes FIFO de criptomonedas</p><h2>Tus operaciones.<br><em>Una visión más clara.</em></h2>
<p class="auth-story-copy">Organiza tu historial y prepara la información que necesitas para revisar tu fiscalidad.</p>
<div class="auth-person"><img src="/static/home-apple-mariano-88.webp" alt="Mariano Sevilla" width="48" height="48"><div><p>Un proyecto de Mariano Sevilla</p><a href="/about">Conoce quién está detrás</a></div></div></aside>
<section class="auth-card" aria-labelledby="authHeading"><h1 id="authHeading">{title}</h1><p id="authDescription" class="auth-description">{description}</p>{google}
<div id="authError" class="auth-error" role="alert" tabindex="-1" hidden></div><div id="authStatus" class="auth-status" role="status" tabindex="-1" hidden></div>
<form id="authForm" method="post" action="/api/{ {'login':'login','signup':'register','forgot':'forgot-password','reset':'reset-password','verify':'resend-verification'}[view]}" novalidate>{inputs}<button id="authSubmit" class="apple-button auth-submit" type="submit">{caption}</button></form>
<button id="authResend" class="auth-resend" type="button" hidden>Reenviar enlace</button>
<a id="authContinue" class="apple-button auth-submit" href="/login/" data-auth-next hidden>Iniciar sesión</a>{recovery}{legal}
<p class="auth-switch" data-auth-entry>{switch}</p>
<noscript><style>#authForm{{display:none}}</style><p class="auth-noscript">Activa JavaScript para utilizar el acceso y la recuperación de cuenta. Si necesitas ayuda, <a href="/contacto">contacta con nosotros</a>.</p></noscript>
</section></main>
<footer class="auth-footer"><p>© 2026 Mariano Sevilla</p><nav aria-label="Información legal"><a href="/privacidad">Privacidad</a><a href="/terminos">Términos</a><a href="/cookies">Cookies</a><a href="/aviso-legal">Aviso legal</a><a href="/contacto">Ayuda</a></nav></footer></body></html>'''

if __name__=='__main__':
    production={'login':'login.html','signup':'signup.html','forgot':'forgot-password.html',
                'reset':'reset-password.html','verify':'verify-email.html'}
    for view,(filename,slug,*_) in PAGES.items():
        html=make(view);(STATIC/filename).write_text(html)
        (STATIC/production[view]).write_text(html)
        viewer=html.replace(f'data-auth-view="{view}"',f'data-auth-view="{view}" data-auth-preview="true"')
        for css in ['landing_apple.css','auth_apple.css']:
            viewer=viewer.replace(f'<link rel="stylesheet" href="/static/{css}">','<style>'+(STATIC/css).read_text()+'</style>')
        script=(STATIC/'auth_apple.js').read_text().replace('</script','<\\/script')
        viewer=viewer.replace('<script src="/static/auth_apple.js" defer></script>','').replace('</body>','<script>'+script+'</script></body>')
        # Inline the tiny decorative SVGs; serve existing portraits/exchanges locally.
        for coin in ['btc','xrp','xlm']:
            import base64
            src='data:image/svg+xml;base64,'+base64.b64encode((STATIC/f'auth-assets/{coin}.svg').read_bytes()).decode()
            viewer=viewer.replace(f'/static/auth-assets/{coin}.svg',src)
        viewer=viewer.replace('/static/images/','/fiscal_app_export/static/images/').replace('/static/home-apple-','/fiscal_app_export/static/home-apple-')
        mapping={'/login/':'login','/signup/':'signup','/recuperar-contrasena':'recuperar'}
        for target,name in mapping.items():viewer=viewer.replace(f'href="{target}"',f'href="/auth-apple-preview/{name}/"')
        # Remains inert with JS disabled or when opened in a new tab.
        viewer=viewer.replace('href="/auth/google"','href="#authHeading"')
        viewer=re.sub(r'href="(/(?!/|auth-apple-preview/)[^"]*)"',lambda m:'href="https://marianosevilla.com'+m[1]+'"',viewer)
        # Avoid offering password-manager autofill for the public static viewer.
        viewer=viewer.replace('autocomplete="current-password"','autocomplete="off"').replace('autocomplete="new-password"','autocomplete="off"')
        dest=OUT/slug;dest.mkdir(parents=True,exist_ok=True);(dest/'index.html').write_text(viewer)
    (OUT/'index.html').write_text((OUT/'login/index.html').read_text())
    print('Built 5 approved production auth pages and isolated viewers.')
