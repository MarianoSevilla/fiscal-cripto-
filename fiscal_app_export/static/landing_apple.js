/* Home-only enhancements. No provider, payment or authentication API changes. */
(function () {
  'use strict';
  if (!document.body.classList.contains('apple-home')) return;
  // Presentation only: the shared menu copies this label when it opens.
  const signup = document.getElementById('snavBtnSignup');
  if (signup) signup.textContent = 'Crear cuenta';

  // A delayed session lookup must not block public navigation. This fallback
  // adds ordinary links only; the shared script still owns session and roles.
  const accessNav = document.getElementById('site-nav');
  const skeleton = document.getElementById('snavSkeleton');
  const login = document.getElementById('snavBtnLogin');
  const accessRight = accessNav && accessNav.querySelector('.snav-right');
  if (accessNav && skeleton && login && signup && accessRight &&
      !skeleton.classList.contains('snav-hidden') && typeof MutationObserver !== 'undefined') {
    const fallbacks = [];
    let fallbackTimer;
    let fallbackFocus = null;
    function trackFallbackFocus(event) {
      const entry = fallbacks.find(item => item.node.contains(event.target));
      fallbackFocus = entry ? { entry: entry, link: event.target } : null;
    }
    document.addEventListener('focusin', trackFallbackFocus);
    function attachFallbacks() {
      const lostFocus = fallbackFocus && document.activeElement === document.body &&
        !accessNav.contains(fallbackFocus.link) ? fallbackFocus.link : null;
      fallbacks.forEach(function (entry) {
        if (entry.node.parentElement !== entry.parent) entry.parent.appendChild(entry.node);
      });
      if (lostFocus) lostFocus.focus({ preventScroll: true });
    }
    const accessObserver = new MutationObserver(function () {
      if (!skeleton.classList.contains('snav-hidden')) {
        attachFallbacks();
        return;
      }
      clearTimeout(fallbackTimer);
      accessObserver.disconnect();
      const focused = document.activeElement;
      const previous = focused === document.body && fallbackFocus &&
        !accessNav.contains(fallbackFocus.link) ? fallbackFocus : null;
      const entry = fallbacks.find(item => item.node.contains(focused)) || (previous && previous.entry);
      const href = entry && (previous ? previous.link : focused).getAttribute('href');
      document.removeEventListener('focusin', trackFallbackFocus);
      fallbacks.forEach(item => item.node.remove());
      accessNav.classList.remove('apple-access-waiting');
      if (entry) {
        const panel = document.getElementById('snavAvatarWrap');
        const authenticated = panel && !panel.classList.contains('snav-hidden');
        let target;
        if (authenticated) target = document.getElementById(entry.mobile ? 'snavMenuToggle' : 'snavAvatar');
        else if (entry.mobile) {
          target = Array.from(entry.parent.querySelectorAll('a')).find(link => link.getAttribute('href') === href);
        } else target = href === login.getAttribute('href') ? login : signup;
        if (target) target.focus({ preventScroll: true });
      }
    });
    accessObserver.observe(accessNav, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] });
    fallbackTimer = setTimeout(function () {
      if (skeleton.classList.contains('snav-hidden')) return;
      const mobileMenu = document.getElementById('snavMobileMenu');
      [accessRight, mobileMenu].filter(Boolean).forEach(function (parent) {
        const mobile = parent === mobileMenu;
        const node = document.createElement('div');
        node.className = 'apple-access-fallback ' + (mobile ? 'apple-access-mobile' : 'apple-access-desktop');
        [login, signup].forEach(function (original, index) {
          const link = document.createElement('a');
          link.href = original.getAttribute('href');
          link.textContent = original.textContent;
          link.className = mobile ? 'snav-mobile-link' + (index ? ' snav-mobile-link-primary' : '') : original.className.replace('snav-hidden', '').trim();
          node.appendChild(link);
        });
        fallbacks.push({ node: node, parent: parent, mobile: mobile });
      });
      attachFallbacks();
      accessNav.classList.add('apple-access-waiting');
    }, 4000);
  }

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
