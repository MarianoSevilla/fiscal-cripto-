/* Presentation only; nav.js owns authentication, roles and menu actions. */
(function () {
 'use strict';
 if (!document.body.classList.contains('apple-how-page')) return;
 const nav=document.getElementById('site-nav');
 if (!nav) return;
 function markCurrentPage() {
  nav.querySelectorAll('a[href="/como-funciona"]').forEach(function (link) {
   link.setAttribute('aria-current','page');
   link.classList.add('active');
  });
 }
 markCurrentPage();
 new MutationObserver(markCurrentPage).observe(nav,{childList:true,subtree:true});
})();
