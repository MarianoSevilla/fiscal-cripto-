/* Contact controller. Preview mode never sends form data or loads Turnstile. */
(function(){
 'use strict';
 const form=document.getElementById('contactForm');if(!form)return;
 const preview=form.dataset.contactMode!=='live';
 const fields=['nombre','email','tipo','mensaje','legal'];
 const controls=Object.fromEntries(fields.map(id=>[id,document.getElementById(id)]));
 const fieldset=document.getElementById('contactFields'),btn=document.getElementById('contactSubmit');
 const summary=document.getElementById('contactErrors'),errorList=document.getElementById('contactErrorList');
 const status=document.getElementById('contactStatus'),security=document.getElementById('contactSecurity');
 const securityNote=document.getElementById('contactSecurityNote'),retry=document.getElementById('contactSecurityRetry');
 const count=document.getElementById('contactCount');
 let sending=false,token='',widgetId=null,widgetSize=null;
 function message(text){status.textContent=text;status.hidden=false;}
 function clearErrors(){summary.hidden=true;errorList.replaceChildren();fields.forEach(id=>{controls[id].removeAttribute('aria-invalid');const e=document.getElementById(id+'Error');e.textContent='';e.hidden=true;});}
 function errors(items){
  summary.hidden=false;errorList.replaceChildren();
  for(const [id,text]of items){const li=document.createElement('li');
   if(id){controls[id].setAttribute('aria-invalid','true');const e=document.getElementById(id+'Error');e.textContent=text;e.hidden=false;const a=document.createElement('a');a.href='#'+id;a.textContent=text;a.addEventListener('click',ev=>{ev.preventDefault();controls[id].focus();});li.append(a);}
   else li.textContent=text;errorList.append(li);
  }
  if(items[0][0])controls[items[0][0]].focus();else summary.focus();
 }
 function validate(){
  const out=[],name=controls.nombre.value.trim(),email=controls.email.value.trim(),text=controls.mensaje.value.trim();
  if(!name||name.length>80)out.push(['nombre','Escribe tu nombre (máximo 80 caracteres).']);
  if(!email||email.length>254||controls.email.validity.typeMismatch||!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))out.push(['email','Escribe una dirección de email válida.']);
  if(!controls.tipo.value)out.push(['tipo','Selecciona el tipo de consulta.']);
  if(text.length<20||text.length>3000)out.push(['mensaje','Describe tu consulta con entre 20 y 3000 caracteres.']);
  if(!controls.legal.checked)out.push(['legal','Confirma que has leído la información sobre protección de datos.']);
  return out;
 }
 controls.mensaje.addEventListener('input',()=>{count.textContent=String(controls.mensaje.value.length);});
 const advice=document.getElementById('contactAdviceHint');
 controls.tipo.addEventListener('change',()=>{advice.hidden=controls.tipo.value!=='asistencia_fiscal';});
 function securityState(text,canRetry=false){token='';securityNote.textContent=text;retry.hidden=!canRetry;}
 function resetSecurity(){
  if(preview)return;
  if(window.turnstile&&widgetId!==null&&widgetSize!==securitySize()){renderSecurity();return;}
  securityState('Completando la verificación de seguridad…');
  if(window.turnstile&&widgetId!==null){try{window.turnstile.reset(widgetId);}catch{securityState('No se ha podido reiniciar la verificación. Puedes escribirnos por email.',true);}}
  else securityState('La verificación no está disponible. Recarga la página o escríbenos por email.');
 }
 retry.addEventListener('click',resetSecurity);
 function securitySize(){return document.getElementById('contactTurnstile').clientWidth<300?'compact':'flexible';}
 function renderSecurity(){
  if(sending)return;
  const size=securitySize();
  if(widgetId!==null&&widgetSize===size)return;
  if(widgetId!==null){window.turnstile.remove(widgetId);widgetId=null;}
  widgetSize=size;securityState('Completando la verificación de seguridad…');
  widgetId=window.turnstile.render('#contactTurnstile',{
   sitekey:form.dataset.sitekey,theme:'light',size,
   callback:value=>{token=value;securityNote.textContent='Verificación completada.';retry.hidden=true;},
   'expired-callback':()=>securityState('La verificación ha caducado. Vuelve a verificar antes de enviar.',true),
   'timeout-callback':()=>securityState('La verificación no ha terminado. Puedes volver a intentarlo.',true),
   'error-callback':()=>{securityState('No se ha podido completar la verificación. Puedes reintentar o escribirnos por email.',true);return true;}
  });
 }
 function loadSecurity(){
  if(preview){security.hidden=true;return;}
  security.hidden=false;securityNote.textContent='Completando la verificación de seguridad…';
  const script=document.createElement('script');script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';script.async=true;script.defer=true;
  script.onerror=()=>securityState('No se ha podido cargar la verificación. Recarga la página o escríbenos por email.');
  script.onload=()=>{try{
   renderSecurity();
   if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>{
    if(!sending&&widgetSize!==securitySize()){
     try{renderSecurity();}catch{securityState('La verificación no está disponible. Recarga la página o escríbenos por email.');}
    }
   }).observe(document.getElementById('contactTurnstile'));
  }catch{securityState('La verificación no está disponible. Recarga la página o escríbenos por email.');}};
  document.head.append(script);
 }
 form.addEventListener('submit',async event=>{
  event.preventDefault();if(sending)return;
  clearErrors();status.hidden=true;const invalid=validate();if(invalid.length){errors(invalid);return;}
  if(preview){message('Datos validados. En esta vista de revisión no se ha enviado el mensaje.');status.focus();return;}
  if(!token){errors([[null,'Completa la verificación de seguridad antes de enviar. Tu mensaje sigue en el formulario.']]);return;}
  const payload={nombre:controls.nombre.value.trim(),email:controls.email.value.trim(),tipo_consulta:controls.tipo.value,mensaje:controls.mensaje.value.trim(),website:form.elements.website.value,ts_token:token};
  sending=true;btn.disabled=true;fieldset.disabled=true;form.setAttribute('aria-busy','true');btn.textContent='Enviando…';message('Enviando tu mensaje…');
  try{
   const response=await fetch('/api/contacto',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify(payload)});
   let data=null;try{data=await response.json();}catch{}
   if(response.ok&&data&&data.ok){form.reset();count.textContent='0';advice.hidden=true;message('Mensaje recibido. Te responderemos por email lo antes posible.');status.focus();}
   else{
    status.hidden=true;
    let text='No se ha podido confirmar el envío. Conservamos lo que has escrito. Puedes reintentar o escribirnos por email.';
    if(response.status===429)text='Has realizado varios intentos. Espera antes de volver a enviar; tu mensaje sigue en el formulario.';
    else if(response.status===400)text=(data&&typeof data.error==='string'?data.error:'Revisa los datos y la verificación antes de reintentar.')+' Tu mensaje sigue en el formulario.';
    errors([[null,text]]);
   }
  }catch{status.hidden=true;errors([[null,'No hemos podido confirmar la recepción por un problema de conexión. Tu texto se conserva. No reenviaremos automáticamente el mensaje; puedes reintentar o escribirnos por email.']]);}
  finally{sending=false;btn.disabled=false;fieldset.disabled=false;form.removeAttribute('aria-busy');btn.textContent='Enviar mensaje';resetSecurity();}
 });
 // Listener registered before enabling fields: a failed script cannot submit via GET.
 fieldset.disabled=false;btn.disabled=false;document.getElementById('contactBootNotice').hidden=true;loadSecurity();
})();
