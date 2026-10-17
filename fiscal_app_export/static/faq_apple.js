/* Progressive enhancement: native details work without JavaScript. */
(function(){
 'use strict';
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
