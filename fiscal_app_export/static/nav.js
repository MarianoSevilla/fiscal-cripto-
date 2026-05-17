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

  // ── HTML del nav ──────────────────────────────────────────────────────────
  function buildHTML() {
    return `
      <div class="snav-inner">

        <a href="/" class="snav-logo">mariano<span>sevilla</span>.com</a>

        <ul class="snav-links">
          <li><a href="/#como-funciona">Cómo funciona</a></li>
          <li><a href="/faq">FAQ</a></li>
          <li><a href="/contacto">Contacto</a></li>
        </ul>

        <div class="snav-right">

          <!-- Estado NO autenticado -->
          <a href="/login/"   class="snav-btn-login" id="snavBtnLogin">Iniciar sesión</a>
          <a href="/signup/"  class="snav-btn-cta"   id="snavBtnSignup">Crea tu cuenta gratis</a>

          <!-- Estado autenticado -->
          <div class="snav-avatar-wrap snav-hidden" id="snavAvatarWrap">
            <button class="snav-avatar" id="snavAvatar" aria-label="Menú de usuario" aria-haspopup="true" aria-expanded="false">U</button>
            <div class="snav-dropdown" id="snavDropdown" role="menu">
              <a href="/pricing"   class="snav-dd-item snav-hidden" id="snavItemPlanes"  role="menuitem">💎&nbsp; Planes</a>
              <a href="/account"   class="snav-dd-item"             id="snavItemAccount" role="menuitem">👤&nbsp; Mi cuenta</a>
              <a href="/dashboard" class="snav-dd-item"             id="snavItemDash"    role="menuitem">⚡&nbsp; Dashboard</a>
              <a href="/stats"     class="snav-dd-item snav-hidden" id="snavItemStats"   role="menuitem">📊&nbsp; Stats</a>
              <div class="snav-dd-divider"></div>
              <button class="snav-dd-item danger" id="snavBtnLogout" role="menuitem">↩&nbsp; Cerrar sesión</button>
            </div>
          </div>

        </div>
      </div>`;
  }

  // ── Marcar item activo según la URL actual ────────────────────────────────
  function markActive() {
    const path = window.location.pathname;
    const map = {
      '/account':   'snavItemAccount',
      '/dashboard': 'snavItemDash',
      '/stats':     'snavItemStats',
      '/pricing':   'snavItemPlanes',
    };
    for (const [prefix, id] of Object.entries(map)) {
      if (path.startsWith(prefix)) {
        const el = document.getElementById(id);
        if (el) el.classList.add('active');
        break;
      }
    }
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
    try {
      const r = await fetch('/api/me', { credentials: 'include' });
      if (!r.ok) return; // no autenticado — estado por defecto (botones login/signup)
      const d = await r.json();
      if (!d || !d.user) return;

      const user = d.user;

      // Ocultar botones no autenticado
      const btnLogin  = document.getElementById('snavBtnLogin');
      const btnSignup = document.getElementById('snavBtnSignup');
      if (btnLogin)  btnLogin.classList.add('snav-hidden');
      if (btnSignup) btnSignup.classList.add('snav-hidden');

      // Mostrar avatar con la inicial correcta
      const avatarWrap = document.getElementById('snavAvatarWrap');
      const avatar     = document.getElementById('snavAvatar');
      if (avatarWrap) avatarWrap.classList.remove('snav-hidden');
      if (avatar) {
        const name    = user.full_name || user.email || 'U';
        avatar.textContent = name.charAt(0).toUpperCase();
      }

      // Mostrar items de admin si corresponde
      if (user.is_admin) {
        const planes = document.getElementById('snavItemPlanes');
        const stats  = document.getElementById('snavItemStats');
        if (planes) planes.classList.remove('snav-hidden');
        if (stats)  stats.classList.remove('snav-hidden');
      }

    } catch (_) {
      // Error de red: no hacemos nada, se muestra el estado no autenticado
    }
  }

  // ── Init principal ────────────────────────────────────────────────────────
  function init() {
    const nav = document.getElementById('site-nav');
    if (!nav) return;

    nav.innerHTML = buildHTML();
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
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
