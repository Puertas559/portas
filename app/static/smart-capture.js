(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const EVENT_NAME = 'FESQUA 2026';
  const state = {
    imageFile:null, ocrText:'', lookup:null, saved:null, step:1,
    cameraStream:null, cameraMode:null, qrLoop:0, qrServerBusy:false,
    barcodeDetector:null, lastQrServerAt:0, cameraStartedAt:0,
  };
  const esc = (v='') => String(v).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const onlyDigits = (v='') => String(v).replace(/\D/g,'');
  const dialog = $('smartCaptureDialog');
  if (!dialog) return;

  function field(name){ return dialog.querySelector(`[data-card-field="${name}"]`); }
  function getField(name){ return field(name)?.value?.trim() || ''; }
  function setField(name,val,{overwrite=false}={}){ if(val && field(name) && (overwrite || !field(name).value)) field(name).value=val; }
  function collectContact(){ return Object.fromEntries(['name','role','company','email','phone','whatsapp','website','social','registrationId','sector','city','department','country'].map(k=>[k,getField(k)])); }

  function showStep(n){
    state.step=n;
    dialog.querySelectorAll('.capture-step').forEach(el=>el.classList.toggle('active', Number(el.dataset.step)===n));
    updateActions();
  }
  function updateActions(){
    const back=$('smartCaptureBack'), next=$('smartCaptureNext'), save=$('smartCaptureSave');
    back.hidden=state.step===1 || state.step===4;
    next.hidden=state.step>=3;
    save.hidden=state.step!==3;
  }
  function resetCapture(){
    state.imageFile=null; state.ocrText=''; state.lookup=null; state.saved=null;
    dialog.querySelectorAll('[data-card-field]').forEach(el=>{ if(el.dataset.cardField!=='country') el.value=''; });
    dialog.querySelectorAll('.capture-field-low').forEach(el=>el.classList.remove('capture-field-low'));
    const preview=$('cardPreview'); if(preview){ preview.removeAttribute('src'); preview.classList.remove('show'); }
    const status=$('ocrStatus'); if(status) status.textContent='Use a câmera, leia um QR ou preencha os dados abaixo.';
    const prog=$('ocrProgress'); if(prog) prog.hidden=true;
  }
  function openCapture({reset=false}={}){
    if(reset) resetCapture();
    state.step=1; state.saved=null; $('smartCaptureSuccess').innerHTML=''; showStep(1);
    if(!dialog.open) dialog.showModal();
  }
  function closeCapture(){ stopCamera(); if(dialog.open) dialog.close(); }
  $('openSmartCapture')?.addEventListener('click', ()=>openCapture({reset:true}));
  $('openSmartCaptureFloating')?.addEventListener('click', ()=>openCapture({reset:true}));
  $('closeSmartCapture')?.addEventListener('click', closeCapture);
  $('smartCaptureBack')?.addEventListener('click', ()=>showStep(Math.max(1,state.step-1)));
  $('smartCaptureNext')?.addEventListener('click', ()=>{
    if(state.step===1){
      if(!getField('name')&&!getField('company')&&!getField('email')&&!getField('whatsapp')&&!getField('website')&&!getField('registrationId')&&!getField('social')){
        window.toast?.('Capture ou informe ao menos um dado do contato'); return;
      }
      renderReview();
      showStep(2);
      // External enrichment is intentionally non-blocking: the seller keeps moving while it runs.
      resolveCapture();
    } else if(state.step===2) showStep(3);
  });

  function validEmail(v=''){ return /^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/.test(v.trim()); }
  function domainFromEmail(v=''){ return validEmail(v) ? v.trim().split('@')[1].toLowerCase().replace(/^www\./,'') : ''; }
  function validWebsite(v=''){
    const raw=v.trim(); if(!raw || raw.includes('@')) return '';
    try{
      const url=new URL(/^https?:\/\//i.test(raw)?raw:`https://${raw}`);
      const host=url.hostname.replace(/^www\./,'');
      return host.includes('.') && /^[a-z0-9.-]+$/i.test(host) ? url.href.replace(/\/$/,'') : '';
    }catch(_){ return ''; }
  }
  function corporateDomain(email=''){
    const d=domainFromEmail(email);
    const publicMail=new Set(['gmail.com','hotmail.com','outlook.com','yahoo.com','icloud.com','live.com','uol.com.br','terra.com.br']);
    return d && !publicMail.has(d) ? d : '';
  }
  function textLooksReliable(v=''){
    const s=v.trim(); if(!s) return false;
    const letters=[...s].filter(c=>/\p{L}/u.test(c)).length;
    const weird=[...s].filter(c=>!/\p{L}|\p{N}|\s|[-'&.,]/u.test(c)).length;
    return letters>=3 && weird/Math.max(1,s.length)<.18;
  }
  function normalizeOcrValues(values={}){
    const out={...values};
    if(out.email && !validEmail(out.email)) out.email='';
    if(out.website){ out.website=validWebsite(out.website); }
    if(!out.website && out.email){ const d=corporateDomain(out.email); if(d) out.website=`https://${d}`; }
    if(out.social && out.email && out.social.replace(/^@/,'').toLowerCase()===domainFromEmail(out.email).split('.')[0]) out.social='';
    if(out.name && !textLooksReliable(out.name)) out.name='';
    if(out.company && !textLooksReliable(out.company)) out.company='';
    return out;
  }
  function markConfidence(confidence={}, values={}){
    dialog.querySelectorAll('.capture-field-low').forEach(el=>el.classList.remove('capture-field-low'));
    const important=['name','company'];
    important.forEach(k=>{
      const f=field(k); if(!f) return;
      const score=Number(confidence[k]||0);
      if(values[k] && score && score<.58) f.closest('label')?.classList.add('capture-field-low');
    });
  }

  function parseCardText(text){
    const lines=text.split(/\n+/).map(x=>x.trim()).filter(Boolean);
    const email=(text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)||[])[0]||'';
    const withoutEmail=email?text.replace(email,' '):text;
    const urls=(withoutEmail.match(/(?:https?:\/\/)?(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:\/\S*)?/ig)||[]).filter(x=>!x.includes('@')).map(validWebsite).filter(Boolean);
    const phoneMatches=text.match(/(?:\+?\d[\d\s().-]{7,}\d)/g)||[];
    const phones=phoneMatches.map(x=>x.trim()).filter(x=>onlyDigits(x).length>=8&&onlyDigits(x).length<=15).sort((a,b)=>onlyDigits(b).length-onlyDigits(a).length);
    const cnpj=(text.match(/\b\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}\b/)||[])[0]||'';
    const social=(withoutEmail.match(/(?:instagram|linkedin|facebook|tiktok)\s*[:@]?\s*(@?[A-Z0-9._-]{3,})/i)||[])[1]||'';
    const roleWords=/gerente|diretor|director|comercial|ventas|sales|engenheir|ingenier|compras|procurement|ceo|owner|propriet|socio|sócio|representante|coordenador|coordinador/i;
    const roleLine=lines.find(x=>roleWords.test(x))||'';
    const candidates=lines.filter(x=>!x.includes('@')&&!/www\.|https?:|\d{4,}/i.test(x)&&x.length>2&&x.length<70&&textLooksReliable(x));
    const nameLine=candidates.find(x=>x!==roleLine && x.split(/\s+/).length>=2 && x.split(/\s+/).length<=5)||'';
    const companyLine=candidates.find(x=>x!==nameLine&&x!==roleLine&&/(ltda|s\.a\.?|sa\b|doors|portas|puertas|indust|group|grupo|technology|tecnologia|sistemas|alumin|esquadr|company|co\.?\s?ltd)/i.test(x)) || '';
    const website=urls[0] || (corporateDomain(email)?`https://${corporateDomain(email)}`:'');
    return normalizeOcrValues({name:nameLine,role:roleLine,company:companyLine,email,phone:phones[0]||'',whatsapp:phones[0]||'',website,social:social||'',registrationId:cnpj});
  }

  async function ensureTesseract(){
    if(window.Tesseract) return window.Tesseract;
    await new Promise((resolve,reject)=>{ const s=document.createElement('script'); s.src='https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js'; s.onload=resolve; s.onerror=reject; document.head.appendChild(s); });
    return window.Tesseract;
  }
  async function browserOCR(file){
    const T=await ensureTesseract();
    const result=await T.recognize(file,'por+spa+eng',{logger:m=>{ if(m.progress){const progress=$('ocrProgress');if(progress)progress.value=Math.round(m.progress*100);} }});
    return result?.data?.text||'';
  }
  async function serverOCR(file){
    const fd=new FormData(); fd.append('card',file,file.name||'cartao.jpg');
    const res=await fetch('/api/smart-capture/card-read',{method:'POST',body:fd});
    const data=await res.json().catch(()=>({}));
    if(!res.ok) throw new Error(data.error||'Falha na leitura do cartão');
    return data;
  }
  function applyOCRFields(values,confidence={}){
    const clean=normalizeOcrValues(values||{});
    Object.entries(clean).forEach(([k,v])=>{
      // Do not silently populate low-confidence person/company guesses.
      if((k==='name'||k==='company') && v && Number(confidence[k]||1)<.58) return;
      setField(k,v);
    });
    markConfidence(confidence,values||{});
    return clean;
  }
  async function runOCR(file){
    const status=$('ocrStatus'), progress=$('ocrProgress');
    const started=performance.now();
    try{
      status.innerHTML='<i class="bi bi-lightning-charge"></i> Leitura rápida do cartão…';
      progress.hidden=false; progress.value=18;
      const data=await serverOCR(file);
      state.ocrText=data.rawText||'';
      const clean=applyOCRFields(data.fields||{},data.confidence||{});
      const count=Object.values(clean).filter(Boolean).length;
      const low=(data.lowConfidence||[]).filter(k=>['name','company'].includes(k));
      const elapsed=((performance.now()-started)/1000).toFixed(1);
      status.innerHTML=`<i class="bi bi-check-circle-fill"></i> Leitura em ${elapsed}s${count?` · ${count} dado${count===1?'':'s'} útil${count===1?'':'eis'}`:''}.${low.length?' <b>Nome/empresa precisam de confirmação.</b>':' Confira e avance.'}`;
      progress.value=100; setTimeout(()=>{progress.hidden=true;},350);
      return;
    }catch(serverErr){
      console.warn('OCR servidor:',serverErr);
      status.innerHTML='<i class="bi bi-phone"></i> Servidor indisponível. Tentando leitura no aparelho…'; progress.value=20;
    }
    try{
      const text=await browserOCR(file); state.ocrText=text;
      const parsed=parseCardText(text); Object.entries(parsed).forEach(([k,v])=>setField(k,v));
      const count=Object.values(parsed).filter(Boolean).length;
      status.innerHTML=count?`<i class="bi bi-check-circle-fill"></i> Leitura alternativa concluída · ${count} dado${count===1?'':'s'} útil${count===1?'':'eis'}. Confira antes de continuar.`:'<i class="bi bi-exclamation-triangle"></i> Não identifiquei dados confiáveis. Preencha manualmente e continue.';
    }catch(err){
      console.warn('OCR navegador:',err);
      status.innerHTML='<i class="bi bi-exclamation-triangle"></i> Não consegui ler. Tente outra foto dentro da moldura, com boa luz e sem reflexo.';
    }finally{ progress.hidden=true; }
  }
  async function handleImage(file){
    if(!file)return;
    state.imageFile=file;
    const img=$('cardPreview'); img.src=URL.createObjectURL(file); img.classList.add('show');
    const status=$('ocrStatus'); if(status)status.innerHTML='<i class="bi bi-hourglass-split"></i> Preparando leitura…';
    runOCR(file); // do not block the UI
  }
  $('cardCameraInput')?.addEventListener('change',e=>handleImage(e.target.files?.[0]));
  $('cardGalleryInput')?.addEventListener('change',e=>handleImage(e.target.files?.[0]));

  // ---------- Live camera / autofocus / QR ----------
  const cameraOverlay=$('smartCameraOverlay'), cameraVideo=$('smartCameraVideo'), cameraStatus=$('smartCameraStatus');
  const cameraCapture=$('smartCameraCapture'), cameraTorch=$('smartCameraTorch');
  function stopCamera(){
    if(state.qrLoop){ cancelAnimationFrame(state.qrLoop); state.qrLoop=0; }
    if(state.cameraStream){ state.cameraStream.getTracks().forEach(t=>t.stop()); state.cameraStream=null; }
    state.cameraMode=null; state.qrServerBusy=false;
    if(cameraVideo) cameraVideo.srcObject=null;
    if(cameraOverlay) cameraOverlay.hidden=true;
  }
  async function applyCameraEnhancements(track){
    try{
      const caps=track.getCapabilities?.()||{};
      const advanced=[];
      if(Array.isArray(caps.focusMode) && caps.focusMode.includes('continuous')) advanced.push({focusMode:'continuous'});
      if(advanced.length) await track.applyConstraints({advanced});
      if(cameraTorch){ cameraTorch.hidden=!caps.torch; cameraTorch.dataset.on='false'; }
    }catch(_){ if(cameraTorch) cameraTorch.hidden=true; }
  }
  async function startCamera(mode){
    if(!navigator.mediaDevices?.getUserMedia){
      if(mode==='card') $('cardCameraInput')?.click(); else window.toast?.('Leitor QR não disponível neste navegador');
      return;
    }
    stopCamera(); state.cameraMode=mode; state.cameraStartedAt=performance.now();
    if(cameraOverlay){ cameraOverlay.hidden=false; cameraOverlay.classList.toggle('qr-mode',mode==='qr'); }
    $('smartCameraTitle').textContent=mode==='qr'?'Ler QR Code':'Fotografar cartão';
    $('smartCameraHint').textContent=mode==='qr'?'Aponte para o QR. A leitura é automática.':'Centralize o cartão na moldura e aguarde o foco ficar nítido.';
    cameraCapture.hidden=mode==='qr';
    cameraStatus.textContent=mode==='qr'?'Procurando QR…':'Abrindo câmera traseira…';
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:'environment'},width:{ideal:1920,min:640},height:{ideal:1080,min:480},frameRate:{ideal:30,max:30}}});
      state.cameraStream=stream; cameraVideo.srcObject=stream; await cameraVideo.play();
      const track=stream.getVideoTracks()[0]; await applyCameraEnhancements(track);
      cameraStatus.textContent=mode==='qr'?'QR pronto · mantenha o código dentro da moldura':'Câmera pronta · aguarde o autofocus e toque em Capturar';
      if(mode==='qr') startQrLoop();
    }catch(err){
      stopCamera();
      if(mode==='card'){ $('cardCameraInput')?.click(); }
      else window.toast?.('Não foi possível abrir a câmera. Verifique a permissão do navegador.');
    }
  }
  function frameCanvas(maxWidth=1200,cropCard=false){
    const vw=cameraVideo.videoWidth, vh=cameraVideo.videoHeight; if(!vw||!vh) return null;
    let sx=0,sy=0,sw=vw,sh=vh;
    if(cropCard){
      sw=Math.floor(vw*.90); sh=Math.min(vh,Math.floor(sw/1.58));
      if(sh>vh*.88){ sh=Math.floor(vh*.88); sw=Math.floor(sh*1.58); }
      sx=Math.floor((vw-sw)/2); sy=Math.floor((vh-sh)/2);
    }
    const scale=Math.min(1,maxWidth/sw), cw=Math.max(1,Math.round(sw*scale)), ch=Math.max(1,Math.round(sh*scale));
    const c=document.createElement('canvas'); c.width=cw; c.height=ch;
    c.getContext('2d',{willReadFrequently:true}).drawImage(cameraVideo,sx,sy,sw,sh,0,0,cw,ch);
    return c;
  }
  function canvasBlob(canvas,quality=.88){ return new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',quality)); }
  cameraCapture?.addEventListener('click',async()=>{
    const canvas=frameCanvas(1800,true); if(!canvas) return;
    cameraStatus.textContent='Capturando…';
    const blob=await canvasBlob(canvas,.9); if(!blob)return;
    const file=new File([blob],`cartao-${Date.now()}.jpg`,{type:'image/jpeg'});
    stopCamera(); await handleImage(file);
  });
  $('openCardCamera')?.addEventListener('click',()=>startCamera('card'));
  $('openQrScanner')?.addEventListener('click',()=>startCamera('qr'));
  $('closeSmartCamera')?.addEventListener('click',stopCamera);
  cameraTorch?.addEventListener('click',async()=>{
    try{
      const track=state.cameraStream?.getVideoTracks?.()[0]; if(!track)return;
      const on=cameraTorch.dataset.on!=='true'; await track.applyConstraints({advanced:[{torch:on}]});
      cameraTorch.dataset.on=String(on); cameraTorch.classList.toggle('active',on);
    }catch(_){ window.toast?.('Lanterna não suportada neste aparelho'); }
  });

  function parseVCard(raw){
    const out={}; const lines=raw.replace(/\r/g,'').split('\n');
    const vals=(prefix)=>lines.filter(x=>x.toUpperCase().startsWith(prefix)).map(x=>x.slice(x.indexOf(':')+1).trim()).filter(Boolean);
    const fn=vals('FN')[0]; const org=vals('ORG')[0]; const title=vals('TITLE')[0]; const email=vals('EMAIL')[0]; const tel=vals('TEL')[0]; const url=vals('URL')[0];
    if(fn)out.name=fn.replace(/;/g,' '); if(org)out.company=org.replace(/;/g,' '); if(title)out.role=title; if(email)out.email=email; if(tel)out.phone=out.whatsapp=tel; if(url)out.website=url;
    return out;
  }
  function parseMecard(raw){
    const out={}; const body=raw.replace(/^MECARD:/i,'').replace(/;;$/,'');
    body.split(';').forEach(part=>{ const i=part.indexOf(':'); if(i<0)return; const k=part.slice(0,i).toUpperCase(),v=part.slice(i+1).trim(); if(!v)return; if(k==='N')out.name=v.replace(/,/g,' '); if(k==='ORG')out.company=v; if(k==='TEL')out.phone=out.whatsapp=v; if(k==='EMAIL')out.email=v; if(k==='URL')out.website=v; });
    return out;
  }
  function applyQrPayload(raw){
    const value=(raw||'').trim(); if(!value)return false;
    let data={};
    if(/^BEGIN:VCARD/i.test(value)) data=parseVCard(value);
    else if(/^MECARD:/i.test(value)) data=parseMecard(value);
    else if(/^mailto:/i.test(value)) data.email=value.replace(/^mailto:/i,'').split('?')[0];
    else if(/^tel:/i.test(value)) data.phone=data.whatsapp=value.replace(/^tel:/i,'');
    else if(/(?:wa\.me|api\.whatsapp\.com|whatsapp\.com\/send)/i.test(value)){
      const m=value.match(/(?:wa\.me\/|phone=)(\+?\d+)/i); if(m)data.phone=data.whatsapp=m[1];
    } else if(/^https?:\/\//i.test(value) || /^[\w.-]+\.[a-z]{2,}/i.test(value)){
      if(/instagram\.com|linkedin\.com|facebook\.com|tiktok\.com/i.test(value)) data.social=value; else data.website=value;
    } else if(/^@\w/.test(value)) data.social=value;
    else if(validEmail(value)) data.email=value;
    else if(onlyDigits(value).length>=8) data.phone=data.whatsapp=value;
    else data.company=value;
    data=normalizeOcrValues(data);
    Object.entries(data).forEach(([k,v])=>setField(k,v));
    const status=$('ocrStatus'); if(status)status.innerHTML='<i class="bi bi-qr-code-scan"></i> QR lido com sucesso. Confira os dados e continue.';
    return Object.values(data).some(Boolean);
  }
  async function nativeQrDetect(){
    if(!('BarcodeDetector' in window)) return null;
    try{
      if(!state.barcodeDetector){
        const formats=await BarcodeDetector.getSupportedFormats?.();
        if(formats && !formats.includes('qr_code')) return null;
        state.barcodeDetector=new BarcodeDetector({formats:['qr_code']});
      }
      const codes=await state.barcodeDetector.detect(cameraVideo); return codes?.[0]?.rawValue||null;
    }catch(_){ return null; }
  }
  async function serverQrDetect(){
    if(state.qrServerBusy || performance.now()-state.lastQrServerAt<650) return null;
    state.qrServerBusy=true; state.lastQrServerAt=performance.now();
    try{
      const canvas=frameCanvas(720,false); if(!canvas)return null;
      const blob=await canvasBlob(canvas,.62); if(!blob)return null;
      const fd=new FormData(); fd.append('frame',blob,'qr-frame.jpg');
      const res=await fetch('/api/smart-capture/qr-read',{method:'POST',body:fd}); const data=await res.json().catch(()=>({}));
      return data.found?data.value:null;
    }catch(_){ return null; }finally{state.qrServerBusy=false;}
  }
  function startQrLoop(){
    let nativeTried=false;
    const tick=async()=>{
      if(state.cameraMode!=='qr'||!state.cameraStream)return;
      let value=await nativeQrDetect(); nativeTried=true;
      if(!value) value=await serverQrDetect();
      if(value){
        navigator.vibrate?.(60); cameraStatus.textContent='QR identificado';
        if(applyQrPayload(value)){ stopCamera(); return; }
      }
      if(nativeTried && performance.now()-state.cameraStartedAt>5000 && cameraStatus) cameraStatus.textContent='Ainda procurando… aproxime o QR e evite reflexo.';
      state.qrLoop=requestAnimationFrame(tick);
    };
    state.qrLoop=requestAnimationFrame(tick);
  }

  function renderReview(){
    const review=$('captureReviewSummary'),v=collectContact(); if(!review)return;
    review.innerHTML=`<b>${esc(v.name||'Nome não confirmado')}</b>${v.role?` · ${esc(v.role)}`:''}<br>${esc(v.company||'Empresa ainda não confirmada')}<br>${esc(v.whatsapp||v.phone||'Sem telefone')}${v.email?` · ${esc(v.email)}`:''}${v.website?`<br>${esc(v.website)}`:''}${v.social?`<br>${esc(v.social)}`:''}`;
  }
  async function resolveCapture(){
    const contact=collectContact(); const query=contact.website||contact.registrationId||contact.email||contact.whatsapp||contact.company||contact.social||contact.name;
    const banner=$('captureDuplicateBanner'); banner.innerHTML='<i class="bi bi-arrow-repeat spin"></i> Enriquecendo em fontes externas em segundo plano…'; banner.className='capture-confirm-banner loading';
    try{
      const res=await fetch('/api/smart-capture/lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,fields:contact})});
      const data=await res.json(); if(!res.ok)throw new Error(data.error||'Falha na busca'); state.lookup=data;
      const enr=data.enrichment||{};
      setField('company',enr.company); setField('website',validWebsite(enr.website||'')); setField('social',enr.social); setField('sector',enr.sector); setField('email',enr.email); setField('phone',enr.phone); setField('whatsapp',enr.whatsapp); setField('registrationId',enr.registrationId); setField('city',enr.city); setField('department',enr.department); setField('country',enr.country);
      if(data.externalFound){
        banner.innerHTML=`<b>Identificação externa concluída.</b> ${esc(enr.source||'Fontes públicas consultadas')}.${data.duplicate?' <span class="capture-dup-note">Possível registro já existente no CRM; o Radar evitará duplicação.</span>':' <span class="capture-new-note">Nenhuma duplicidade encontrada no CRM.</span>'}`;
        if(data.duplicate)banner.classList.add('warning');
      }else{
        banner.className='capture-confirm-banner warning'; banner.innerHTML='<b>Dados do contato capturados.</b> A empresa ainda não foi confirmada externamente. Confira os campos e você pode continuar normalmente.';
      }
      renderReview();
    }catch(err){ banner.className='capture-confirm-banner warning'; banner.textContent=`Enriquecimento externo ainda não terminou: ${err.message}. Você pode continuar e salvar o contato.`; }
  }

  dialog.querySelectorAll('[data-choice-group]').forEach(group=>group.addEventListener('click',e=>{
    const chip=e.target.closest('.capture-chip'); if(!chip)return; const multi=group.dataset.multi==='true';
    if(!multi)group.querySelectorAll('.capture-chip').forEach(x=>x.classList.remove('active'));
    chip.classList.toggle('active',multi?!chip.classList.contains('active'):true);
  }));
  function selected(group){ const el=dialog.querySelector(`[data-choice-group="${group}"]`); if(!el)return []; return [...el.querySelectorAll('.capture-chip.active')].map(x=>x.dataset.value); }
  function qualification(){ return {type:selected('type')[0]||'Cliente potencial',temperature:selected('temperature')[0]||'MEDIUM',interests:selected('interests'),market:selected('market')[0]||'Brasil',nextAction:selected('nextAction')[0]||'Enviar apresentação da Hengjie Doors',notes:$('captureNotes')?.value?.trim()||'',presentationUrl:$('capturePresentationUrl')?.value?.trim()||''}; }
  $('editCapturedData')?.addEventListener('click',()=>showStep(1));
  const presentationInput=$('capturePresentationUrl'); if(presentationInput){ presentationInput.value=localStorage.getItem('hengjiePresentationUrl')||''; presentationInput.addEventListener('change',()=>localStorage.setItem('hengjiePresentationUrl',presentationInput.value.trim())); }

  $('smartCaptureSave')?.addEventListener('click',async()=>{
    const btn=$('smartCaptureSave'); btn.disabled=true; btn.innerHTML='<i class="bi bi-hourglass-split"></i> Salvando…';
    try{
      const res=await fetch('/api/smart-capture/qualify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contact:collectContact(),qualification:qualification(),event:EVENT_NAME,captureMethod:state.imageFile?'BUSINESS_CARD':'SMART_CAPTURE'})});
      const data=await res.json(); if(!res.ok)throw new Error(data.error||'Não foi possível salvar'); state.saved=data;
      if(state.imageFile&&data.company?.id){ const fd=new FormData();fd.append('companyId',data.company.id);if(data.contact?.id)fd.append('contactId',data.contact.id);fd.append('event',EVENT_NAME);fd.append('card',state.imageFile,state.imageFile.name||'cartao.jpg');fetch('/api/smart-capture/card-upload',{method:'POST',body:fd}).catch(()=>{}); }
      const phone=onlyDigits(data.whatsapp||data.contact?.whatsapp||data.contact?.phone||'');
      $('smartCaptureSuccess').innerHTML=`<div class="capture-success"><i class="bi bi-check-circle-fill"></i><h3>Contato capturado</h3><p><b>${esc(data.contact?.name||'Contato')}</b> · ${esc(data.company?.name||'Empresa')}<br>Classificado e registrado no CRM com origem ${EVENT_NAME}.</p><div class="capture-message-preview">${esc(data.whatsappMessage||'')}</div>${phone?'<button type="button" class="primary whatsapp" id="openCapturedWhatsapp"><i class="bi bi-whatsapp"></i> Abrir WhatsApp com mensagem pronta</button>':'<p><b>WhatsApp não informado.</b> O contato foi salvo e pode ser completado depois.</p>'}</div>`;
      showStep(4);
      $('openCapturedWhatsapp')?.addEventListener('click',()=>window.open(`https://wa.me/${phone}?text=${encodeURIComponent(data.whatsappMessage||'')}`,'_blank','noopener'));
      window.toast?.('Contato da FESQUA salvo no CRM');
    }catch(err){window.toast?.(err.message);}finally{btn.disabled=false;btn.innerHTML='<i class="bi bi-check2-circle"></i> Salvar e preparar WhatsApp';}
  });

  const searchForm=$('siteAnalysisForm'), searchInput=$('companyWebsite');
  function applyExternalResult(data,q){
    const e=data.enrichment||{}; openCapture({reset:true});
    setField('company',e.company);setField('website',validWebsite(e.website||''));setField('social',e.social);
    setField('email',data.kind==='EMAIL'?q:e.email);setField('whatsapp',data.kind==='PHONE'?q:e.whatsapp);setField('phone',e.phone);
    setField('registrationId',(data.kind==='CNPJ'||data.kind==='RUC')?q:e.registrationId);setField('sector',e.sector);setField('city',e.city);setField('department',e.department);setField('country',e.country);
    if(data.kind==='SOCIAL')setField('social',q);
  }
  if(searchForm&&searchInput){
    searchInput.removeAttribute('required');searchInput.type='text';searchInput.inputMode='search';searchInput.autocomplete='off';searchInput.placeholder='Site, CNPJ/RUC, e-mail, WhatsApp, empresa ou @rede social…';
    const label=searchForm.querySelector('label');if(label)label.innerHTML='Buscar <b>nova empresa</b> fora da base <span>fontes externas primeiro</span>';
    searchForm.addEventListener('submit',async e=>{
      e.preventDefault();e.stopImmediatePropagation();const q=searchInput.value.trim();if(!q)return;
      const result=$('smartLookupResult');result.className='smart-lookup-result show external-first';result.innerHTML='<strong><i class="bi bi-globe2"></i> Buscando novo cliente fora do CRM…</strong><p>Consultando fontes públicas. O CRM será verificado somente depois para evitar duplicidade.</p>';
      try{
        const res=await fetch('/api/smart-capture/lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q})});const data=await res.json();if(!res.ok)throw new Error(data.error||'Falha');const ext=data.enrichment||{};
        if(data.externalFound){
          const duplicateNote=data.duplicate?'<div class="smart-dedupe-note"><i class="bi bi-shield-check"></i> Após a descoberta externa, foi encontrada possível correspondência no CRM. Ela será usada apenas para impedir duplicação.</div>':'<div class="smart-new-note"><i class="bi bi-plus-circle"></i> Nenhuma correspondência no CRM após a descoberta externa.</div>';
          const source=ext.source?`<span class="smart-source"><i class="bi bi-globe2"></i> ${esc(ext.source)}</span>`:'';
          result.innerHTML=`<strong><i class="bi bi-stars"></i> ${esc(ext.company||'Empresa localizada')}</strong><p>${esc(ext.sector||ext.website||ext.searchResultTitle||'Dados externos encontrados.')}</p>${source}${duplicateNote}<button type="button" class="primary secondary-action" id="lookupOpenCapture"><i class="bi bi-lightning-charge"></i> Confirmar e classificar</button>`;
        }else result.innerHTML='<strong><i class="bi bi-search"></i> Não localizei uma empresa nova automaticamente.</strong><p>Tente site, CNPJ/RUC, e-mail corporativo, WhatsApp, nome completo, @rede social ou use cartão/QR.</p><button type="button" class="secondary-action" id="lookupOpenCapture"><i class="bi bi-person-plus"></i> Preencher e classificar manualmente</button>';
        $('lookupOpenCapture')?.addEventListener('click',()=>applyExternalResult(data,q));
      }catch(err){result.innerHTML=`<strong>Não foi possível concluir a busca externa.</strong><p>${esc(err.message)}</p><button type="button" class="secondary-action" id="lookupOpenCapture">Abrir captura manual</button>`;$('lookupOpenCapture')?.addEventListener('click',()=>openCapture({reset:true}));}
    },true);
  }
})();
