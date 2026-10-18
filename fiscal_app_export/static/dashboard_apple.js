/* Presentation and discovery only. Shared navigation owns session and roles. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id),body=document.body;
 const workspace=$('dashWorkspace'),access=$('dashAccess'),retry=$('dashRetry'),resume=$('dashResume');
 const dashItem=$('snavItemDash');
 if(dashItem)dashItem.setAttribute('aria-current','page');
 let settled=false;
 const waiting=setTimeout(()=>{
  if(settled)return;
  $('dashAccessTitle').textContent='Seguimos comprobando tu sesión';
  $('dashAccessDescription').textContent='La comprobación está tardando más de lo habitual. Puedes esperar o volver a comprobarla.';
  retry.hidden=false;
 },8000);
 function state(result){
  settled=true;clearTimeout(waiting);
  const ready=result&&result.state==='authenticated';
  body.dataset.dashboardState=ready?'ready':result?.state==='anonymous'?'expired':'error';
  workspace.hidden=!ready;
  access.hidden=ready;
  if(!ready){
   const expired=body.dataset.dashboardState==='expired';
   $('dashAccessTitle').textContent=expired?'Tu sesión ha finalizado':'No podemos comprobar tu sesión';
   $('dashAccessDescription').textContent=expired?'Vuelve a iniciar sesión para acceder a tus herramientas.':'Comprueba tu conexión y vuelve a intentarlo. Tus herramientas aparecerán cuando podamos confirmar el acceso.';
   resume.hidden=!expired;retry.hidden=expired;
   return;
  }
  $('dashSearchWrap').hidden=false;
  const links=$('dashRoleLinks');
  for(const id of ['snavItemAdminAsesoria','snavItemStats','snavItemAdminComms','snavItemAdminRecursos','snavItemMisSolicitudes']){
   const original=$(id);
   if(!original||original.classList.contains('snav-hidden'))continue;
   const li=document.createElement('li'),a=document.createElement('a');
   a.href=original.getAttribute('href');a.textContent=original.textContent;li.append(a);links.append(li);
  }
  if(result.is_admin===true){
   const li=document.createElement('li'),a=document.createElement('a');
   a.href='/admin/contactos';a.textContent='Contactos';li.append(a);links.append(li);
  }
  $('dashManagement').hidden=!links.children.length;
 }
 retry.addEventListener('click',()=>location.reload());
 Promise.resolve(window.SiteNav?.ready).then(state).catch(()=>state(null));
 // Revalidate when returning from a cached authenticated page.
 window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
 const input=$('dashSearch'),clear=$('dashSearchClear'),cards=[...document.querySelectorAll('[data-exchange-name]')];
 const normalize=text=>text.toLocaleLowerCase('es').normalize('NFD').replace(/[\u0300-\u036f]/g,'');
 function filter(){
  const query=normalize(input.value.trim());let count=0;
  for(const card of cards){card.hidden=!!query&&!normalize(card.dataset.exchangeName).includes(query);if(!card.hidden)count++;}
  clear.hidden=!input.value; $('dashEmpty').hidden=count>0;
  $('dashCount').textContent=count===1?'1 exchange disponible':count+' exchanges disponibles';
 }
 input.addEventListener('input',filter);
 clear.addEventListener('click',()=>{input.value='';filter();input.focus();});
 document.querySelector('a[href="#fifo"]')?.addEventListener('click',()=>requestAnimationFrame(()=>$('fifo').focus({preventScroll:true})));
 document.querySelectorAll('.apple-footer-year').forEach(el=>{el.textContent=new Intl.DateTimeFormat('en',{year:'numeric',timeZone:'Europe/Madrid'}).format(new Date());});
})();
