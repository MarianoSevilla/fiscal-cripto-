"""Shared avatar/mobile navigation; synthetic profiles and local assets only."""
import json
from urllib.parse import urlsplit


GENERAL = [('Mi espacio fiscal', '/dashboard'), ('Mi cuenta', '/account')]
ADVISOR = [
    ('Panel asesoramiento', '/admin/asesoramiento'),
    ('Solicitudes de recursos', '/admin/recursos'),
]
ADMIN = [
    ('Stats', '/stats'), ('Panel asesoramiento', '/admin/asesoramiento'),
    ('Comunicaciones', '/admin/comunicaciones'),
    ('Solicitudes de recursos', '/admin/recursos'),
    ('Mis solicitudes fiscales', '/mis-solicitudes-fiscales'),
    ('Contactos', '/admin/contactos'),
]


def run_avatar_navigation(browser, origin, check_header):
    cases = 0
    for path in ['/', '/modelo721']:
        for role in ['user', 'advisor', 'admin']:
            for plan in ['free', 'pro']:
                for width in [320, 390, 768, 1200, 1280]:
                    ctx = browser.new_context(viewport={'width': width, 'height': 650})
                    state = {'logout': False}
                    writes, bad, errors = [], [], []
                    user = {
                        'full_name': 'Persona sintética', 'email': 'fixture@example.invalid',
                        'plan': plan, 'is_admin': role == 'admin',
                        'is_fiscal_advisor': role in ['advisor', 'admin'],
                    }

                    def route(r):
                        request = r.request
                        url = urlsplit(request.url)
                        if url.hostname == 'fonts.googleapis.com':
                            r.fulfill(status=200, content_type='text/css', body='')
                            return
                        if url.hostname != '127.0.0.1':
                            bad.append(request.url)
                            r.abort()
                            return
                        if url.path == '/api/me':
                            r.fulfill(status=200, content_type='application/json',
                                      body=json.dumps({'user': None if state['logout'] else user}))
                        elif url.path == '/api/logout' and request.method == 'POST':
                            writes.append((request.method, url.path))
                            state['logout'] = True
                            r.fulfill(status=200, content_type='application/json', body='{}')
                        elif request.method != 'GET' or url.path.startswith('/api/'):
                            bad.append(request.method + ' ' + url.path)
                            r.abort()
                        else:
                            r.continue_()

                    ctx.route('**/*', route)
                    page = ctx.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    try:
                        assert page.goto(origin + path, wait_until='networkidle').status == 200
                        page.locator('#site-nav[data-auth-state=authenticated]').wait_for()
                        check_header(page, width)
                        professional = ADMIN if role == 'admin' else ADVISOR if role == 'advisor' else []
                        expected = GENERAL + professional
                        labels = [text for text, _ in expected] + ['Cerrar sesión']
                        avatar = page.locator('#snavAvatar')
                        dropdown = page.locator('#snavDropdown')
                        avatar.focus()
                        page.keyboard.press('Enter')
                        assert avatar.get_attribute('aria-expanded') == 'true'
                        assert avatar.get_attribute('aria-controls') == 'snavDropdown'
                        assert avatar.get_attribute('aria-haspopup') is None
                        assert dropdown.get_attribute('role') is None
                        assert dropdown.locator('[role=menuitem]').count() == 0
                        visible = dropdown.locator('.snav-dd-item:visible')
                        assert visible.all_text_contents() == labels, (path, role, plan, width)
                        assert dropdown.locator('a:visible').evaluate_all(
                            'nodes=>nodes.map(a=>a.getAttribute("href"))') == [href for _, href in expected]
                        assert dropdown.locator('a[href="/pricing"],a[href="/recursos"],a[href="/pedir-asesoramiento"]').count() == 0
                        box = dropdown.bounding_box()
                        assert box['x'] >= -1 and box['x'] + box['width'] <= width + 1
                        for label in labels:
                            page.keyboard.press('Tab')
                            assert page.evaluate('document.activeElement.textContent.trim()') == label
                        page.keyboard.press('Escape')
                        # Approved Home also restores focus in a capture-phase RAF.
                        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(resolve))')
                        assert avatar.get_attribute('aria-expanded') == 'false'
                        assert not dropdown.is_visible()
                        assert avatar.evaluate('e=>e===document.activeElement')

                        if width <= 1200:
                            toggle = page.locator('#snavMenuToggle')
                            public = page.locator('.snav-links a').all_text_contents()
                            toggle.focus()
                            page.keyboard.press('Enter')
                            menu = page.locator('#snavMobileMenu')
                            assert menu.is_visible()
                            assert menu.locator('a,button').all_text_contents() == [s.strip() for s in public] + labels
                            assert menu.locator('a[href="/pricing"],a[href="/pedir-asesoramiento"]').count() == 0
                            box = menu.bounding_box()
                            assert box['x'] >= -1 and box['x'] + box['width'] <= width + 1
                            assert box['y'] + box['height'] <= 651
                            for label in [s.strip() for s in public] + labels:
                                page.keyboard.press('Tab')
                                assert page.evaluate('document.activeElement.textContent.trim()') == label
                            page.keyboard.press('Escape')
                            assert not menu.is_visible()
                            assert toggle.evaluate('e=>e===document.activeElement')
                            toggle.click()
                            menu.get_by_role('button', name='Cerrar sesión', exact=True).click()
                        else:
                            avatar.click()
                            dropdown.get_by_role('button', name='Cerrar sesión', exact=True).click()
                        page.wait_for_url(origin + '/')
                        page.locator('#site-nav[data-auth-state=anonymous]').wait_for()
                        assert page.locator('#snavAvatarWrap').is_hidden()
                        assert writes == [('POST', '/api/logout')]
                        assert not bad and not errors, (path, role, plan, width, bad, errors)
                        cases += 1
                    finally:
                        ctx.close()
    print(f'AVATAR_NAVIGATION_QA: PASS ({cases} scenarios; 3 roles x 2 plans; mobile/tablet/desktop; native links; keyboard; synthetic logout; no production requests)')
