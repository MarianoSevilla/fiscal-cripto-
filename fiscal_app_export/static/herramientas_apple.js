/* Presentation only. nav.js still owns authentication, roles and menu actions. */
(function () {
 'use strict';
 if (!document.body.classList.contains('apple-tools')) return;
 const nav = document.getElementById('site-nav');
 if (!nav) return;
 function markCurrentPage() {
  nav.querySelectorAll('a[href="/herramientas"]').forEach(function (link) {
   link.setAttribute('aria-current', 'page');
   link.classList.add('active');
  });
 }
 markCurrentPage();
 new MutationObserver(markCurrentPage).observe(nav, { childList:true, subtree:true });
})();
