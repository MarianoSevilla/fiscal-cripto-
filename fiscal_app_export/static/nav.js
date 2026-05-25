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

          <!-- Estado NO autenticado (oculto hasta que /api/me resuelve) -->
          <a href="/login/"   class="snav-btn-login snav-hidden" id="snavBtnLogin">Iniciar sesión</a>
          <a href="/signup/"  class="snav-btn-cta   snav-hidden" id="snavBtnSignup">Crea tu cuenta gratis</a>

          <!-- Estado autenticado (oculto hasta que /api/me resuelve) -->
          <div class="snav-avatar-wrap snav-hidden" id="snavAvatarWrap">
            <button class="snav-avatar" id="snavAvatar" aria-label="Menú de usuario" aria-haspopup="true" aria-expanded="false">U</button>
            <div class="snav-dropdown" id="snavDropdown" role="menu">
              <a href="/pricing"   class="snav-dd-item snav-hidden" id="snavItemPlanes"  role="menuitem">💎&nbsp; Planes</a>
              <a href="/account"   class="snav-dd-item"             id="snavItemAccount" role="menuitem">👤&nbsp; Mi cuenta</a>
              <a href="/dashboard" class="snav-dd-item"             id="snavItemDash"    role="menuitem">⚡&nbsp; Dashboard</a>
              <a href="/stats"     class="snav-dd-item snav-hidden" id="snavItemStats"          role="menuitem">📊&nbsp; Stats</a>
              <a href="/admin/asesoramiento"      class="snav-dd-item snav-hidden" id="snavItemAdminAsesoria"    role="menuitem">🛠&nbsp; Panel asesoramiento</a>
              <a href="/admin/comunicaciones"     class="snav-dd-item snav-hidden" id="snavItemAdminComms"       role="menuitem">📢&nbsp; Comunicaciones</a>
              <a href="/mis-solicitudes-fiscales" class="snav-dd-item snav-hidden" id="snavItemMisSolicitudes"  role="menuitem">📋&nbsp; Mis solicitudes fiscales</a>
              <div class="snav-dd-divider"></div>
              <button class="snav-dd-item danger" id="snavBtnLogout" role="menuitem">↩&nbsp; Cerrar sesión</button>
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
      '/pricing':                   'snavItemPlanes',
      '/admin/asesoramiento':       'snavItemAdminAsesoria',
      '/admin/comunicaciones':      'snavItemAdminComms',
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
    // Por defecto mostramos botones (no autenticado).
    // Se pone a false si detectamos sesión activa.
    let authenticated = false;

    try {
      const r = await fetch('/api/me', { credentials: 'include' });

      if (r.ok) {
        const d = await r.json();

        if (d && d.user) {
          authenticated = true;
          const user = d.user;

          // Mostrar avatar con la inicial correcta
          const avatarWrap = document.getElementById('snavAvatarWrap');
          const avatar     = document.getElementById('snavAvatar');
          if (avatarWrap) avatarWrap.classList.remove('snav-hidden');
          if (avatar) {
            const name = user.full_name || user.email || 'U';
            avatar.textContent = name.charAt(0).toUpperCase();
          }

          // Mostrar items de admin si corresponde
          if (user.is_admin) {
            const planes          = document.getElementById('snavItemPlanes');
            const stats           = document.getElementById('snavItemStats');
            const adminAsesoria   = document.getElementById('snavItemAdminAsesoria');
            const adminComms      = document.getElementById('snavItemAdminComms');
            const misSolicitudes  = document.getElementById('snavItemMisSolicitudes');
            if (planes)         planes.classList.remove('snav-hidden');
            if (stats)          stats.classList.remove('snav-hidden');
            if (adminAsesoria)  adminAsesoria.classList.remove('snav-hidden');
            if (adminComms)     adminComms.classList.remove('snav-hidden');
            if (misSolicitudes) misSolicitudes.classList.remove('snav-hidden');
          }
        }
      }

    } catch (_) {
      // Error de red: se muestra el estado no autenticado (comportamiento correcto)
    } finally {
      // Ocultar skeleton siempre (tanto si hay sesión como si no)
      const skeleton = document.getElementById('snavSkeleton');
      if (skeleton) skeleton.classList.add('snav-hidden');

      // Mostrar botones solo si no hay sesión
      if (!authenticated) {
        const btnLogin  = document.getElementById('snavBtnLogin');
        const btnSignup = document.getElementById('snavBtnSignup');
        if (btnLogin)  btnLogin.classList.remove('snav-hidden');
        if (btnSignup) btnSignup.classList.remove('snav-hidden');
      }
    }
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
    updateAuthState();
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
