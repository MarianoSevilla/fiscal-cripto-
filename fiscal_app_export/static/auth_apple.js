'use strict';
(() => {
 const root=document.body,view=root.dataset.authView,preview=root.dataset.authPreview==='true';
 const $=id=>document.getElementById(id);
 function safeNext(value){
  if(typeof value!=='string'||value.length>2048)return '/dashboard';
  let decoded=value;
  for(let i=0;i<4;i++){
   if(!decoded.startsWith('/')||decoded.startsWith('//')||/[\\\s\u0000-\u001f\u007f]/.test(decoded))return '/dashboard';
   let u;try{u=new URL(decoded,location.origin)}catch{return '/dashboard'}
   if(u.origin!==location.origin||['/login','/signup','/auth/google','/auth/google/callback'].includes(u.pathname.replace(/\/$/,'')))return '/dashboard';
   let next;try{next=decodeURIComponent(decoded)}catch{return '/dashboard'}
   if(next===decoded)return value;decoded=next;
  }
  return '/dashboard';
 }
 const next=safeNext(new URLSearchParams(location.search).get('next'));
 document.querySelectorAll('[data-auth-next]').forEach(a=>{
  if(!preview){const u=new URL(a.getAttribute('href'),location.origin);u.searchParams.set('next',next);a.href=u.pathname+u.search}
 });
 const error=$('authError'),status=$('authStatus'),form=$('authForm'),submit=$('authSubmit');
 function message(el,text){el.textContent=text;el.hidden=false;el.focus()}
 function clear(){error.hidden=true;status.hidden=true;document.querySelectorAll('[aria-invalid=true]').forEach(e=>e.removeAttribute('aria-invalid'));document.querySelectorAll('.auth-field-error').forEach(e=>{e.textContent='';e.hidden=true})}
 function invalid(input,text){input.setAttribute('aria-invalid','true');const out=$(input.id+'Error');out.textContent=text;out.hidden=false;input.focus();return false}
 function validate(){
  const name=$('authName'),email=$('authEmail'),pass=$('authPassword'),confirm=$('authConfirm');
  if(name&&!name.value.trim())return invalid(name,'Introduce tu nombre y apellidos.');
  if(email&&(!email.value.trim()||!email.validity.valid))return invalid(email,'Introduce un correo electrónico válido.');
  if(pass){
   const min=view==='login'?1:15;
   if(pass.value.length<min)return invalid(pass,view==='login'?'Introduce tu contraseña.':'Usa al menos 15 caracteres.');
   if(new TextEncoder().encode(pass.value).length>72)return invalid(pass,'La contraseña es demasiado larga. Prueba una frase más corta.');
  }
  if(confirm&&confirm.value!==pass.value)return invalid(confirm,'Las contraseñas no coinciden.');
  return true;
 }
 document.querySelectorAll('.auth-reveal').forEach(button=>button.addEventListener('click',()=>{
  const input=$(button.getAttribute('aria-controls')),show=input.type==='password';input.type=show?'text':'password';button.textContent=show?'Ocultar':'Mostrar';button.setAttribute('aria-pressed',String(show));
 }));
 async function post(path,payload){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  try{
   const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});
   let data;try{data=await response.json()}catch{throw new Error('No hemos podido completar la solicitud. Inténtalo de nuevo.');}
   if(!response.ok)throw new Error(response.status===429?'Has realizado demasiados intentos. Espera antes de volver a intentarlo.':data.error||'No hemos podido completar la solicitud. Inténtalo de nuevo.');
   return data;
  }finally{clearTimeout(timer)}
 }
 function failure(e){message(error,e.name==='AbortError'?'La solicitud está tardando demasiado. Vuelve a intentarlo.':e instanceof TypeError?'No hemos podido conectar. Comprueba tu conexión e inténtalo de nuevo.':e.message)}
 function previewNotice(){message(status,'Esta vista previa no inicia sesiones ni crea cuentas.');}
 const google=document.querySelector('.auth-google');
 if(preview&&google)google.addEventListener('click',e=>{e.preventDefault();previewNotice()});
 if(form&&view!=='verify')form.addEventListener('submit',async e=>{
  e.preventDefault();clear();if(!validate())return;if(preview){previewNotice();return;}
  submit.disabled=true;form.setAttribute('aria-busy','true');const caption=submit.textContent;submit.textContent='Un momento';
  const email=$('authEmail')?.value.trim().toLowerCase(),password=$('authPassword')?.value;
  try{
   if(view==='login'){
    const d=await post('/api/login',{email,password,next});
    location.assign(d.pending_verification?'/verify-email-result?status=pending&next='+encodeURIComponent(next):safeNext(d.redirect_to||next));
   }else if(view==='signup'){
    const d=await post('/api/register',{email,password,full_name:$('authName').value.trim(),next});
    form.hidden=true;document.querySelectorAll('[data-auth-entry]').forEach(e=>e.hidden=true);
    $('authHeading').textContent='Revisa tu correo';$('authDescription').textContent=d.message;
    $('authResend').hidden=false;$('authResend').dataset.email=email;
    message(status,'Revisa también la carpeta de spam. El enlace de verificación caduca en 24 horas.');
   }else if(view==='forgot'){
    const d=await post('/api/forgot-password',{email,next});form.reset();message(status,d.message);
   }else if(view==='reset'){
    const token=location.pathname.split('/').filter(Boolean).pop();
    const d=await post('/api/reset-password',{token,password,confirm_password:$('authConfirm').value});
    form.reset();form.hidden=true;message(status,d.message);$('authContinue').hidden=false;
   }
  }catch(err){failure(err)}finally{submit.disabled=false;submit.textContent=caption;form.removeAttribute('aria-busy')}
 });
 const resend=$('authResend');
 if(resend)resend.addEventListener('click',async()=>{
  clear();if(preview){previewNotice();return;}
  let email=resend.dataset.email||$('authEmail')?.value.trim().toLowerCase();
  if(!email){message(error,'Introduce el correo de tu cuenta para solicitar otro enlace.');return;}
  resend.disabled=true;
  try{const d=await post('/api/resend-verification',{email,next});message(status,d.message)}catch(e){failure(e)}finally{resend.disabled=false}
 });
 if(view==='verify'){
  const state=new URLSearchParams(location.search).get('status')||'pending';
  const texts={success:['Correo verificado','Ya puedes iniciar sesión y continuar.'],already:['Tu correo ya está verificado','Inicia sesión con tu método habitual.'],expired:['El enlace ha caducado','Solicita un nuevo enlace de verificación.'],invalid:['Este enlace no es válido','Solicita un nuevo enlace para verificar tu correo.'],pending:['Verifica tu correo','Abre el enlace que te hemos enviado. Si no lo encuentras, revisa la carpeta de spam o solicita otro.']};
  const [title,description]=texts[state]||texts.invalid;$('authHeading').textContent=title;$('authDescription').textContent=description;
  const done=['success','already'].includes(state);if(form)form.hidden=done;$('authContinue').hidden=!done;
 }
 const params=new URLSearchParams(location.search);
 if(params.has('error'))message(error,params.get('error')==='identity_conflict'?'No se puede completar el acceso con Google. Utiliza tu método habitual o recupera la contraseña.':'No hemos podido completar el acceso con Google. Inténtalo de nuevo o utiliza tu correo y contraseña.');
 if(view==='verify'&&form)form.addEventListener('submit',async e=>{
  e.preventDefault();clear();if(!validate())return;if(preview){previewNotice();return;}
  submit.disabled=true;try{const d=await post('/api/resend-verification',{email:$('authEmail').value.trim().toLowerCase(),next});message(status,d.message)}catch(err){failure(err)}finally{submit.disabled=false}
 });
 // Login/registration are never performed automatically in the static viewer.
 if(!preview&&['login','signup'].includes(view))fetch('/api/me',{credentials:'same-origin'}).then(r=>r.ok?r.json():null).then(d=>{if(d?.user)location.replace(next)}).catch(()=>{});
})();
