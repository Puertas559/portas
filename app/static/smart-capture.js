(() => {
  const $ = (id) => document.getElementById(id);
  const EVENT_NAME = 'FESQUA 2026';
  const state = { imageFile:null, ocrText:'', lookup:null, saved:null, step:1 };
  const esc = (v='') => String(v).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const onlyDigits = (v='') => String(v).replace(/\D/g,'');
  const dialog = $('smartCaptureDialog');
  if (!dialog) return;

  function showStep(n){ state.step=n; dialog.querySelectorAll('.capture-step').forEach(el=>el.classList.toggle('active', Number(el.dataset.step)===n)); updateActions(); }
  function updateActions(){
    const back=$('smartCaptureBack'), next=$('smartCaptureNext'), save=$('smartCaptureSave');
    back.hidden=state.step===1 || state.step===4; next.hidden=state.step>=3; save.hidden=state.step!==3;
  }
  function openCapture(){ state.step=1; state.saved=null; $('smartCaptureSuccess').innerHTML=''; showStep(1); if(!dialog.open) dialog.showModal(); }
  function closeCapture(){ if(dialog.open) dialog.close(); }
  $('openSmartCapture')?.addEventListener('click', openCapture);
  $('openSmartCaptureFloating')?.addEventListener('click', openCapture);
  $('closeSmartCapture')?.addEventListener('click', closeCapture);
  $('smartCaptureBack')?.addEventListener('click', ()=>showStep(Math.max(1,state.step-1)));
  $('smartCaptureNext')?.addEventListener('click', async()=>{ if(state.step===1){ if(!getField('name')&&!getField('company')&&!getField('email')&&!getField('whatsapp')){ window.toast?.('Capture o complete al menos un dato del contacto'); return; } await resolveCapture(); showStep(2); } else if(state.step===2) showStep(3); });

  function field(name){ return dialog.querySelector(`[data-card-field="${name}"]`); }
  function getField(name){ return field(name)?.value?.trim() || ''; }
  function setField(name,val){ if(val && field(name) && !field(name).value) field(name).value=val; }
  function collectContact(){ return Object.fromEntries(['name','role','company','email','phone','whatsapp','website','registrationId','sector','city','department','country'].map(k=>[k,getField(k)])); }

  function parseCardText(text){
    const lines=text.split(/\n+/).map(x=>x.trim()).filter(Boolean);
    const email=(text.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)||[])[0]||'';
    const urls=(text.match(/(?:https?:\/\/)?(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}(?:\/\S*)?/ig)||[]).filter(x=>!x.includes('@'));
    const phoneMatches=text.match(/(?:\+?\d[\d\s().-]{7,}\d)/g)||[];
    const phones=phoneMatches.map(x=>x.trim()).sort((a,b)=>onlyDigits(b).length-onlyDigits(a).length);
    const cnpj=(text.match(/\b\d{2}\.\d{3}\.\d{3}\/\d{4}-\d{2}\b/)||[])[0]||'';
    const roleWords=/gerente|diretor|director|comercial|ventas|sales|engenheir|ingenier|compras|procurement|ceo|owner|propriet|socio|sócio|representante|coordenador|coordinador/i;
    const roleLine=lines.find(x=>roleWords.test(x))||'';
    const candidates=lines.filter(x=>!x.includes('@')&&!/www\.|https?:|\d{4,}/i.test(x)&&x.length>2&&x.length<70);
    const nameLine=candidates.find(x=>x!==roleLine && x.split(/\s+/).length>=2 && x.split(/\s+/).length<=5)||candidates[0]||'';
    const companyLine=candidates.find(x=>x!==nameLine&&x!==roleLine&&/(ltda|s\.a\.?|sa\b|doors|portas|puertas|indust|group|grupo|technology|tecnologia|sistemas|alumin|esquadr|company|co\.?\s?ltd)/i.test(x)) || candidates.find(x=>x!==nameLine&&x!==roleLine)||'';
    return {name:nameLine,role:roleLine,company:companyLine,email,phone:phones[0]||'',whatsapp:phones[0]||'',website:urls[0]||'',registrationId:cnpj};
  }

  async function ensureTesseract(){
    if(window.Tesseract) return window.Tesseract;
    await new Promise((resolve,reject)=>{const s=document.createElement('script');s.src='https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js';s.onload=resolve;s.onerror=reject;document.head.appendChild(s);});
    return window.Tesseract;
  }
  async function runOCR(file){
    const status=$('ocrStatus'), progress=$('ocrProgress');
    try{
      status.textContent='Lendo o cartão…'; progress.hidden=false; progress.value=5;
      const T=await ensureTesseract();
      const result=await T.recognize(file,'por+eng+spa',{logger:m=>{if(m.progress){progress.value=Math.round(m.progress*100);status.textContent=m.status==='recognizing text'?`Lendo… ${progress.value}%`:'Preparando leitura…';}}});
      state.ocrText=result.data.text||'';
      const parsed=parseCardText(state.ocrText); Object.entries(parsed).forEach(([k,v])=>setField(k,v));
      status.textContent='Leitura concluída. Confira os dados antes de continuar.'; progress.hidden=true;
    }catch(err){ console.warn(err); status.textContent='Não foi possível fazer a leitura automática. Confira/preencha os dados manualmente.'; progress.hidden=true; }
  }
  async function handleImage(file){ if(!file)return; state.imageFile=file; const img=$('cardPreview'); img.src=URL.createObjectURL(file); img.classList.add('show'); await runOCR(file); }
  $('cardCameraInput')?.addEventListener('change',e=>handleImage(e.target.files?.[0]));
  $('cardGalleryInput')?.addEventListener('change',e=>handleImage(e.target.files?.[0]));

  async function resolveCapture(){
    const contact=collectContact(); const query=contact.email||contact.whatsapp||contact.website||contact.registrationId||contact.company||contact.name;
    const banner=$('captureDuplicateBanner'); banner.textContent='Verificando duplicidade e enriquecendo dados…'; banner.className='capture-confirm-banner';
    try{
      const res=await fetch('/api/smart-capture/lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,fields:contact})});
      const data=await res.json(); if(!res.ok) throw new Error(data.error||'Falha na busca'); state.lookup=data;
      const enr=data.enrichment||{}; setField('company',enr.company);setField('website',enr.website);setField('sector',enr.sector);setField('email',enr.email);setField('phone',enr.phone);setField('whatsapp',enr.whatsapp);setField('registrationId',enr.registrationId);setField('city',enr.city);setField('department',enr.department);setField('country',enr.country);
      if(data.duplicate){ const c=data.companies?.[0],p=data.contacts?.[0]; banner.className='capture-confirm-banner warning';banner.innerHTML=`<b>Registro já encontrado.</b> ${esc(p?.name||'')} ${c?`· ${esc(c.name)}`:''}. O Radar irá completar o registro existente, sem duplicar.`; }
      else banner.innerHTML='<b>Novo contato.</b> O Radar não encontrou duplicidade. Confira os dados e siga para a classificação.';
      const review=$('captureReviewSummary'); const v=collectContact(); if(review) review.innerHTML=`<b>${esc(v.name||'Nome não identificado')}</b>${v.role?` · ${esc(v.role)}`:''}<br>${esc(v.company||'Empresa não identificada')}<br>${esc(v.whatsapp||v.phone||'Sem telefone')}${v.email?` · ${esc(v.email)}`:''}${v.website?`<br>${esc(v.website)}`:''}`;
    }catch(err){ banner.className='capture-confirm-banner warning';banner.textContent=`Não foi possível enriquecer agora: ${err.message}. Você pode continuar e salvar o contato.`; }
  }

  dialog.querySelectorAll('[data-choice-group]').forEach(group=>group.addEventListener('click',e=>{
    const chip=e.target.closest('.capture-chip'); if(!chip)return; const multi=group.dataset.multi==='true'; if(!multi) group.querySelectorAll('.capture-chip').forEach(x=>x.classList.remove('active')); chip.classList.toggle('active', multi ? !chip.classList.contains('active') : true);
  }));
  function selected(group){ const el=dialog.querySelector(`[data-choice-group="${group}"]`); if(!el)return []; return [...el.querySelectorAll('.capture-chip.active')].map(x=>x.dataset.value); }
  function qualification(){return {type:selected('type')[0]||'Cliente potencial',temperature:selected('temperature')[0]||'MEDIUM',interests:selected('interests'),market:selected('market')[0]||'Brasil',nextAction:selected('nextAction')[0]||'Enviar apresentação da Hengjie Doors',notes:$('captureNotes')?.value?.trim()||'',presentationUrl:$('capturePresentationUrl')?.value?.trim()||''};}

  $('editCapturedData')?.addEventListener('click',()=>showStep(1));
  const presentationInput=$('capturePresentationUrl'); if(presentationInput){presentationInput.value=localStorage.getItem('hengjiePresentationUrl')||'';presentationInput.addEventListener('change',()=>localStorage.setItem('hengjiePresentationUrl',presentationInput.value.trim()));}

  $('smartCaptureSave')?.addEventListener('click', async()=>{
    const btn=$('smartCaptureSave'); btn.disabled=true; btn.innerHTML='<i class="bi bi-hourglass-split"></i> Salvando…';
    try{
      const res=await fetch('/api/smart-capture/qualify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contact:collectContact(),qualification:qualification(),event:EVENT_NAME,captureMethod:state.imageFile?'BUSINESS_CARD':'MANUAL'})});
      const data=await res.json(); if(!res.ok) throw new Error(data.error||'Não foi possível salvar'); state.saved=data;
      if(state.imageFile && data.company?.id){ const fd=new FormData();fd.append('companyId',data.company.id);if(data.contact?.id)fd.append('contactId',data.contact.id);fd.append('event',EVENT_NAME);fd.append('card',state.imageFile,state.imageFile.name||'cartao.jpg');fetch('/api/smart-capture/card-upload',{method:'POST',body:fd}).catch(()=>{}); }
      const phone=onlyDigits(data.whatsapp||data.contact?.whatsapp||data.contact?.phone||'');
      $('smartCaptureSuccess').innerHTML=`<div class="capture-success"><i class="bi bi-check-circle-fill"></i><h3>Contato capturado</h3><p><b>${esc(data.contact?.name||'Contato')}</b> · ${esc(data.company?.name||'Empresa')}<br>Classificado e registrado no CRM com origem ${EVENT_NAME}.</p><div class="capture-message-preview">${esc(data.whatsappMessage||'')}</div>${phone?'<button type="button" class="primary whatsapp" id="openCapturedWhatsapp"><i class="bi bi-whatsapp"></i> Abrir WhatsApp com mensagem pronta</button>':'<p><b>WhatsApp não informado.</b> O contato foi salvo e pode ser completado depois.</p>'}</div>`;
      showStep(4);
      $('openCapturedWhatsapp')?.addEventListener('click',()=>{ window.open(`https://wa.me/${phone}?text=${encodeURIComponent(data.whatsappMessage||'')}`,'_blank','noopener'); });
      window.toast?.('Contato da FESQUA salvo no CRM');
    }catch(err){ window.toast?.(err.message); }finally{ btn.disabled=false;btn.innerHTML='<i class="bi bi-check2-circle"></i> Salvar e preparar WhatsApp'; }
  });

  const searchForm=$('siteAnalysisForm'); const searchInput=$('companyWebsite');
  if(searchForm&&searchInput){
    searchInput.removeAttribute('required'); searchInput.type='text'; searchInput.inputMode='search'; searchInput.autocomplete='off'; searchInput.placeholder='Empresa, site, e-mail, WhatsApp, CNPJ/RUC…';
    const label=searchForm.querySelector('label'); if(label)label.textContent='Busca inteligente de empresa ou contato';
    searchForm.addEventListener('submit', async e=>{
      const q=searchInput.value.trim(); if(!q)return;
      if(/^https?:\/\//i.test(q)||(/^[\w.-]+\.[a-z]{2,}(?:\/.*)?$/i.test(q)&&!q.includes('@'))){ return; }
      e.preventDefault(); e.stopImmediatePropagation();
      const result=$('smartLookupResult');result.className='smart-lookup-result show';result.innerHTML='<strong>Buscando…</strong><p>Verificando CRM, contato, domínio e identificadores.</p>';
      try{ const res=await fetch('/api/smart-capture/lookup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:q})});const data=await res.json();if(!res.ok)throw new Error(data.error||'Falha');
        if(data.duplicate){const c=data.companies?.[0],p=data.contacts?.[0];result.classList.add('smart-duplicate');result.innerHTML=`<strong><i class="bi bi-check-circle"></i> Encontrado no CRM</strong><p>${esc(p?.name||'')} ${c?`· ${esc(c.name)}`:''}. Abra a captura rápida para classificar/atualizar este contato.</p><button type="button" class="secondary-action" id="lookupOpenCapture">Abrir captura</button>`;}
        else{const e=data.enrichment||{};result.innerHTML=`<strong><i class="bi bi-stars"></i> ${esc(e.company||'Novo contato/empresa')}</strong><p>${esc(e.sector||e.website||'Não encontrado no CRM. Você pode completar os dados e classificar em segundos.')}</p><button type="button" class="secondary-action" id="lookupOpenCapture">Capturar e classificar</button>`;}
        $('lookupOpenCapture')?.addEventListener('click',()=>{openCapture(); const e=data.enrichment||{}; setField('company',e.company);setField('website',e.website);setField('email',data.kind==='EMAIL'?q:e.email);setField('whatsapp',data.kind==='PHONE'?q:e.whatsapp);setField('registrationId',data.kind==='CNPJ'?q:e.registrationId);setField('sector',e.sector);});
      }catch(err){result.innerHTML=`<strong>Não foi possível concluir a busca.</strong><p>${esc(err.message)}</p>`;}
    }, true);
  }
})();
