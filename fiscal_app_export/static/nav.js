/**
 * nav.js — Header desktop unificado
 *
 * Uso: añadir <nav id="site-nav"></nav> en el HTML y cargar este script.
 * El script detecta la página actual, hace fetch a /api/me y renderiza
 * el estado correcto (no autenticado / autenticado / admin).
 *
 * Expone window.SiteNav con:
 *   SiteNav.updateAvatar(initial)  — para actualizar la inicial del avatar
 *                                    desde páginas que cambian el nombre del usuario.
 */
(function () {
  'use strict';

  // ── HTML de la zona derecha (skeleton + botones + avatar) ────────────────
  // Se inyecta en .snav-right cuando ya existe el shell estático en el HTML.
  function buildRightHTML() {
    return `
          <!-- Skeleton: visible mientras /api/me está en vuelo -->
          <div class="snav-skeleton" id="snavSkeleton" aria-hidden="true"></div>
          <span class="snav-auth-status" id="snavAuthStatus" role="status" aria-live="polite"></span>
          <button type="button" class="snav-auth-retry snav-hidden" id="snavAuthRetry" aria-describedby="snavAuthStatus">Reintentar</button>

          <!-- Estado NO autenticado (oculto hasta que /api/me resuelve) -->
          <a href="/login/"   class="snav-btn-login snav-hidden" id="snavBtnLogin">Iniciar sesión</a>
          <a href="/signup/"  class="snav-btn-cta   snav-hidden" id="snavBtnSignup">Crea tu cuenta gratis</a>

          <!-- Estado autenticado (oculto hasta que /api/me resuelve) -->
          <div class="snav-avatar-wrap snav-hidden" id="snavAvatarWrap">
            <button class="snav-avatar" id="snavAvatar" aria-label="Menú de usuario" aria-haspopup="true" aria-expanded="false">U</button>
            <div class="snav-dropdown" id="snavDropdown" role="menu">
              <a href="/account"   class="snav-dd-item"             id="snavItemAccount" role="menuitem">Mi cuenta</a>
              <a href="/dashboard" class="snav-dd-item"             id="snavItemDash"    role="menuitem">Mi espacio fiscal</a>
              <a href="/stats"     class="snav-dd-item snav-hidden" id="snavItemStats"          role="menuitem">Stats</a>
              <a href="/admin/asesoramiento"      class="snav-dd-item snav-hidden" id="snavItemAdminAsesoria"    role="menuitem">Panel asesoramiento</a>
              <a href="/admin/comunicaciones"     class="snav-dd-item snav-hidden" id="snavItemAdminComms"       role="menuitem">Comunicaciones</a>
              <a href="/admin/recursos"           class="snav-dd-item snav-hidden" id="snavItemAdminRecursos"    role="menuitem">Solicitudes de recursos</a>
              <a href="/mis-solicitudes-fiscales" class="snav-dd-item snav-hidden" id="snavItemMisSolicitudes"  role="menuitem">Mis solicitudes fiscales</a>
              <div class="snav-dd-divider"></div>
              <button class="snav-dd-item danger" id="snavBtnLogout" role="menuitem">Cerrar sesión</button>
            </div>
          </div>`;
  }

  // ── HTML completo del nav (fallback si el shell NO está en el HTML) ───────
  function buildFullHTML() {
    return `
      <div class="snav-inner">

        <a href="/" class="snav-logo">mariano<span>sevilla</span>.com</a>

        <ul class="snav-links">
          <li><a href="/como-funciona">Cómo funciona</a></li>
          <li><a href="/faq">FAQ</a></li>
          <li><a href="/contacto">Contacto</a></li>
        </ul>

        <div class="snav-right">
          ${buildRightHTML()}
        </div>
      </div>`;
  }

  // ── Marcar item activo según la URL actual ────────────────────────────────
  function markActive() {
    const path = window.location.pathname;

    // Dropdown items (avatar menu)
    const map = {
      '/account':                   'snavItemAccount',
      '/dashboard':                 'snavItemDash',
      '/stats':                     'snavItemStats',
      '/admin/asesoramiento':       'snavItemAdminAsesoria',
      '/admin/comunicaciones':      'snavItemAdminComms',
      '/admin/recursos':            'snavItemAdminRecursos',
      '/mis-solicitudes-fiscales':  'snavItemMisSolicitudes',
    };
    for (const [prefix, id] of Object.entries(map)) {
      if (path.startsWith(prefix)) {
        const el = document.getElementById(id);
        if (el) el.classList.add('active');
        break;
      }
    }

    // Links centrales del nav (Cómo funciona / FAQ / Contacto)
    const navLinks = document.querySelectorAll('.snav-links a');
    navLinks.forEach(function (a) {
      const href = a.getAttribute('href');
      if (!href || href === '/') return;
      if (path === href || path.startsWith(href + '/')) {
        a.classList.add('active');
      }
    });
  }

  // ── Dropdown ──────────────────────────────────────────────────────────────
  function initDropdown() {
    const avatar   = document.getElementById('snavAvatar');
    const dropdown = document.getElementById('snavDropdown');
    if (!avatar || !dropdown) return;

    avatar.addEventListener('click', function (e) {
      e.stopPropagation();
      const isOpen = dropdown.classList.toggle('open');
      avatar.setAttribute('aria-expanded', String(isOpen));
    });

    // Cerrar al hacer click fuera
    document.addEventListener('click', function () {
      dropdown.classList.remove('open');
      avatar.setAttribute('aria-expanded', 'false');
    });

    // Cerrar con Escape
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        dropdown.classList.remove('open');
        avatar.setAttribute('aria-expanded', 'false');
      }
    });
  }


  // Mobile navigation reuses the per-page links and current auth state.
  let refreshMobileMenu = function () {};

  function initMobileMenu() {
    const nav = document.getElementById('site-nav');
    const inner = nav && nav.querySelector('.snav-inner');
    if (!nav || !inner || document.getElementById('snavMenuToggle')) return;

    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.id = 'snavMenuToggle';
    toggle.className = 'snav-menu-toggle';
    toggle.setAttribute('aria-controls', 'snavMobileMenu');
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Abrir menú');
    const icon = document.createElement('span');
    icon.className = 'snav-menu-icon';
    icon.setAttribute('aria-hidden', 'true');
    toggle.appendChild(icon);
    inner.appendChild(toggle);

    const menu = document.createElement('div');
    menu.id = 'snavMobileMenu';
    menu.className = 'snav-mobile-menu';
    menu.setAttribute('role', 'navigation');
    menu.setAttribute('aria-label', 'Navegación móvil');
    menu.hidden = true;
    nav.appendChild(menu);

    function closeMenu(returnFocus) {
      if (menu.hidden) return;
      menu.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Abrir menú');
      if (returnFocus) toggle.focus();
    }

    function addLink(label, href, isPrimary, isActive) {
      const link = document.createElement('a');
      link.href = href;
      link.textContent = label;
      link.className = 'snav-mobile-link' +
        (isPrimary ? ' snav-mobile-link-primary' : '') +
        (isActive ? ' active' : '');
      menu.appendChild(link);
    }

    function addSeparator() {
      const sep = document.createElement('div');
      sep.className = 'snav-mobile-separator';
      sep.setAttribute('aria-hidden', 'true');
      menu.appendChild(sep);
    }

    refreshMobileMenu = function () {
      menu.replaceChildren();
      nav.querySelectorAll('.snav-links a').forEach(function (link) {
        addLink(link.textContent.trim(), link.getAttribute('href'), false,
          link.classList.contains('active'));
      });
      addSeparator();

      const userPanel = document.getElementById('snavAvatarWrap');
      const authenticated = userPanel && !userPanel.classList.contains('snav-hidden');

      if (authenticated) {
        const drop = document.getElementById('snavDropdown');
        if (!drop) return;
        drop.querySelectorAll('.snav-dd-item').forEach(function (item) {
          if (item.classList.contains('snav-hidden')) return;
          if (item.tagName === 'A') {
            addLink(item.textContent.trim(), item.getAttribute('href'), false,
              item.classList.contains('active'));
          } else if (item.id === 'snavBtnLogout') {
            const logout = document.createElement('button');
            logout.type = 'button';
            logout.className = 'snav-mobile-link';
            logout.textContent = item.textContent.trim();
            logout.addEventListener('click', function () { item.click(); });
            menu.appendChild(logout);
          }
        });
      } else {
        const retry = document.getElementById('snavAuthRetry');
        if (retry && !retry.classList.contains('snav-hidden')) {
          const status = document.createElement('p');
          status.className = 'snav-mobile-status';
          status.textContent = document.getElementById('snavAuthStatus').textContent;
          menu.appendChild(status);
          const button = document.createElement('button');
          button.type = 'button';
          button.id = 'snavMobileRetry';
          button.className = 'snav-mobile-link';
          button.textContent = retry.textContent;
          button.addEventListener('click', function () { retry.click(); });
          menu.appendChild(button);
          return;
        }
        const login = document.getElementById('snavBtnLogin');
        const signup = document.getElementById('snavBtnSignup');
        if (login && !login.classList.contains('snav-hidden'))
          addLink(login.textContent.trim(), login.getAttribute('href'), false, false);
        if (signup && !signup.classList.contains('snav-hidden'))
          addLink(signup.textContent.trim(), signup.getAttribute('href'), true, false);
      }
    };

    toggle.addEventListener('click', function () {
      const opening = menu.hidden;
      if (opening) refreshMobileMenu();
      menu.hidden = !opening;
      toggle.setAttribute('aria-expanded', String(opening));
      toggle.setAttribute('aria-label', opening ? 'Cerrar menú' : 'Abrir menú');
    });
    menu.addEventListener('click', function (event) {
      if (event.target.closest('a,button')) closeMenu(false);
    });
    document.addEventListener('click', function (event) {
      if (!nav.contains(event.target)) closeMenu(false);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeMenu(true);
    });
    window.addEventListener('resize', function () {
      if (window.innerWidth > 1200) closeMenu(false);
    });
    refreshMobileMenu();
  }

  // ── Logout ────────────────────────────────────────────────────────────────
  function initLogout() {
    const btn = document.getElementById('snavBtnLogout');
    if (!btn) return;
    btn.addEventListener('click', async function () {
      try {
        await fetch('/api/logout', { method: 'POST', credentials: 'include' });
      } catch (_) {}
      window.location.href = '/';
    });
  }

  // ── Actualizar estado según /api/me ───────────────────────────────────────
  async function updateAuthState() {
    // Unknown access is distinct from a confirmed anonymous session.
    const nav = document.getElementById('site-nav');
    const retry = document.getElementById('snavAuthRetry');
    const status = document.getElementById('snavAuthStatus');
    nav.dataset.authState = 'loading';
    let settled = false;
    const waiting = setTimeout(function () {
      if (settled) return;
      status.textContent = 'Seguimos comprobando tu sesión. Puedes esperar o reintentar.';
      retry.classList.remove('snav-hidden');
      document.getElementById('snavSkeleton').classList.add('snav-hidden');
      refreshMobileMenu();
    }, 8000);
    // Optional consumer contract. No account identifiers or personal data are
    // exposed; the existing server flags remain the only source of permissions.
    let result = { state: 'error', is_admin: false, is_fiscal_advisor: false };

    try {
      const r = await fetch('/api/me', { credentials: 'include' });

      if (r.ok) {
        const d = await r.json();
        if (!d || !Object.prototype.hasOwnProperty.call(d, 'user') ||
            (d.user !== null && (typeof d.user !== 'object' || Array.isArray(d.user)))) {
          throw new Error('Invalid session response');
        }
        result.state = d.user ? 'authenticated' : 'anonymous';

        if (d.user) {
          const user = d.user;
          result.is_admin = user.is_admin === true;
          result.is_fiscal_advisor = user.is_fiscal_advisor === true;

          // Mostrar avatar con la inicial correcta
          const avatarWrap = document.getElementById('snavAvatarWrap');
          const avatar     = document.getElementById('snavAvatar');
          if (avatarWrap) avatarWrap.classList.remove('snav-hidden');
          if (avatar) {
            const name = user.full_name || user.email || 'U';
            avatar.textContent = name.charAt(0).toUpperCase();
          }

          // Mostrar items según rol
          if (user.is_admin) {
            const stats           = document.getElementById('snavItemStats');
            const adminAsesoria   = document.getElementById('snavItemAdminAsesoria');
            const adminComms      = document.getElementById('snavItemAdminComms');
            const adminRecursos   = document.getElementById('snavItemAdminRecursos');
            const misSolicitudes  = document.getElementById('snavItemMisSolicitudes');
            if (stats)          stats.classList.remove('snav-hidden');
            if (adminAsesoria)  adminAsesoria.classList.remove('snav-hidden');
            if (adminComms)     adminComms.classList.remove('snav-hidden');
            if (adminRecursos)  adminRecursos.classList.remove('snav-hidden');
            if (misSolicitudes) misSolicitudes.classList.remove('snav-hidden');
          } else if (user.is_fiscal_advisor) {
            const adminAsesoria = document.getElementById('snavItemAdminAsesoria');
            if (adminAsesoria) adminAsesoria.classList.remove('snav-hidden');
          }
        }
      }

    } catch (_) {
      // Network/HTTP/JSON failures do not establish whether a session exists.
    } finally {
      settled = true;
      clearTimeout(waiting);
      const retryFocused = document.activeElement === retry ||
        document.activeElement.id === 'snavMobileRetry';
      nav.dataset.authState = result.state;
      // Ocultar skeleton siempre (tanto si hay sesión como si no)
      const skeleton = document.getElementById('snavSkeleton');
      if (skeleton) skeleton.classList.add('snav-hidden');

      // Only an explicit {user:null} response shows anonymous account links.
      if (result.state === 'anonymous') {
        const btnLogin  = document.getElementById('snavBtnLogin');
        const btnSignup = document.getElementById('snavBtnSignup');
        if (btnLogin)  btnLogin.classList.remove('snav-hidden');
        if (btnSignup) btnSignup.classList.remove('snav-hidden');
      }
      status.textContent = result.state === 'error' ? 'No podemos comprobar tu sesión. Vuelve a intentarlo.' : '';
      retry.classList.toggle('snav-hidden', result.state !== 'error');
      refreshMobileMenu();
      if (retryFocused) {
        const target = window.innerWidth <= 1200 ? document.getElementById('snavMenuToggle') :
          result.state === 'authenticated' ? document.getElementById('snavAvatar') :
          result.state === 'anonymous' ? document.getElementById('snavBtnLogin') : retry;
        if (target) target.focus({ preventScroll: true });
      }
    }
    return result;
  }

  // ── Init principal ────────────────────────────────────────────────────────
  function init() {
    const nav = document.getElementById('site-nav');
    if (!nav) return;

    const existing = nav.querySelector('.snav-inner');
    if (existing) {
      // Shell estático ya en el HTML: solo hidratar .snav-right
      // Esto garantiza que logo + links nunca desaparecen, ni un frame.
      const right = existing.querySelector('.snav-right');
      if (right) right.innerHTML = buildRightHTML();
    } else {
      // Fallback: generar el nav completo (no debería ocurrir con los HTML actualizados)
      nav.innerHTML = buildFullHTML();
    }

    markActive();
    initDropdown();
    initLogout();
    initMobileMenu();
    document.getElementById('snavAuthRetry').addEventListener('click', function () { window.location.reload(); });
    window.SiteNav.ready = updateAuthState();
  }

  // ── API pública ───────────────────────────────────────────────────────────
  window.SiteNav = {
    /** Actualiza la inicial del avatar (útil en account.html al cambiar el nombre) */
    updateAvatar: function (initial) {
      const avatar = document.getElementById('snavAvatar');
      if (avatar && initial) avatar.textContent = String(initial).charAt(0).toUpperCase();
    },
  };

  // ── Bootstrap ─────────────────────────────────────────────────────────────
  //
  // Si el script está posicionado justo después de <nav id="site-nav">,
  // el elemento ya existe en el DOM cuando este código ejecuta.
  // En ese caso init() se llama de forma síncrona — el skeleton aparece
  // al instante, sin esperar a DOMContentLoaded.
  //
  // Si por cualquier razón el nav aún no existe (script en <head>, etc.),
  // se usa el fallback estándar.
  if (document.getElementById('site-nav')) {
    init();
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

