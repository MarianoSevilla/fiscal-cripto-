/* Progressive enhancement: native details work without JavaScript. */
(function(){
 'use strict';
 // The shared menu recreates its links on session changes and opening.
 const nav=document.getElementById('site-nav');
 function markCurrent(){
  if(nav)nav.querySelectorAll('a[href]').forEach(function(link){
   if(new URL(link.getAttribute('href'),location.href).pathname==='/faq')link.setAttribute('aria-current','page');
  });
 }
 markCurrent();
 if(nav)new MutationObserver(markCurrent).observe(nav,{childList:true,subtree:true});
 function openAnchor(){
  let id;try{id=decodeURIComponent(location.hash.slice(1));}catch(_){return;}
  if(!id)return;
  const target=document.getElementById(id);
  if(!target||!target.matches('.apple-faq-item'))return;
  target.open=true;
  target.scrollIntoView({block:'start'});
 }
 window.addEventListener('hashchange',openAnchor);
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',openAnchor);
 else openAnchor();
})();
