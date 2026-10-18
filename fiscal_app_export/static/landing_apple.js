/* Home-only enhancements. No provider, payment or authentication API changes. */
(function () {
  'use strict';
  if (!document.body.classList.contains('apple-home')) return;
  // Presentation only: the shared menu copies this label when it opens.
  const signup = document.getElementById('snavBtnSignup');
  if (signup) signup.textContent = 'Crear cuenta';

  // Shared nav.js owns pending/error/anonymous access states on every page.

  // Demonstration dates follow the previous tax year in Spain. These nodes
  // belong only to the fictitious report; no user/report data is read.
  const exampleYear = Number(new Intl.DateTimeFormat('en', {
    year: 'numeric', timeZone: 'Europe/Madrid'
  }).format(new Date())) - 1;
  document.querySelectorAll('.apple-footer-year').forEach(function (year) {
    year.textContent = String(exampleYear + 1);
  });
  document.querySelectorAll('.apple-example-date').forEach(function (date) {
    const parts = date.getAttribute('datetime').split('-');
    date.setAttribute('datetime', exampleYear + '-' + parts[1] + '-' + parts[2]);
    date.textContent = parts[2] + '/' + parts[1] + '/' + exampleYear;
  });
  // A scroll hint is useful only when the example actually overflows. Observe
  // both widths so text enlargement is handled as well as viewport resizing.
  const tableWrap = document.querySelector('.mock-table-wrap');
  const tableHint = document.querySelector('.apple-table-hint');
  if (tableWrap && tableHint) {
    function updateTableHint() {
      tableHint.hidden = tableWrap.scrollWidth <= tableWrap.clientWidth + 1;
    }
    updateTableHint();
    if (typeof ResizeObserver !== 'undefined') {
      const tableObserver = new ResizeObserver(updateTableHint);
      tableObserver.observe(tableWrap);
      const table = tableWrap.querySelector('table');
      if (table) tableObserver.observe(table);
    } else {
      window.addEventListener('resize', updateTableHint);
    }
  }
  // Every card is in the initial HTML. On wide screens, place the four
  // additional cards in the same grid; mobile keeps them in native details.
  // Without JavaScript the disclosure stays open and every guide is available.
  const moreExchanges = document.getElementById('apple-exchange-more');
  if (moreExchanges) {
    const mobile = window.matchMedia('(max-width:640px)');
    const grid = moreExchanges.parentElement;
    const rest = moreExchanges.querySelector('.apple-exchange-rest');
    const secondary = rest.querySelector('.apple-exchange-secondary');
    const cards = Array.from(rest.querySelectorAll('.apple-exchange-card'));
    const summary = moreExchanges.querySelector('summary');
    function syncExchanges() {
      const focused = document.activeElement;
      if (mobile.matches) {
        if (moreExchanges.contains(focused) || cards.some(card => card.contains(focused))) {
          summary.focus({ preventScroll: true });
        }
        cards.forEach(card => rest.insertBefore(card, secondary));
        moreExchanges.open = false;
      } else {
        cards.forEach(card => grid.insertBefore(card, moreExchanges));
        moreExchanges.open = true;
        if (cards.some(card => card.contains(focused))) focused.focus({ preventScroll: true });
        else if (focused === summary) cards[0].focus({ preventScroll: true });
      }
    }
    syncExchanges();
    if (mobile.addEventListener) mobile.addEventListener('change', syncExchanges);
    else mobile.addListener(syncExchanges);
  }
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
