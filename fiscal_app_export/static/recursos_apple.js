(() => {
 'use strict';
 const nav=document.getElementById('site-nav');
 function current(){ if(nav)nav.querySelectorAll('a[href="/recursos"]').forEach(a=>a.setAttribute('aria-current','page')); }
 current(); if(nav)new MutationObserver(current).observe(nav,{childList:true,subtree:true});
 const form=document.getElementById('resource-form'); if(!form)return;
 form.hidden=false;document.getElementById('resource-nojs').hidden=true;
 const byId=id=>document.getElementById(id),btn=byId('submit-btn'),success=byId('form-success'),error=byId('form-error');
 const legal=byId('legal_accepted'),marketing=byId('marketing_consent'),uid=byId('uid'),unknown=byId('uid_unknown');
 const label=btn.textContent.trim();let pending=false;
 function update(){btn.disabled=pending||!legal.checked;}
 function fail(message,field){error.textContent=message;error.hidden=false;if(field){field.setAttribute('aria-invalid','true');field.focus();}}
 legal.addEventListener('change',update);update();
 uid.addEventListener('input',()=>uid.removeAttribute('aria-invalid'));
 unknown.addEventListener('change',()=>{uid.removeAttribute('aria-invalid');byId('uid-helper').textContent=unknown.checked?'Puedes dejarlo en blanco. Revisaremos tu situación manualmente.':'Consulta las instrucciones de tu exchange para localizar tu UID.';});
 form.addEventListener('submit',async e=>{
  e.preventDefault();if(pending)return;error.hidden=true;success.hidden=true;
  if(!form.reportValidity())return;
  if(!legal.checked){fail('Debes aceptar la política de privacidad para continuar.',legal);return;}
  if(!uid.value.trim()&&!unknown.checked){fail('Introduce tu UID o marca que no sabes dónde encontrarlo.',uid);return;}
  const payload={resource_id:Number(byId('resource_id').value),name:byId('name').value.trim(),email:byId('email').value.trim(),exchange:byId('exchange').value||null,bitvavo_status:byId('bitvavo_status').value||null,uid:uid.value.trim()||null,uid_unknown:unknown.checked,telegram_user:byId('telegram_user').value.trim()||null,legal_accepted:legal.checked,marketing_consent:marketing.checked};
  pending=true;update();btn.textContent='Enviando…';form.setAttribute('aria-busy','true');
  try{
   const res=await fetch('/api/recursos/solicitar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
   const data=await res.json();if(res.ok){form.hidden=true;success.hidden=false;success.focus();}else fail(data.error||'No hemos podido enviar la solicitud. Revisa los datos e inténtalo de nuevo.');
  }catch(_){fail('No se ha podido enviar la solicitud. Comprueba tu conexión e inténtalo de nuevo.');}
  finally{pending=false;btn.textContent=label;form.removeAttribute('aria-busy');update();}
 });
})();
