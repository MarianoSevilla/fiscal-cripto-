/* Home-only enhancements. No provider, payment or authentication API changes. */
(function () {
  'use strict';
  if (!document.body.classList.contains('apple-home')) return;
  const nav = document.getElementById('site-nav');
  if (nav && typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(function () {
      nav.style.setProperty('--apple-nav-height', Math.ceil(nav.getBoundingClientRect().height) + 'px');
    }).observe(nav);
  }
  const avatar = document.getElementById('snavAvatar');
  const dropdown = document.getElementById('snavDropdown');
  // This is a disclosure of native links, not an application menu widget.
  if (avatar && dropdown) {
    avatar.removeAttribute('aria-haspopup');
    avatar.setAttribute('aria-controls', 'snavDropdown');
    dropdown.removeAttribute('role');
    dropdown.querySelectorAll('[role="menuitem"]').forEach(function (item) {
      item.removeAttribute('role');
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && dropdown.classList.contains('open')) {
        requestAnimationFrame(function () { avatar.focus(); });
      }
    }, true);
  }
})();
