(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value = "") => String(value).replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const moduleTitles = {
    triage:"Calificar por sitio", research:"Cola de investigación", salesready:"Listo para ventas", hoy:"Mi día",
    crm:"CRM", pipeline:"Embudo comercial", visitas:"Visitas", radar:"Radar comercial", captacion:"Captación automática",
    oportunidades:"Oportunidades", smartlists:"Listas inteligentes", metrics:"Rendimiento"
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
    if (name === "hoy" && typeof loadToday === "function") loadToday();
    if (name === "radar" && typeof loadCommandCenter === "function") loadCommandCenter();
  }
  window.openWorkspaceModule = openModule;

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
  $("saveContact")?.addEventListener("click",async()=>{const companyId=$("committeeList")?.dataset.companyId;if(!companyId)return toastLocal("Abra primero una oportunidad real");const name=$("contactName").value.trim();if(!name)return toastLocal("Ingrese el nombre");const phone=$("contactPhone").value.trim();const payload={name,role:$("contactRole").value.trim(),buyingRole:$("contactBuyingRole").value,email:$("contactEmail").value.trim(),phone,whatsapp:phone,influence:$("contactBuyingRole").value==="DECISION_MAKER"?90:70,confidence:70};const r=await fetch(`/api/companies/${companyId}/contacts`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!r.ok)return toastLocal("No se pudo guardar el contacto");["contactName","contactRole","contactEmail","contactPhone"].forEach((id)=>$(id).value="");toastLocal("Contacto añadido al Comité de compra");loadCommittee();loadWorkspace(true)});

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

  openModule("triage");
})();
