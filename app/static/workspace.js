(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value = "") => String(value).replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const moduleTitles = {
    triage:"Calificar por sitio", research:"Cola de investigación", salesready:"Listo para ventas", hoy:"Mi día",
    crm:"CRM", pipeline:"Embudo comercial", visitas:"Visitas", radar:"Radar comercial", captacion:"Captación automática",
    oportunidades:"Oportunidades", smartlists:"Listas inteligentes", reportes:"Reportes comerciales", metrics:"Rendimiento"
  };
  let workspaceData = null;
  const bulkSelection = new Set();

  function toastLocal(message){ if (typeof toast === "function") return toast(message); const el=$("toast"); if(el){el.textContent=message;el.style.display="block";setTimeout(()=>el.style.display="none",2200);} }

  function openModule(name){
    document.querySelectorAll(".app-module").forEach((el) => el.classList.toggle("module-active", el.dataset.module === name));
    document.querySelectorAll("[data-module-target]").forEach((el) => el.classList.toggle("active", el.dataset.moduleTarget === name));
    if ($("workspaceModuleTitle")) $("workspaceModuleTitle").textContent = moduleTitles[name] || "Centro comercial";
    document.body.classList.remove("drawer-open");
    window.scrollTo({top:0,behavior:"smooth"});
    if (["research","salesready","smartlists"].includes(name)) loadWorkspace();
    if (name === "metrics") loadPerformance();
    if (name === "reportes") loadReports();
    if (name === "hoy" && typeof loadToday === "function") loadToday();
    if (name === "radar" && typeof loadCommandCenter === "function") loadCommandCenter();
  }

  document.querySelectorAll("[data-module-target]").forEach((link) => link.addEventListener("click", (e) => { e.preventDefault(); openModule(link.dataset.moduleTarget); }));
  $("globalRefresh")?.addEventListener("click", () => {
    const active = document.querySelector("[data-module-target].active")?.dataset.moduleTarget || "triage";
    if (["research","salesready","smartlists"].includes(active)) loadWorkspace(true);
    else if (active === "hoy" && typeof loadToday === "function") loadToday();
    else if (active === "radar" && typeof loadCommandCenter === "function") loadCommandCenter();
    else location.reload();
  });

  function leadById(id){ return (window.RADAR_LEADS || []).find((lead) => String(lead.id) === String(id)); }
  function openLead(id){
    const lead = leadById(id);
    if (!lead) return toastLocal("Oportunidad no encontrada en la vista actual");
    if (typeof selectLead === "function") selectLead(lead);
    document.body.classList.add("drawer-open");
  }
  document.addEventListener("click", (event) => {
    const direct = event.target.closest("[data-open-opportunity]");
    if (direct) openLead(direct.dataset.openOpportunity);
    if (event.target.closest(".lead,.open-crm-detail,.radar-row[data-opportunity-id],.task-item .open-task")) setTimeout(()=>document.body.classList.add("drawer-open"),0);
  }, true);
  $("closeDrawer")?.addEventListener("click", () => document.body.classList.remove("drawer-open"));


  async function loadPerformance(){
    try{const r=await fetch("/api/metrics");const d=await r.json();if(!r.ok)throw new Error();const money=(v)=>new Intl.NumberFormat("es-PY",{style:"currency",currency:"USD",maximumFractionDigits:0}).format(Number(v)||0);const values=[d.opportunities||0,d.salesReady||0,`${d.decisionMakerCoverage||0}%`,`${d.averageCompleteness||0}%`,`${d.responseRate||0}%`,`${d.winRate||0}%`,money(d.pipelineValue),d.overdueTasks||0];document.querySelectorAll("#performanceMetrics article strong").forEach((el,i)=>el.textContent=values[i]);}
    catch(_){toastLocal("No se pudieron cargar las métricas");}
  }

  function readinessCard(lead){
    const ready = Boolean(lead.salesReady);
    const blockers = (lead.blockers || []).slice(0,4);
    return `<article class="readiness-card ${bulkSelection.has(String(lead.id)) ? "selected-card" : ""}" data-ready-id="${esc(lead.id)}">
      <label><input type="checkbox" class="bulk-ready-check" data-id="${esc(lead.id)}" ${bulkSelection.has(String(lead.id))?"checked":""}></label>
      <div><span class="${ready?"ready-flag":"blocked-flag"}">${ready?"● LISTO PARA VENTAS":"○ AÚN NO PREPARADO"}</span><h3>${esc(lead.company)}</h3><p>${esc(lead.project || "Proyecto por validar")}</p>
      <div class="readiness-meta"><span>Preparación ${Number(lead.leadReadiness)||0}</span><span>Puntuación ${Number(lead.score)||0}</span><span>Confianza ${Number(lead.confidenceScore)||0}</span><span>Datos ${Number(lead.dataCompleteness)||0}%</span></div>
      ${blockers.length?`<p style="margin-top:9px">Falta: ${esc(blockers.join(", "))}</p>`:""}</div>
      <button class="open-ready" data-open-opportunity="${esc(lead.id)}"><i class="bi bi-arrow-right"></i></button>
    </article>`;
  }

  function renderWorkspace(data){
    workspaceData = data;
    const summary = data.summary || {};
    document.querySelectorAll("#workspaceSummary article b").forEach((el,i)=>{el.textContent=[summary.needsResearch||0,summary.withoutDecisionMaker||0,summary.staleAccounts||0,summary.salesReady||0][i]});
    const research = data.researchQueue || [];
    if ($("researchTable")) $("researchTable").innerHTML = research.map((row)=>`<article class="work-row">
      <input type="checkbox" disabled><div><strong>${esc(row.company)}</strong><small>${esc([row.sector,row.city].filter(Boolean).join(" · ") || "Por validar")}</small></div>
      <div><span>Completitud ${row.completeness}%</span><div class="completeness"><i style="width:${row.completeness}%"></i></div></div>
      <div><strong>Afinidad ${row.fit||0}</strong><small>Aceleración ${row.momentum||0}</small></div>
      <div><strong>Prioridad ${row.priority||0}</strong><small>${row.staleDays==null?"Sin verificar":`${row.staleDays}d desde revisión`}</small></div>
      <div class="missing-tags">${(row.missing||[]).map((m)=>`<em>${esc(m)}</em>`).join("")||"<span>Completo</span>"}</div>
      <button class="row-action" data-research-url="${esc(row.website||"")}">Investigar</button></article>`).join("") || "<p>No hay empresas pendientes de investigación.</p>";
    if ($("salesReadyList")) $("salesReadyList").innerHTML = (data.salesReady||[]).map(readinessCard).join("") || "<p>No hay oportunidades cercanas a Listo para ventas.</p>";
    renderSmartList(document.querySelector("#smartListTabs button.active")?.dataset.smart || "hotWithoutDecisionMaker");
  }

  async function loadWorkspace(force=false){
    if (workspaceData && !force){ renderWorkspace(workspaceData); return; }
    try{ const r=await fetch("/api/workspace/overview"); if(!r.ok) throw new Error(); renderWorkspace(await r.json()); }
    catch(_){ toastLocal("No se pudo cargar el centro de trabajo comercial"); }
  }
  $("refreshWorkspace")?.addEventListener("click",()=>loadWorkspace(true));
  $("researchTable")?.addEventListener("click",(e)=>{const b=e.target.closest("[data-research-url]");if(!b)return;openModule("triage");const url=b.dataset.researchUrl;if(url){$("companyWebsite").value=url;$("companyWebsite").focus();toastLocal("Sitio cargado para enriquecimiento");}else{toastLocal("Esta empresa todavía no tiene sitio identificado");}});


  function renderSmartList(key){
    document.querySelectorAll("#smartListTabs button").forEach((b)=>b.classList.toggle("active",b.dataset.smart===key));
    if(!workspaceData || !$("smartListResults")) return;
    const rows=(workspaceData.smartLists||{})[key]||[];
    $("smartListResults").innerHTML=rows.map((row)=>{
      if(row.companyId && !row.id) return `<article class="readiness-card"><div class="readiness-score">${Number(row.completeness)||0}</div><div><h3>${esc(row.company)}</h3><p>Datos vencidos o incompletos · Afinidad ${Number(row.fit)||0}</p></div></article>`;
      return readinessCard(row);
    }).join("")||"<p>Sin resultados para esta lista.</p>";
  }
  $("smartListTabs")?.addEventListener("click",(e)=>{const b=e.target.closest("button[data-smart]");if(b)renderSmartList(b.dataset.smart)});
  document.querySelector("#smartListTabs button")?.classList.add("active");

  document.addEventListener("change",(e)=>{if(e.target.matches(".bulk-ready-check")){const id=String(e.target.dataset.id);e.target.checked?bulkSelection.add(id):bulkSelection.delete(id);e.target.closest(".readiness-card")?.classList.toggle("selected-card",e.target.checked)}});
  document.querySelectorAll("[data-bulk-action]").forEach((b)=>b.addEventListener("click",async()=>{
    if(!bulkSelection.size) return toastLocal("Seleccione oportunidades en Listo para ventas");
    const r=await fetch("/api/bulk/actions",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:b.dataset.bulkAction,opportunityIds:[...bulkSelection]})});
    const d=await r.json(); if(!r.ok)return toastLocal(d.error||"No se pudo ejecutar"); toastLocal(`${d.updated} oportunidades actualizadas`); bulkSelection.clear(); loadWorkspace(true);
  }));

  $("runBulkSiteAnalysis")?.addEventListener("click",async()=>{
    const raw=$("bulkSiteUrls")?.value.trim(); if(!raw)return toastLocal("Pegue al menos una URL");
    const urls=[...new Set(raw.replace(/\r/g,"\n").split("\n").map(v=>v.trim()).filter(Boolean))].slice(0,25);
    const button=$("runBulkSiteAnalysis"); button.disabled=true;
    let done=0, failed=0;
    $("bulkSiteMessage").textContent=`Iniciando Análisis rápido de ${urls.length} sitios · hasta 4 análisis en paralelo…`;
    const queue=[...urls];
    const worker=async()=>{while(queue.length){const url=queue.shift();try{const r=await fetch("/api/website-analysis",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url,mode:"quick"})});const d=await r.json();if(!r.ok)throw new Error(d.error||"Error");$("siteAnalysisResults")?.insertAdjacentHTML("afterbegin",typeof renderWebsiteAnalysis==="function"?renderWebsiteAnalysis(d):"");done++;}catch(_){failed++;}finally{$("bulkSiteMessage").textContent=`${done} analizadas · ${failed} con error · ${queue.length} pendientes`;}}};
    try{await Promise.all(Array.from({length:Math.min(4,urls.length)},worker));toastLocal("Análisis rápido en lote terminado");}
    finally{button.disabled=false;$("bulkSiteMessage").textContent=`${done} analizadas · ${failed} con error. Profundice solo las empresas que valen la pena.`;}
  });

  $("createCadence")?.addEventListener("click",async()=>{if(!selected||selected.demo)return toastLocal("Seleccione una oportunidad real");const r=await fetch(`/api/opportunities/${selected.id}/cadence`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({replace:true})});if(!r.ok)return toastLocal("No se pudo crear la cadencia");toastLocal("Cadencia comercial creada");if(typeof loadToday==="function")loadToday()});
  $("saveOutcome")?.addEventListener("click",async()=>{if(!selected||selected.demo)return toastLocal("Seleccione una oportunidad real");const outcome=$("commercialOutcome").value;if(!outcome)return toastLocal("Seleccione un resultado");const r=await fetch(`/api/opportunities/${selected.id}/outcome`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({outcome,lostReason:$("lostReason").value})});const d=await r.json();if(!r.ok)return toastLocal(d.error||"No se pudo guardar");Object.assign(selected,d);if(typeof render==="function")render();toastLocal("Resultado comercial guardado");loadWorkspace(true)});


  async function loadCommittee(){
    if(!selected || selected.demo || !selected.id) return;
    const lead=selected; const companyName=lead.company;
    try{
      // Resolve company ID by name from the company endpoint, then fetch its committee.
      const companyResponse=await fetch(`/api/companies?q=${encodeURIComponent(companyName)}`); const companyData=await companyResponse.json();
      const company=(companyData.items||[]).find((row)=>row.name===companyName)||(companyData.items||[])[0];
      if(!company){$("committeeList").innerHTML="<p>Empresa no localizada.</p>";return;}
      $("committeeList").dataset.companyId=company.id;
      const r=await fetch(`/api/companies/${company.id}/contacts`); const rows=await r.json();
      $("committeeList").innerHTML=(rows||[]).map((c)=>`<article class="committee-contact"><strong>${esc(c.name)}</strong><span>${esc(c.role||"Cargo por validar")}</span><small>${esc(c.email||c.whatsapp||c.phone||"Sin contacto directo")}</small><em>${esc(c.buyingRole||"POR VALIDAR")} · influencia ${Number(c.influence)||0}</em></article>`).join("")||"<p>No hay contactos todavía. Añada el primer decisor o influenciador.</p>";
    }catch(_){$("committeeList").innerHTML="<p>No se pudo cargar el comité.</p>"}
  }
  document.querySelector('[data-tab="committee"]')?.addEventListener("click",()=>setTimeout(loadCommittee,0));
  $("saveContact")?.addEventListener("click",async()=>{const companyId=$("committeeList")?.dataset.companyId;if(!companyId)return toastLocal("Abra primero una oportunidad real");const name=$("contactName").value.trim();if(!name)return toastLocal("Ingrese el nombre");const phone=$("contactPhone").value.trim();const payload={name,role:$("contactRole").value.trim(),buyingRole:$("contactBuyingRole").value,email:$("contactEmail").value.trim(),phone,whatsapp:phone,influence:$("contactBuyingRole").value==="DECISION_MAKER"?90:70,confidence:70};const r=await fetch(`/api/companies/${companyId}/contacts`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});const d=await r.json().catch(()=>({}));if(!r.ok)return toastLocal(d.error||"No se pudo guardar el contacto");["contactName","contactRole","contactEmail","contactPhone"].forEach((id)=>$(id).value="");toastLocal("Contacto añadido al Comité de compra");window.dispatchEvent(new CustomEvent("radar:contact-updated",{detail:{companyId:Number(companyId),contactId:d.id,name:payload.name,email:payload.email,role:payload.role}}));loadCommittee();loadWorkspace(true)});

  // Keep the drawer intelligence indicators synchronized whenever a lead is selected.
  const syncDrawer=()=>{ if(!selected)return; if($("drawerReadiness"))$("drawerReadiness").textContent=`${Number(selected.leadReadiness)||0}/100`;if($("drawerCompleteness"))$("drawerCompleteness").textContent=`${Number(selected.dataCompleteness)||0}%`;if($("drawerSalesReady")){$("drawerSalesReady").textContent=selected.salesReady?"LISTO PARA VENTAS":"NO PREPARADO";$("drawerSalesReady").classList.toggle("ready",Boolean(selected.salesReady))}if($("nextBestActionText"))$("nextBestActionText").textContent=selected.nextBestAction||"Completar contacto y validar el próximo paso.";};
  document.addEventListener("click",()=>setTimeout(syncDrawer,0));

  // Enter executes the most likely action in the active module.
  $("companyWebsite")?.addEventListener("keydown",(e)=>{if(e.key==="Enter"){e.preventDefault();$("siteAnalysisForm")?.requestSubmit()}});
  $("bulkSiteUrls")?.addEventListener("keydown",(e)=>{if((e.metaKey||e.ctrlKey)&&e.key==="Enter"){$("runBulkSiteAnalysis")?.click()}});



  async function loadSimilarAccounts(){
    if(!selected || selected.demo || !selected.id) return toastLocal("Seleccione una oportunidad real");
    const box=$("similarAccountsList"), button=$("loadSimilarAccounts");
    if(box) box.innerHTML='<div class="mini-skeleton"><i></i><span></span><span></span></div>';
    if(button) button.disabled=true;
    try{
      const r=await fetch(`/api/opportunities/${selected.id}/similar`); const rows=await r.json();
      if(!r.ok) throw new Error();
      box.innerHTML=(rows||[]).map(row=>`<button class="similar-row" data-open-opportunity="${esc(row.id)}"><span><strong>${esc(row.company)}</strong><small>${esc(row.sector||"Sector por validar")}</small></span><em>${Number(row.similarity)||0}% similar</em></button>`).join("")||"<small>No hay suficientes cuentas comparables todavía.</small>";
    }catch(_){ if(box)box.innerHTML="<small>No se pudieron calcular cuentas similares.</small>"; }
    finally{if(button)button.disabled=false;}
  }
  $("loadSimilarAccounts")?.addEventListener("click",loadSimilarAccounts);

  // Keyboard-first workflow: / focuses qualification, Escape closes drawer.
  document.addEventListener("keydown",(e)=>{
    const tag=(document.activeElement?.tagName||"").toLowerCase();
    const typing=["input","textarea","select"].includes(tag);
    if(e.key==="/" && !typing){e.preventDefault();openModule("triage");setTimeout(()=>$("companyWebsite")?.focus(),50);}
    if(e.key==="Escape" && document.body.classList.contains("drawer-open")) document.body.classList.remove("drawer-open");
  });

  function reportParams(){
    const p=new URLSearchParams(); const period=$("reportPeriod")?.value||"all"; p.set("period",period);
    if(period==="custom"){if($("reportStart")?.value)p.set("start",$("reportStart").value);if($("reportEnd")?.value)p.set("end",$("reportEnd").value);}
    if($("reportUser")?.value)p.set("user",$("reportUser").value); return p;
  }
  const reportTypeLabel=(v)=>({EMAIL_SENT:"Correo enviado",WHATSAPP_SENT:"WhatsApp",CALL:"Llamada",MEETING:"Reunión",VISIT_SCHEDULED:"Visita marcada",VISIT:"Visita realizada",PROPOSAL_SENT:"Propuesta",REPLY:"Respuesta recibida"}[v]||v||"Actividad");
  const yesNo=(v)=>v?'<span class="report-yes"><i class="bi bi-check-circle-fill"></i> Sí</span>':'<span class="report-no">—</span>';
  async function loadReports(){
    const box=$("reportActivity"), kpis=$("reportKpis"), summary=$("reportSummary"); if(box)box.innerHTML='<p>Cargando empresas...</p>';
    try{const r=await fetch(`/api/reports/activity?${reportParams()}`);const d=await r.json();if(!r.ok)throw new Error(d.error||"No se pudo cargar el reporte");
      if($("reportUser") && $("reportUser").options.length<=1){(d.users||[]).forEach(u=>$("reportUser").insertAdjacentHTML("beforeend",`<option value="${esc(u)}">${esc(u)}</option>`));}
      const m=d.metrics||{};
      if(kpis)kpis.innerHTML=[
        ["Empresas únicas analizadas",m.analysed],["Clasificadas",m.classified],["Empresas contactadas",m.contactedCompanies],["Empresas que respondieron",m.replies],
        ["Visitas marcadas",m.visitsScheduled ?? m.visits],["Visitas realizadas",m.visitsCompleted],["Empresas con propuesta",m.proposals],["Ganadas",m.wins]
      ].map(([l,v])=>`<article><small>${esc(l.toUpperCase())}</small><strong>${Number(v)||0}</strong></article>`).join("");
      if($("reportTaskStats"))$("reportTaskStats").innerHTML=`<article><i class="bi bi-envelope-check"></i><span><small>CORREOS</small><b>${Number(m.emails)||0}</b></span></article><article><i class="bi bi-whatsapp"></i><span><small>WHATSAPPS</small><b>${Number(m.whatsapps)||0}</b></span></article><article><i class="bi bi-telephone"></i><span><small>LLAMADAS</small><b>${Number(m.calls)||0}</b></span></article><article><i class="bi bi-list-check"></i><span><small>TAREAS PENDIENTES</small><b>${Number(m.pendingFollowups)||0}</b></span></article><article class="${Number(m.overdueFollowups)>0?'overdue':''}"><i class="bi bi-exclamation-triangle"></i><span><small>TAREAS VENCIDAS</small><b>${Number(m.overdueFollowups)||0}</b></span></article>`;
      if(summary)summary.textContent=d.summary||"Sin actividad registrada en el período.";
      if($("reportFunnel"))$("reportFunnel").innerHTML=`<div><b>${Number(m.analysed)||0}</b><span>Empresas únicas</span></div><i>→</i><div><b>${Number(m.classified)||0}</b><span>Clasificadas</span></div><i>→</i><div><b>${Number(m.contactedCompanies)||0}</b><span>Contactadas</span></div><i>→</i><div><b>${Number(m.replies)||0}</b><span>Respondieron</span></div><i>→</i><div><b>${Number(m.visitsScheduled ?? m.visits)||0}</b><span>Visitas</span></div><i>→</i><div><b>${Number(m.proposals)||0}</b><span>Propuestas</span></div>`;
      const rows=d.companies||[]; if($("reportCount"))$("reportCount").textContent=`${rows.length} empresas`;
      if(box)box.innerHTML=rows.length?`<div class="report-company-row report-company-header"><span>Empresa</span><span>Estado</span><span>Último contacto</span><span>Respondió</span><span>Visita</span><span>Propuesta</span><span>Próxima acción</span></div>${rows.map(row=>`<div class="report-company-row"><strong>${esc(row.company)}</strong><span>${esc(row.status||"CRM")}</span><span>${esc((row.lastContactAt||"").slice(0,10)||"—")}</span><span>${yesNo(row.replied)}</span><span>${row.visitCompleted?'<span class="report-yes">Realizada</span>':row.visitScheduled?'<span class="report-yes">Marcada</span>':'—'}</span><span>${yesNo(row.proposal)}</span><span>${esc(row.nextAction||"—")}</span></div>`).join("")}`:'<p class="report-empty">No hay empresas con actividad comercial relevante en este período.</p>';
    }catch(e){if(box)box.innerHTML=`<p class="report-empty">${esc(e.message)}</p>`;}
  }

  $("reportPeriod")?.addEventListener("change",()=>{document.querySelectorAll(".report-custom").forEach(el=>el.hidden=$("reportPeriod").value!=="custom");loadReports();});
  $("reportUser")?.addEventListener("change",loadReports); $("reportRefresh")?.addEventListener("click",loadReports);
  $("reportCopy")?.addEventListener("click",async()=>{await navigator.clipboard.writeText($("reportSummary")?.textContent||"");toastLocal("Resumen copiado");});
  $("reportCsv")?.addEventListener("click",()=>{window.location.href=`/api/reports/activity.csv?${reportParams()}`;});
  $("reportPdf")?.addEventListener("click",()=>{window.location.href=`/api/reports/activity.pdf?${reportParams()}`;});



  // V15.6 · Importación de histórico comercial
  const importFieldLabels = {
    company:"Empresa*", legal_name:"Razón social", ruc:"RUC / CNPJ", website:"Sitio", sector:"Sector",
    city:"Ciudad", department:"Departamento / Estado", country:"País", company_email:"Correo general empresa",
    company_phone:"Teléfono empresa", company_whatsapp:"WhatsApp empresa", contact_name:"Nombre del contacto",
    contact_role:"Cargo / área", contact_email:"Correo del contacto", contact_phone:"Teléfono del contacto",
    contact_whatsapp:"WhatsApp del contacto", date:"Fecha de interacción", channel:"Canal", status:"Estado CRM",
    observation:"Observación / histórico", next_action:"Próxima acción", next_action_at:"Fecha próxima acción", owner:"Responsable comercial"
  };
  let importPreviewData = null;

  function closeImportHistory(){ $("importHistoryDialog")?.close(); }
  $("importCommercialHistory")?.addEventListener("click",()=>{
    importPreviewData=null;
    if($("importHistoryMapping")) $("importHistoryMapping").hidden=true;
    if($("importHistoryResult")) $("importHistoryResult").hidden=true;
    if($("importHistoryStatus")) $("importHistoryStatus").textContent="";
    $("importHistoryDialog")?.showModal();
  });
  $("closeImportHistory")?.addEventListener("click",closeImportHistory);

  function buildImportMapping(data){
    importPreviewData=data;
    const columns=data.columns||[];
    const detected=data.detectedMapping||{};
    $("importHistoryRows").textContent=`${Number(data.rowCount)||0} filas detectadas`;
    const options=(selected)=>`<option value="">No importar</option>${columns.map(c=>`<option value="${esc(c)}" ${selected===c?"selected":""}>${esc(c)}</option>`).join("")}`;
    $("importHistoryFields").innerHTML=Object.entries(importFieldLabels).map(([field,label])=>`<label>${esc(label)}<select data-import-field="${field}">${options(detected[field]||"")}</select></label>`).join("");
    const sample=data.sample||[];
    if(sample.length){
      const visible=columns.slice(0,10);
      $("importHistoryPreview").innerHTML=`<div class="import-preview-table"><table><thead><tr>${visible.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${sample.map(row=>`<tr>${visible.map(c=>`<td title="${esc(row[c]||"")}">${esc(row[c]||"")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }else $("importHistoryPreview").innerHTML="<p>La planilla no contiene filas de datos.</p>";
    $("importHistoryMapping").hidden=false;
  }

  $("previewImportHistory")?.addEventListener("click",async()=>{
    const file=$("importHistoryFile")?.files?.[0];
    if(!file) return toastLocal("Seleccione una planilla .xlsx o .csv");
    const status=$("importHistoryStatus"); status.textContent="Analizando columnas y coincidencias…";
    const fd=new FormData(); fd.append("file",file);
    try{
      const r=await fetch("/api/imports/history/preview",{method:"POST",body:fd}); const d=await r.json();
      if(!r.ok) throw new Error(d.error||"No se pudo leer la planilla");
      buildImportMapping(d); status.textContent="Planilla lista para revisión";
    }catch(e){status.textContent=e.message; toastLocal(e.message);}
  });

  $("executeImportHistory")?.addEventListener("click",async()=>{
    const file=$("importHistoryFile")?.files?.[0]; if(!file)return toastLocal("Seleccione una planilla");
    const mapping={}; document.querySelectorAll("[data-import-field]").forEach(sel=>{if(sel.value)mapping[sel.dataset.importField]=sel.value;});
    if(!mapping.company)return toastLocal("Seleccione la columna Empresa");
    const button=$("executeImportHistory"); button.disabled=true; button.innerHTML='<span class="spinner-border spinner-border-sm"></span> Consolidando…';
    const fd=new FormData(); fd.append("file",file); fd.append("mapping",JSON.stringify(mapping));
    try{
      const r=await fetch("/api/imports/history",{method:"POST",body:fd}); const d=await r.json();
      if(!r.ok) throw new Error(d.error||"No se pudo importar");
      const result=$("importHistoryResult"); result.hidden=false;
      result.innerHTML=`<strong><i class="bi bi-check2-circle"></i> Importación consolidada</strong><p>El Radar comparó cada fila con las empresas y contactos ya existentes antes de crear nuevos registros.</p><div class="import-result-grid">
        <article><strong>${Number(d.companiesCreated)||0}</strong><span>empresas nuevas</span></article><article><strong>${Number(d.companiesUpdated)||0}</strong><span>empresas existentes encontradas</span></article>
        <article><strong>${Number(d.contactsCreated)||0}</strong><span>contactos nuevos</span></article><article><strong>${Number(d.contactsUpdated)||0}</strong><span>contactos completados</span></article>
        <article><strong>${Number(d.activitiesCreated)||0}</strong><span>interacciones incorporadas</span></article><article><strong>${Number(d.opportunitiesCreated)||0}</strong><span>entradas nuevas en CRM</span></article>
        <article><strong>${Number(d.duplicatesSkipped)||0}</strong><span>duplicados omitidos</span></article><article><strong>${(d.errors||[]).length}</strong><span>filas con revisión</span></article></div>${(d.errors||[]).length?`<div class="import-result-errors">${d.errors.slice(0,8).map(x=>`Fila ${x.row}: ${esc(x.error)}`).join("<br>")}</div>`:""}`;
      toastLocal("Histórico importado y consolidado");
      setTimeout(()=>location.reload(),1200);
    }catch(e){toastLocal(e.message); if($("importHistoryStatus"))$("importHistoryStatus").textContent=e.message;}
    finally{button.disabled=false;button.innerHTML='<i class="bi bi-database-check"></i> Importar y consolidar';}
  });


  openModule("triage");
})();
