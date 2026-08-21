const leads = Array.isArray(window.RADAR_LEADS) ? window.RADAR_LEADS : [];
const brandName = (window.RADAR_BRAND && window.RADAR_BRAND.brand_name) || "Radar Comercial Industrial";
let selected = leads[0] || null;
let level = "ALL";
let selectedChannel = "whatsapp";
let selectedCompanyId = null;
let drawerContacts = [];
let drawerMessageSeq = 0;
const visitSelection = new Set();
let discoveredCompanies = [];
const pipelineStages = [
  ["NOVO", "NUEVO"], ["QUALIFICADO", "CALIFICADO"], ["CONTATO_REALIZADO", "CONTACTADO"],
  ["RESPONDEU", "RESPONDIÓ"], ["VISITA", "VISITA"], ["ORCAMENTO", "PRESUPUESTO"], ["NEGOCIACAO", "NEGOCIACIÓN"],
];

const $ = (id) => document.getElementById(id);

function initials(name = "") {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

function priorityLabel(priority) {
  return { HOT: "URGENTE", HIGH: "ALTA", MEDIUM: "MEDIA" }[priority] || priority || "MEDIA";
}

function eventLabel(eventType) {
  return {
    NEW_FACTORY: "NUEVA FÁBRICA",
    NEW_LOGISTICS_CENTER: "NUEVO CENTRO LOGÍSTICO",
    EXPANSION: "EXPANSIÓN",
    INVESTMENT: "INVERSIÓN",
    BUYING_INTENT: "INTENCIÓN DE COMPRA",
    NEW_COMPANY: "NUEVA EMPRESA",
    NEW_WAREHOUSE: "NUEVO DEPÓSITO",
  }[eventType] || eventType || "NO INFORMADO";
}

function tag(priority, score) {
  const safePriority = escapeHtml(priority || "MEDIUM");
  return `<span class="level ${safePriority.toLowerCase()}">${escapeHtml(priorityLabel(priority))} · ${Number(score) || 0}</span>`;
}

function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.style.display = "block";
  window.setTimeout(() => { element.style.display = "none"; }, 2200);
}

function render() {
  const query = $("search").value.trim().toLowerCase();
  const rows = leads.filter((lead) => {
    const matchesLevel = level === "ALL" || lead.level === level;
    const searchable = `${lead.company || ""} ${lead.city || ""} ${lead.department || ""} ${lead.sector || ""} ${lead.project || ""}`.toLowerCase();
    return matchesLevel && searchable.includes(query);
  });

  $("resultCount").textContent = `${rows.length} resultados`;
  $("leadList").innerHTML = rows.map((lead) => `
    <button class="lead ${selected && selected.id === lead.id ? "selected" : ""}" data-id="${escapeHtml(lead.id)}">
      <span class="avatar">${escapeHtml(initials(lead.company))}</span>
      <span>
        <span><h3>${escapeHtml(lead.company)}</h3>${tag(lead.level, lead.score)}</span>
        <strong>${escapeHtml(lead.project)}</strong>
        <small>⌖ ${escapeHtml(lead.city)}, ${escapeHtml(lead.department)}</small>
      </span>
      <span>›</span>
    </button>
  `).join("") || "<p>No se encontraron oportunidades.</p>";

  document.querySelectorAll(".lead").forEach((button) => {
    button.addEventListener("click", () => {
      const lead = leads.find((item) => String(item.id) === button.dataset.id);
      if (lead) selectLead(lead);
    });
  });
  renderCrm();
  renderKanban();
}

function money(value) {
  return new Intl.NumberFormat("es-PY", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(Number(value) || 0);
}

function renderKanban() {
  const board = $("kanbanBoard");
  if (!board) return;
  board.innerHTML = pipelineStages.map(([status, label]) => {
    const rows = leads.filter((lead) => lead.status === status);
    return `<section class="kanban-column" data-status="${status}"><header>${label}<span>${rows.length}</span></header>${rows.map((lead) => `<article class="kanban-card" data-id="${escapeHtml(lead.id)}"><h4>${escapeHtml(lead.company)}</h4><p>${escapeHtml(lead.project)}</p><b>${money(lead.estimatedValue)} · ${Number(lead.probability) || 0}%</b><select class="kanban-status">${pipelineStages.map(([value, text]) => `<option value="${value}" ${value === lead.status ? "selected" : ""}>${text}</option>`).join("")}<option value="GANHO">GANADO</option><option value="PERDIDO">PERDIDO</option></select></article>`).join("")}</section>`;
  }).join("");
}

function contactMessage(lead, channel = selectedChannel) {
  const products = (lead.products || []).slice(0, 3).join(", ") || "soluciones de accesos automáticos";
  const context = lead.whyNow || `${lead.company} presenta una operación que puede requerir soluciones de acceso industrial.`;
  const next = lead.nextBestAction || "validar el responsable técnico y el cronograma de la operación";
  const role = "Mantenimiento, Ingeniería, Infraestructura, Operaciones, Logística o Proyectos";
  if (channel === "email") return `Asunto: ${brandName} | Soluciones industriales para ${lead.company}\n\nEstimado equipo de ${lead.company},\n\nMi nombre es David Granja y formo parte del equipo comercial de ${brandName}. Estuvimos revisando información pública sobre su operación en ${lead.city || "Paraguay"} y detectamos un contexto que puede tener aplicación para ${products}.\n\n${context}\n\nSomos fábrica especializada en soluciones de accesos automáticos para operaciones industriales, logísticas y comerciales. Nuestro objetivo no es enviar un catálogo genérico, sino entender la etapa y las necesidades de la operación para evaluar una solución adecuada, incluyendo instalación, mantenimiento, modernización y soporte técnico.\n\n¿Podrían indicarme quién es la persona responsable de ${role}? Me gustaría coordinar una conversación breve para ${next}.\n\nQuedo a disposición.\n\nSaludos cordiales,\nDavid Granja\n${brandName}`;
  if (channel === "call") return `GUION DE LLAMADA\n\n1. Presentarse como David Granja, de ${brandName}.\n2. Mencionar el contexto: ${context}\n3. Pedir al responsable de ${role}.\n4. Validar etapa, cronograma, accesos industriales, áreas de carga y necesidades de ${products}.\n5. Objetivo de la llamada: ${next}.\n6. Cerrar proponiendo visita técnica o conversación de 15 minutos.`;
  if (channel === "linkedin") return `Hola. Soy David Granja, de ${brandName}. Estuvimos conociendo la operación de ${lead.company} y vimos un posible encaje para ${products}. Me gustaría conectar con la persona responsable de ${role} para entender la etapa actual y evaluar si podemos aportar una solución técnica. ¿Podría orientarme con el contacto adecuado?`;
  return `Hola, ¿cómo está? Soy David Granja, de ${brandName}. Estuve conociendo la operación de ${lead.company} y detectamos un posible encaje para ${products}. ${context}\n\nQuisiera hablar con la persona responsable de ${role} para entender la etapa actual y verificar si podemos aportar una solución adecuada. ¿Podría indicarme con quién debería conversar?`;
}

function renderCrm() {
  const grid = $("crmGrid");
  if (!grid) return;
  const status = $("crmStatusFilter").value;
  const rows = leads.filter((lead) => status === "ALL" || lead.status === status);
  $("crmCount").textContent = `${rows.length} empresas`;
  grid.innerHTML = rows.map((lead) => {
    const address = lead.address || `${lead.city || ""}, ${lead.department || ""}, Paraguay`;
    return `<article class="crm-card" data-id="${escapeHtml(lead.id)}">
      <div class="crm-card-top"><span class="avatar">${escapeHtml(initials(lead.company))}</span><div><h3>${escapeHtml(lead.company)}</h3><p>${escapeHtml(lead.sector)} · ${escapeHtml(lead.city)}</p></div>${tag(lead.level, lead.score)}</div>
      <strong>${escapeHtml(lead.project)}</strong><small><i class="bi bi-geo-alt"></i> ${escapeHtml(address)}</small>
      <div class="crm-flags"><span class="${lead.contactVerified ? "verified" : "pending"}"><i class="bi bi-${lead.contactVerified ? "person-check-fill" : "person-exclamation"}"></i> ${lead.contactVerified ? "Contacto validado" : "Validar contacto"}</span>${lead.nextActionAt ? `<span><i class="bi bi-calendar-event"></i> ${new Date(lead.nextActionAt).toLocaleDateString("es-PY")}</span>` : ""}</div>
      <div class="crm-card-actions"><button class="open-company-dossier"><i class="bi bi-building"></i> Ficha 360°</button><label><input class="visit-check" type="checkbox" ${visitSelection.has(String(lead.id)) ? "checked" : ""}> Incluir en visita</label></div>
    </article>`;
  }).join("") || '<div class="empty-signals"><strong>No hay empresas en este estado.</strong></div>';
}

function renderRoutePlan() {
  const selectedLeads = leads.filter((lead) => visitSelection.has(String(lead.id)))
    .sort((a, b) => `${a.department} ${a.city}`.localeCompare(`${b.department} ${b.city}`));
  if (!selectedLeads.length) {
    $("routePlan").innerHTML = '<div class="route-empty"><i class="bi bi-geo-alt"></i><strong>Ninguna empresa seleccionada</strong><span>Marque “Incluir en visita” en la Caja CRM.</span></div>';
    return;
  }
  $("routePlan").innerHTML = `<div class="route-summary"><b>${selectedLeads.length} visitas seleccionadas</b><span>Ordenadas por región y ciudad</span></div>${selectedLeads.map((lead, index) => {
    const address = lead.address || `${lead.city}, ${lead.department}, Paraguay`;
    return `<article class="route-stop"><span>${index + 1}</span><div><h3>${escapeHtml(lead.company)}</h3><p>${escapeHtml(lead.sector)} · ${escapeHtml(address)}</p><b>Ofrecer:</b> ${escapeHtml((lead.products || []).join(", ") || "Evaluación técnica de accesos")}<br><b>Dolores probables:</b> ${escapeHtml((lead.painPoints || []).join(", "))}</div><a href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}" target="_blank" rel="noopener" aria-label="Abrir ubicación"><i class="bi bi-geo-alt-fill"></i></a></article>`;
  }).join("")}`;
}

function selectLead(lead) {
  if (!lead) return;
  selected = lead;
  $("initials").textContent = initials(lead.company);
  $("companyName").textContent = lead.company || "Empresa no informada";
  $("companyMeta").textContent = `${lead.sector || "Sector no informado"} · ${lead.origin || "Paraguay"}`;
  $("companyPlace").textContent = `⌖ ${lead.city || "Ciudad no informada"}, ${lead.department || ""}`;
  $("drawerLevel").className = `level ${(lead.level || "MEDIUM").toLowerCase()}`;
  $("drawerLevel").textContent = `${priorityLabel(lead.level)} · ${Number(lead.score) || 0}`;
  $("whyText").textContent = lead.whyNow || `${lead.project || "El proyecto"} puede generar demanda de accesos industriales en áreas de operación, carga y circulación de vehículos.`;
  $("eventType").textContent = eventLabel(lead.event);
  $("stage").textContent = lead.stage || "Por validar";
  $("investment").textContent = lead.investment || "No divulgado";
  $("productList").innerHTML = (lead.products || []).map((product) => `<span>${escapeHtml(product)}</span>`).join("");
  $("evidenceText").textContent = lead.evidence || "No hay evidencia registrada.";
  $("status").value = lead.status || "NOVO";
  $("contactVerified").checked = Boolean(lead.contactVerified);
  $("followUpDate").value = lead.nextActionAt ? String(lead.nextActionAt).slice(0, 10) : "";
  $("dealOwner").value = lead.owner || "Equipo comercial";
  $("dealValue").value = Number(lead.estimatedValue) || 0;
  $("dealProbability").value = Number(lead.probability) || 20;
  $("approach").value = "Cargando mensaje contextual del CRM…";
  $("drawerMessageRecipient") && ($("drawerMessageRecipient").value = "");
  updateChannelAction();
  loadUnifiedDrawerMessaging(lead);
  render();
}

function updateChannelAction() {
  if (!selected) return;
  const labels = { whatsapp: "Enviar por WhatsApp", email: "Redactar correo", call: "Iniciar llamada", linkedin: "Abrir LinkedIn" };
  $("openChannel").innerHTML = `<i class="bi bi-box-arrow-up-right"></i> ${labels[selectedChannel]}`;
  if (selectedChannel === "linkedin") {
    $("approach").value = contactMessage(selected, "linkedin");
    if ($("drawerMessageSubjectWrap")) $("drawerMessageSubjectWrap").hidden = true;
    if ($("drawerMessageRecipient")) $("drawerMessageRecipient").value = selected.linkedin || "";
  } else {
    generateUnifiedDrawerMessage();
  }
}

async function resolveSelectedCompanyId(lead = selected) {
  if (!lead) return null;
  if (lead.companyId) return Number(lead.companyId);
  const r = await fetch(`/api/companies?q=${encodeURIComponent(lead.company || "")}`);
  const d = await r.json().catch(() => ({}));
  const row = (d.items || []).find(x => x.name === lead.company) || (d.items || [])[0];
  return row?.id ? Number(row.id) : null;
}

async function loadUnifiedDrawerMessaging(lead = selected, preferredContactId = null) {
  if (!lead) return;
  const companyId = await resolveSelectedCompanyId(lead);
  selectedCompanyId = companyId;
  drawerContacts = [];
  const select = $("drawerMessageContact");
  if (!companyId) {
    if (select) select.innerHTML = '<option value="">Empresa no localizada</option>';
    $("approach").value = "No se pudo localizar la empresa en el CRM.";
    return;
  }
  try {
    const r = await fetch(`/api/companies/${companyId}/contacts`);
    drawerContacts = r.ok ? await r.json() : [];
  } catch (_) { drawerContacts = []; }
  if (select) {
    select.innerHTML = '<option value="">Equipo / contacto general</option>' + drawerContacts.map(c => `<option value="${c.id}">${escapeHtml(c.name || c.role || "Contacto")}${c.role ? ` · ${escapeHtml(c.role)}` : ""} · ${escapeHtml(c.email || c.whatsapp || c.phone || "sin contacto directo")}</option>`).join("");
    if (preferredContactId && drawerContacts.some(c => String(c.id) === String(preferredContactId))) select.value = String(preferredContactId);
  }
  await generateUnifiedDrawerMessage();
}

async function generateUnifiedDrawerMessage() {
  if (!selected || !selectedCompanyId || selectedChannel === "linkedin") return;
  const seq = ++drawerMessageSeq;
  const channel = { whatsapp: "WHATSAPP", email: "EMAIL", call: "CALL" }[selectedChannel] || "EMAIL";
  const contactId = $("drawerMessageContact")?.value || null;
  if ($("approach")) $("approach").value = "Generando mensaje contextual…";
  try {
    const r = await fetch(`/api/companies/${selectedCompanyId}/message`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ contactId, channel, opportunityId: selected.id }) });
    const d = await r.json();
    if (!r.ok || seq !== drawerMessageSeq) return;
    $("approach").value = d.body || "";
    if ($("drawerMessageRecipient")) $("drawerMessageRecipient").value = d.recipient || "";
    if ($("drawerMessageSubject")) $("drawerMessageSubject").value = channel === "EMAIL" ? (d.subject || "") : "";
    if ($("drawerMessageSubjectWrap")) $("drawerMessageSubjectWrap").hidden = channel !== "EMAIL";
  } catch (_) {
    if (seq === drawerMessageSeq) $("approach").value = "No se pudo generar el mensaje desde el CRM.";
  }
}

function activateTab(tabName) {
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  ["overview", "committee", "evidence", "timeline"].forEach((name) => {
    $(name + "Panel").classList.toggle("hidden", name !== tabName);
  });
}

async function loadTimeline() {
  activateTab("timeline");
  if (!selected) return;
  if (selected.demo) {
    $("timelineList").innerHTML = "<article><i></i><small>DESCUBRIMIENTO</small><strong>Evento de demostración identificado por el radar</strong></article>";
    return;
  }
  try {
    const response = await fetch(`/api/timeline/${selected.id}`);
    if (!response.ok) throw new Error("No se pudo cargar la cronología");
    const rows = await response.json();
    $("timelineList").innerHTML = rows.map((event) => `<article><i></i><small>${escapeHtml(event.type)}</small><strong>${escapeHtml(event.description)}</strong></article>`).join("") || "<p>No hay eventos registrados.</p>";
  } catch (_error) {
    toast("No se pudo cargar la cronología");
  }
}

document.querySelectorAll(".filters button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".filters button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    level = button.dataset.level;
    render();
  });
});

$("search").addEventListener("input", render);
$("crmStatusFilter").addEventListener("change", renderCrm);

$("crmGrid").addEventListener("click", (event) => {
  const card = event.target.closest(".crm-card");
  if (!card) return;
  const lead = leads.find((item) => String(item.id) === card.dataset.id);
  if (!lead) return;
  if (event.target.closest(".open-crm-detail")) {
    selectLead(lead);
    document.body.classList.add("drawer-open");
  }
  if (event.target.matches(".visit-check")) {
    if (event.target.checked) visitSelection.add(String(lead.id)); else visitSelection.delete(String(lead.id));
    renderRoutePlan();
  }
});

document.querySelectorAll(".tabs button").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.dataset.tab === "timeline") await loadTimeline();
    else activateTab(button.dataset.tab);
  });
});

$("status").addEventListener("change", async (event) => {
  if (!selected) return;
  if (selected.demo) {
    toast("DATOS DE DEMOSTRACIÓN: registre una oportunidad para guardarla en el CRM");
    event.target.value = selected.status || "NOVO";
    return;
  }
  try {
    const response = await fetch(`/api/opportunities/${selected.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: event.target.value }),
    });
    if (!response.ok) throw new Error("No se pudo guardar el estado");
    selected.status = event.target.value;
    toast("Estado guardado en PostgreSQL");
  } catch (_error) {
    event.target.value = selected.status || "NOVO";
    toast("No se pudo guardar el estado");
  }
});

$("contactVerified").addEventListener("change", async (event) => {
  if (!selected || selected.demo) return toast("Registre una oportunidad real para validar el contacto");
  const response = await fetch(`/api/opportunities/${selected.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ contactVerified: event.target.checked }) });
  if (!response.ok) {
    event.target.checked = !event.target.checked;
    return toast("No se pudo guardar la validación");
  }
  selected.contactVerified = event.target.checked;
  renderCrm();
  toast("Validación del contacto guardada");
});

$("scheduleFollowUp").addEventListener("click", async () => {
  if (!selected || selected.demo) return toast("Registre una oportunidad real para programar seguimiento");
  const date = $("followUpDate").value;
  if (!date) return toast("Seleccione la fecha del próximo seguimiento");
  const response = await fetch(`/api/opportunities/${selected.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nextActionAt: `${date}T12:00:00` }) });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "No se pudo programar el seguimiento");
  selected.nextActionAt = data.nextActionAt;
  renderCrm();
  toast("Seguimiento programado en el CRM");
});

$("saveDealData").addEventListener("click", async () => {
  if (!selected || selected.demo) return toast("Seleccione una oportunidad real");
  const payload = { owner: $("dealOwner").value, estimatedValue: $("dealValue").value, probability: $("dealProbability").value };
  const response = await fetch(`/api/opportunities/${selected.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) return toast(data.error || "No se pudieron guardar los datos");
  Object.assign(selected, data); render(); toast("Datos comerciales guardados");
});

$("kanbanBoard").addEventListener("change", async (event) => {
  if (!event.target.matches(".kanban-status")) return;
  const card = event.target.closest(".kanban-card");
  const lead = leads.find((item) => String(item.id) === card.dataset.id);
  if (!lead || lead.demo) return toast("Los datos de demostracións no se pueden mover");
  const oldStatus = lead.status;
  const response = await fetch(`/api/opportunities/${lead.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: event.target.value }) });
  if (!response.ok) { event.target.value = oldStatus; return toast("No se pudo mover la oportunidad"); }
  lead.status = event.target.value; render(); toast("Oportunidad movida en el pipeline");
});

$("copyApproach").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("approach").value);
    toast("Mensaje copiado");
  } catch (_error) {
    $("approach").select();
    document.execCommand("copy");
    toast("Mensaje copiado");
  }
});

document.querySelectorAll(".channels button").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll(".channels button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    selectedChannel = button.dataset.channel;
    updateChannelAction();
    toast(`Canal seleccionado: ${button.textContent.trim()}`);
  });
});

$("drawerMessageContact")?.addEventListener("change", generateUnifiedDrawerMessage);
$("copyDrawerRecipient")?.addEventListener("click", async () => {
  const value = $("drawerMessageRecipient")?.value || "";
  if (!value) return toast("No hay destinatario para copiar");
  await navigator.clipboard.writeText(value);
  toast("Destinatario copiado");
});

window.addEventListener("radar:contact-updated", (event) => {
  const detail = event.detail || {};
  if (selected && String(detail.companyId || "") === String(selectedCompanyId || selected.companyId || "")) loadUnifiedDrawerMessaging(selected, detail.contactId || null);
});
window.addEventListener("radar:company-contact-updated", (event) => {
  const detail = event.detail || {};
  if (selected && String(detail.companyId || "") === String(selectedCompanyId || selected.companyId || "")) loadUnifiedDrawerMessaging(selected);
});

$("openChannel").addEventListener("click", () => {
  if (!selected) return;
  const message = $("approach")?.value || "";
  const recipient = $("drawerMessageRecipient")?.value || "";
  let url;
  if (selectedChannel === "whatsapp") {
    const number = String(recipient).replace(/\D/g, "");
    if (!number) return toast("Este destinatario todavía no tiene WhatsApp registrado");
    url = `https://wa.me/${number}?text=${encodeURIComponent(message)}`;
  } else if (selectedChannel === "email") {
    if (!recipient) return toast("Este destinatario todavía no tiene correo registrado");
    const subject = $("drawerMessageSubject")?.value || "";
    url = `mailto:${recipient}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(message)}`;
  } else if (selectedChannel === "call") {
    if (!recipient) return toast("Este destinatario todavía no tiene teléfono registrado");
    url = `tel:${recipient}`;
  } else {
    url = selected.linkedin || `https://www.linkedin.com/search/results/companies/?keywords=${encodeURIComponent(selected.company)}`;
  }
  window.open(url, "_blank", "noopener");
  const confirmButton = $("confirmChannelSent");
  if (confirmButton) {
    confirmButton.hidden = !["whatsapp","email"].includes(selectedChannel);
    confirmButton.dataset.channel = selectedChannel;
    confirmButton.dataset.companyId = String(selectedCompanyId || "");
    confirmButton.dataset.contactId = String($("drawerMessageContact")?.value || "");
  }
});

$("confirmChannelSent")?.addEventListener("click", async () => {
  const companyId = Number($("confirmChannelSent").dataset.companyId || selectedCompanyId || 0);
  if (!companyId) return toast("Empresa no localizada en el CRM");
  const channel = $("confirmChannelSent").dataset.channel || selectedChannel;
  const activityType = channel === "whatsapp" ? "WHATSAPP_SENT" : "EMAIL_SENT";
  const contactId = $("confirmChannelSent").dataset.contactId || null;
  const subject = channel === "email" ? ($("drawerMessageSubject")?.value || "Correo comercial") : "WhatsApp comercial";
  const summary = channel === "email" ? "Correo comercial enviado desde el Radar." : "WhatsApp comercial enviado desde el Radar.";
  try {
    const r = await fetch(`/api/companies/${companyId}/activities`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({type:activityType,contactId,subject,summary,outcome:"SENT"})});
    const d = await r.json().catch(()=>({}));
    if(!r.ok) throw new Error(d.error || "No se pudo registrar el envío");
    $("confirmChannelSent").hidden = true;
    toast(channel === "whatsapp" ? "WhatsApp registrado como enviado" : "Correo registrado como enviado");
  } catch(e) { toast(e.message); }
});

$("buildRoute").addEventListener("click", () => {
  const rows = leads.filter((lead) => visitSelection.has(String(lead.id)))
    .sort((a, b) => `${a.department} ${a.city}`.localeCompare(`${b.department} ${b.city}`));
  if (!rows.length) return toast("Seleccione al menos una empresa para la visita");
  const locations = rows.slice(0, 10).map((lead) => lead.address || `${lead.city}, ${lead.department}, Paraguay`);
  const params = new URLSearchParams({ api: "1", origin: $("routeOrigin").value || "Asunción, Paraguay", destination: locations.at(-1), travelmode: "driving" });
  if (locations.length > 1) params.set("waypoints", locations.slice(0, -1).join("|"));
  window.open(`https://www.google.com/maps/dir/?${params}`, "_blank", "noopener");
});

document.querySelectorAll(".pin").forEach((button, index) => {
  button.addEventListener("click", () => {
    if (leads[index]) selectLead(leads[index]);
  });
});

const dialog = $("leadDialog");
$("newLead").addEventListener("click", () => dialog.showModal());
$("closeDialog").addEventListener("click", () => dialog.close());

$("leadForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.score = Number(data.score);
  $("formMessage").textContent = "Guardando...";
  try {
    const response = await fetch("/api/opportunities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error("No se pudo registrar la oportunidad");
    $("formMessage").textContent = "Oportunidad guardada. Actualizando...";
    window.setTimeout(() => window.location.reload(), 500);
  } catch (_error) {
    $("formMessage").textContent = "Verifique los campos y la conexión con la base de datos.";
  }
});

$("findCompanies").addEventListener("click", async () => {
  const button = $("findCompanies");
  const params = new URLSearchParams({
    q: $("search").value.trim(), city: $("searchCity").value.trim(),
    region: $("searchRegion").value, industry: $("searchIndustry").value,
  });
  button.disabled = true;
  button.innerHTML = '<i class="bi bi-hourglass-split"></i> Buscando...';
  $("companySearchResults").classList.remove("hidden");
  $("companySearchMessage").textContent = "Consultando empresas y establecimientos públicos en Paraguay...";
  $("companyResultGrid").innerHTML = "";
  try {
    const response = await fetch(`/api/company-search?${params}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No se pudo realizar la búsqueda");
    discoveredCompanies = data.results || [];
    $("companySearchMessage").textContent = `${discoveredCompanies.length} empresas o establecimientos encontrados. Valide los datos antes de contactar.`;
    $("companyResultGrid").innerHTML = discoveredCompanies.map((company, index) => `<article class="company-result" data-index="${index}">
      <div><span class="source-type">${escapeHtml(company.source)} · POTENCIAL ${Number(company.score)}</span><h3>${escapeHtml(company.company)}</h3><p>${escapeHtml(company.sector)} · ${escapeHtml(company.city)}, ${escapeHtml(company.region)}</p></div>
      <p><i class="bi bi-geo-alt"></i> ${escapeHtml(company.address || "Dirección por validar")}</p>
      <div class="result-contacts">${company.website ? `<a href="${escapeHtml(company.website)}" target="_blank" rel="noopener"><i class="bi bi-globe2"></i> Sitio</a>` : ""}${company.phone ? `<span><i class="bi bi-telephone"></i> ${escapeHtml(company.phone)}</span>` : ""}${company.email ? `<span><i class="bi bi-envelope"></i> ${escapeHtml(company.email)}</span>` : ""}</div>
      <div class="result-actions">${company.website ? '<button class="analyze-discovered"><i class="bi bi-building-check"></i> Analizar sitio</button>' : ""}<button class="add-discovered primary"><i class="bi bi-inbox-fill"></i> Añadir al CRM</button></div>
    </article>`).join("") || '<div class="empty-signals"><strong>No encontramos empresas con estos criterios.</strong><span>Pruebe otra ciudad, región o actividad.</span></div>';
    $("companySearchResults").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    $("companySearchMessage").textContent = error.message;
  } finally {
    button.disabled = false;
    button.innerHTML = '<i class="bi bi-buildings"></i> Buscar empresas';
  }
});

$("closeCompanySearch").addEventListener("click", () => $("companySearchResults").classList.add("hidden"));

$("companyResultGrid").addEventListener("click", async (event) => {
  const card = event.target.closest(".company-result");
  if (!card) return;
  const company = discoveredCompanies[Number(card.dataset.index)];
  if (!company) return;
  if (event.target.closest(".analyze-discovered")) {
    $("companyWebsite").value = company.website;
    $("triage").scrollIntoView({ behavior: "smooth" });
    toast("Sitio preparado para el análisis minucioso");
    return;
  }
  const addButton = event.target.closest(".add-discovered");
  if (!addButton) return;
  addButton.disabled = true;
  addButton.textContent = "Añadiendo...";
  try {
    const response = await fetch("/api/company-search/add", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(company) });
    const lead = await response.json();
    if (!response.ok) throw new Error(lead.error || "No se pudo añadir al CRM");
    leads.unshift(lead);
    selectLead(lead);
    card.remove();
    toast("Empresa añadida a la Caja CRM");
  } catch (error) {
    addButton.disabled = false;
    addButton.innerHTML = '<i class="bi bi-inbox-fill"></i> Añadir al CRM';
    toast(error.message);
  }
});

document.querySelectorAll('.sidebar nav a[href^="#"]').forEach((link) => {
  link.addEventListener("click", async (event) => {
    const target = link.getAttribute("href");
    document.querySelectorAll(".sidebar nav a").forEach((item) => item.classList.remove("active"));
    link.classList.add("active");

    if (target === "#crm") {
      event.preventDefault();
      $("crm").scrollIntoView({ behavior: "smooth" });
      toast("Caja CRM: todas las empresas clasificadas");
    } else if (target === "#visitas") {
      event.preventDefault();
      $("visitas").scrollIntoView({ behavior: "smooth" });
    } else if (target === "#timeline") {
      event.preventDefault();
      await loadTimeline();
    } else if (target === "#pesquisas") {
      event.preventDefault();
      $("search").focus();
      window.scrollTo({ top: 0, behavior: "smooth" });
      toast("Busque por empresa, ciudad, región o tipo de industria");
    }
  });
});

$("drawerMenu").addEventListener("click", () => toast("Seleccione una oportunidad para ver las acciones"));

$("runCollector").addEventListener("click", async () => {
  const button = $("runCollector");
  button.disabled = true;
  button.textContent = "Buscando empresas y proyectos...";
  $("collectorMessage").textContent = "Consultando fuentes públicas. Esto puede tardar algunos segundos.";
  try {
    const response = await fetch("/api/collector/run", { method: "POST" });
    const data = await response.json();
    if (!response.ok && response.status !== 429) throw new Error(data.error || "Error de captación");
    const run = data.run;
    $("collectorMessage").textContent = `${run.itemsScanned} elementos analizados · ${run.signalsCreated} señales nuevas`;
    window.setTimeout(() => window.location.reload(), 900);
  } catch (_error) {
    button.disabled = false;
    button.textContent = "⚙ Ejecutar búsqueda ahora";
    $("collectorMessage").textContent = "No se pudo completar la búsqueda. Intente nuevamente.";
  }
});

document.querySelectorAll(".approve-signal").forEach((button) => {
  button.addEventListener("click", async () => {
    const card = button.closest(".prospect-card");
    button.disabled = true;
    button.textContent = "Convirtiendo...";
    const response = await fetch(`/api/signals/${card.dataset.signalId}/approve`, { method: "POST" });
    if (response.ok) {
      card.remove();
      toast("Señal convertida en oportunidad del CRM");
      window.setTimeout(() => window.location.reload(), 700);
    } else {
      button.disabled = false;
      button.textContent = "Convertir en oportunidad";
      toast("No se pudo convertir la señal");
    }
  });
});

document.querySelectorAll(".discard-signal").forEach((button) => {
  button.addEventListener("click", async () => {
    const card = button.closest(".prospect-card");
    const response = await fetch(`/api/signals/${card.dataset.signalId}/discard`, { method: "POST" });
    if (response.ok) {
      card.remove();
      toast("Señal descartada");
    } else toast("No se pudo descartar la señal");
  });
});

function renderWebsiteAnalysis(analysis) {
  const list = (values, fallback = "No encontrado") => Array.isArray(values) && values.length ? values.map(escapeHtml).join(", ") : fallback;
  const decision = analysis.decision || "PENDING";
  const decisionLabel = { QUALIFIED: "CALIFICADA", DISQUALIFIED: "DESCALIFICADA", PENDING: "PENDIENTE" }[decision];
  const scanMode = analysis.scanMode || (analysis.status === "QUICK" ? "quick" : "deep");
  const scanLabel = scanMode === "quick" ? "ANÁLISIS RÁPIDO" : (analysis.cached ? "RESULTADO EN CACHÉ" : "ANÁLISIS PROFUNDO");
  const decisionActions = decision === "PENDING"
    ? '<button class="qualify-analysis">Clasificar e ingresar al CRM</button><button class="disqualify-analysis">Desclasificar</button>'
    : `<strong>${decision === "QUALIFIED" ? "✓ Empresa ingresada al CRM" : "Empresa desclasificada"}</strong>`;
  const deepAction = scanMode === "quick" ? '<button class="deep-analysis"><i class="bi bi-arrow-repeat"></i> Profundizar ahora</button>' : '';
  return `
    <article class="analysis-card ${scanMode === "quick" ? "quick-result" : "deep-result"}" data-analysis-id="${escapeHtml(analysis.id)}" data-decision="${escapeHtml(decision)}">
      <div class="analysis-score"><strong>${Number(analysis.score) || 0}</strong><small>${escapeHtml(analysis.level)}</small></div>
      <div class="analysis-main"><span class="source-type"><i class="bi ${scanMode === "quick" ? "bi-lightning-charge" : "bi-check2-circle"}"></i> ${scanLabel} · ${Number(analysis.pagesAnalyzed) || 0} PÁGINAS · ${decisionLabel}</span><h3>${escapeHtml(analysis.company)}</h3><p><b>Sector:</b> ${escapeHtml(analysis.sector)} · <b>Tamaño:</b> ${escapeHtml(analysis.companySize)}</p><a href="${escapeHtml(analysis.url)}" target="_blank" rel="noopener">Abrir sitio ↗</a></div>
      <div class="analysis-grid">
        <div><b>Contacto</b><span>${list(analysis.emails)}</span><span>${list(analysis.phones)}</span>${analysis.whatsapp ? `<span>WhatsApp: ${escapeHtml(analysis.whatsapp)}</span>` : ""}</div>
        <div><b>Dirección y responsables</b><span>${escapeHtml(analysis.address || "No encontrado")}</span><span>${list(analysis.contacts, "No identificado")}</span></div>
        <div><b>Productos probables</b><span>${list(analysis.products, "Requiere validación")}</span></div>
        <div><b>Servicios recomendados</b><span>${list(analysis.services)}</span></div>
      </div>
      <div class="analysis-reasons"><b>Razones de la calificación</b><span>${list(analysis.reasons, "Sin evidencia suficiente")}</span></div>
      ${analysis.enrichment && Object.keys(analysis.enrichment).length ? `<div class="analysis-autofill"><div><b><i class="bi bi-magic"></i> Datos preparados para la ficha 360°</b><span>El radar completará automáticamente los campos seguros al ingresar la empresa al CRM.</span></div><div class="autofill-grid"><span><small>Razón social</small><strong>${escapeHtml(analysis.enrichment.legalName || 'Por validar')}</strong></span><span><small>RUC</small><strong>${escapeHtml(analysis.enrichment.ruc || 'Por validar')}</strong></span><span><small>Fundación</small><strong>${escapeHtml(analysis.enrichment.foundedYear || 'Por validar')}</strong></span><span><small>Plantas / unidades</small><strong>${Number((analysis.enrichment.operationPlants||[]).length)}</strong></span><span><small>Redes detectadas</small><strong>${Number(Object.keys(analysis.enrichment.socialLinks||{}).length)}</strong></span><span><small>Revisión manual</small><strong>${Number((analysis.enrichment.reviewRequired||[]).length)} campo(s)</strong></span></div></div>` : ''}
      ${Array.isArray(analysis.alternativeSites) && analysis.alternativeSites.length ? `<div class="site-alternative-notice"><div><b>Presencia digital relacionada detectada</b><span>${analysis.alternativeSites.length} sitio(s) alternativo(s) o redirección(es) vinculados al dominio analizado.</span></div><button class="show-site-alternatives">Ver sitios relacionados</button></div>` : ''}
      <div class="analysis-decision">${deepAction}${decisionActions}</div>
    </article>`;
}

function siteErrorText(details={}) {
  return {
    INVALID_URL:"Dirección web no válida", DNS_ERROR:"Dominio no localizado", TIMEOUT:"Tiempo de espera agotado",
    ACCESS_BLOCKED:"Acceso bloqueado por el sitio", SSL_ERROR:"Problema de seguridad HTTPS", NOT_FOUND:"Sitio no encontrado",
    REMOTE_SERVER_ERROR:"Servidor temporalmente indisponible", CONNECTION_ERROR:"No fue posible conectar", HTTP_ERROR:"Respuesta HTTP con error",
    SITE_VALIDATION_ERROR:"No fue posible validar el sitio", UNKNOWN_ERROR:"Error técnico del analizador"
  }[details.category] || details.title || "No fue posible analizar el sitio";
}

function renderAlternativeSites(alternatives=[]) {
  if (!alternatives.length) return '<div class="diagnostic-empty">No se encontró otra dirección accesible relacionada automáticamente. Puede verificar el nombre de la empresa en una búsqueda externa y pegar el nuevo sitio en el calificador.</div>';
  return alternatives.map((alt,index)=>`<article class="alternative-site-row" data-alt-url="${escapeHtml(alt.url)}">
    <div class="alternative-confidence"><b>${Number(alt.confidence)||0}%</b><small>confianza</small></div>
    <div><strong>${escapeHtml(alt.title || alt.host || alt.url)}</strong><a href="${escapeHtml(alt.url)}" target="_blank" rel="noopener">${escapeHtml(alt.url)}</a><p>${escapeHtml(alt.reason || 'Sitio relacionado detectado')}</p></div>
    <div class="alternative-actions"><button class="analyze-alternative primary">Analizar</button><button class="use-alternative">Usar como sitio principal</button><button class="open-alternative">Abrir</button></div>
  </article>`).join('');
}

function openSiteDiagnostic(data={}, requestedUrl="") {
  const details=data.errorDetails || {};
  const dialog=$("siteDiagnosticDialog");
  if (!dialog) return;
  $("diagnosticTitle").textContent=siteErrorText(details);
  $("diagnosticMessage").textContent=details.message || data.error || "No fue posible completar el análisis.";
  $("diagnosticAction").textContent=details.action || "Revise la dirección y vuelva a intentar.";
  const technical=details.technical || {};
  $("diagnosticCode").textContent=details.code || details.category || "ANALYZER_ERROR";
  $("diagnosticRequestedUrl").textContent=technical.requestedUrl || requestedUrl || "—";
  $("diagnosticStage").textContent=technical.stage || "Análisis del sitio";
  $("diagnosticHttp").textContent=technical.httpStatus ? `HTTP ${technical.httpStatus}` : "No disponible";
  $("diagnosticTime").textContent=new Date().toLocaleString("es-PY");
  $("diagnosticAlternatives").innerHTML=renderAlternativeSites(data.alternatives || details.alternatives || []);
  dialog.showModal();
}

function openAlternativeSites(alternatives=[], requestedUrl="") {
  openSiteDiagnostic({errorDetails:{title:"Sitios relacionados detectados",message:"El radar encontró otras direcciones que pueden pertenecer a la misma presencia digital de la empresa.",action:"Revise la confianza de cada opción. Puede analizarla directamente o abrirla en una nueva pestaña.",code:"RELATED_SITES",technical:{requestedUrl,stage:"identificación de presencia digital"}}, alternatives}, requestedUrl);
}

function maybeShowAlternatives(analysis, requestedUrl="") {
  if (Array.isArray(analysis?.alternativeSites) && analysis.alternativeSites.length) {
    openAlternativeSites(analysis.alternativeSites, requestedUrl || analysis.url);
  }
}

function setScanProgress(stage, progress, message, active = true) {
  const status = $("scanStatus"), bar = $("scanProgressBar"), label = $("scanStage"), msg = $("siteAnalysisMessage");
  if (status) status.classList.toggle("is-scanning", active);
  if (bar) bar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  if (label) label.textContent = stage;
  if (msg) msg.textContent = message;
}

async function deepenWebsiteAnalysis(analysisId, card = null, silent = false) {
  if (!analysisId) return;
  if (card) card.classList.add("is-upgrading");
  if (!silent) setScanProgress("Análisis profundo", 62, "Revisando proyectos, noticias, infraestructura, responsables y señales comerciales…", true);
  try {
    const response = await fetch(`/api/website-analysis/${analysisId}/deep`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) { openSiteDiagnostic(data, card?.querySelector('a')?.href || ''); throw new Error(data.error || "No se pudo completar el análisis profundo"); }
    const current = card || document.querySelector(`.analysis-card[data-analysis-id="${analysisId}"]`);
    if (current) current.outerHTML = renderWebsiteAnalysis(data);
    if (Array.isArray(data.alternativeSites) && data.alternativeSites.length) maybeShowAlternatives(data, data.url);
    if (!silent) setScanProgress("Completado", 100, `Análisis profundo completado: ${data.pagesAnalyzed || 0} páginas relevantes · potencial ${data.level}.`, false);
    return data;
  } catch (error) {
    if (card) card.classList.remove("is-upgrading");
    if (!silent) setScanProgress("Análisis rápido disponible", 100, error.message, false);
    return null;
  }
}

$("siteAnalysisForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  const url = $("companyWebsite").value.trim();
  const started = performance.now();
  button.disabled = true;
  button.querySelector("span") && (button.querySelector("span").textContent = "Escaneando…");
  setScanProgress("Análisis rápido", 18, "Leyendo página principal y rutas esenciales para devolver una ficha inicial…", true);
  const skeleton = document.createElement("div");
  skeleton.className = "analysis-skeleton";
  skeleton.innerHTML = '<i></i><div><b></b><span></span><span></span><span></span></div>';
  $("siteAnalysisResults").prepend(skeleton);
  try {
    const response = await fetch("/api/website-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, mode: "quick" }),
    });
    const data = await response.json();
    if (!response.ok) { openSiteDiagnostic(data, url); throw new Error(data.error || "No se pudo analizar el sitio"); }
    skeleton.remove();
    $("siteAnalysisResults").insertAdjacentHTML("afterbegin", renderWebsiteAnalysis(data));
    if (Array.isArray(data.alternativeSites) && data.alternativeSites.length) maybeShowAlternatives(data, url);
    const seconds = ((performance.now() - started) / 1000).toFixed(1);
    if (data.cached || data.scanMode === "deep") {
      setScanProgress("Cache reciente", 100, `Resultado reutilizado en ${seconds}s. No fue necesario descargar el sitio nuevamente.`, false);
    } else {
      setScanProgress("Ficha inicial lista", 48, `Análisis rápido listo en ${seconds}s. Puede seguir trabajando mientras completamos el análisis profundo.`, true);
      const card = document.querySelector(`.analysis-card[data-analysis-id="${data.id}"]`);
      deepenWebsiteAnalysis(data.id, card, false);
    }
    toast(data.cached ? "Análisis reciente recuperado del cache" : "Ficha inicial disponible");
  } catch (error) {
    skeleton.remove();
    setScanProgress("Error", 100, error.message, false);
  } finally {
    button.disabled = false;
    button.querySelector("span") && (button.querySelector("span").textContent = "Analizar empresa");
  }
});

$("siteAnalysisResults").addEventListener("click", async (event) => {
  const card = event.target.closest(".analysis-card");
  if (!card) return;
  if (event.target.closest(".show-site-alternatives")) {
    const id=card.dataset.analysisId;
    const response=await fetch(`/api/website-analysis`); const rows=await response.json();
    const item=Array.isArray(rows)?rows.find(x=>String(x.id)===String(id)):null;
    openAlternativeSites(item?.alternativeSites||[], item?.url||"");
    return;
  }
  const deepButton = event.target.closest(".deep-analysis");
  if (deepButton) {
    deepButton.disabled = true;
    await deepenWebsiteAnalysis(card.dataset.analysisId, card, false);
    return;
  }
  if (event.target.matches(".copy-draft")) {
    const text = event.target.parentElement.querySelector("textarea").value;
    await navigator.clipboard.writeText(text);
    toast("Mensaje copiado");
    return;
  }
  const qualify = event.target.matches(".qualify-analysis");
  const disqualify = event.target.matches(".disqualify-analysis");
  if (!qualify && !disqualify) return;
  event.target.disabled = true;
  event.target.textContent = qualify ? "Ingresando al CRM..." : "Desclasificando...";
  try {
    const action = qualify ? "qualify" : "disqualify";
    const response = await fetch(`/api/website-analysis/${card.dataset.analysisId}/${action}`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No se pudo guardar la decisión");
    const analysis = data.analysis || data;
    card.outerHTML = renderWebsiteAnalysis(analysis);
    if (qualify && data.opportunity) {
      const existing = leads.findIndex((lead) => String(lead.id) === String(data.opportunity.id));
      if (existing >= 0) leads[existing] = data.opportunity; else leads.unshift(data.opportunity);
      selected = data.opportunity;
      render();
      window.setTimeout(() => {
        if (typeof window.openCompanyDossier === "function") {
          window.openCompanyDossier(data.opportunity, "messages");
        } else {
          $("crm").scrollIntoView({ behavior: "smooth" });
        }
      }, 120);
    }
    toast(qualify ? "Empresa ingresada al CRM y mensajes generados" : "Empresa desclasificada");
  } catch (error) {
    event.target.disabled = false;
    event.target.textContent = qualify ? "Clasificar e ingresar al CRM" : "Desclasificar";
    toast(error.message);
  }
});

async function loadToday() {
  try {
    await fetch("/api/tasks/ensure", { method: "POST" });
    const [todayResponse, metricsResponse, intelligenceResponse] = await Promise.all([fetch("/api/dashboard/today"), fetch("/api/metrics"), fetch("/api/dashboard/revenue-intelligence")]);
    const today = await todayResponse.json();
    const metrics = await metricsResponse.json();
    const intelligence = await intelligenceResponse.json();
    const metricValues = [today.dueToday, today.overdue, money(metrics.pipelineValue), `${metrics.responseRate}%`, metrics.won];
    document.querySelectorAll("#salesMetrics article b").forEach((element, index) => { element.textContent = metricValues[index]; });
    const intelligenceValues = [intelligence.companies, intelligence.projects, intelligence.signals, intelligence.evidence, intelligence.sources, money(intelligence.expectedRevenue)];
    document.querySelectorAll("#intelligenceMetrics article b").forEach((element, index) => { element.textContent = intelligenceValues[index]; });
    $("dailyFocus").textContent = today.overdue ? `${today.overdue} tareas atrasadas requieren atención inmediata.` : "No hay atrasos. Avance con los contactos previstos para hoy.";
    $("todayTasks").innerHTML = (today.tasks || []).map((task) => {
      const due = new Date(task.dueAt);
      const overdue = due < new Date();
      const icon = { WHATSAPP: "whatsapp", CALL: "telephone", EMAIL: "envelope", VISIT: "geo-alt", FOLLOW_UP: "arrow-repeat" }[task.channel] || "check2-square";
      return `<article class="task-item ${overdue ? "overdue" : ""}" data-task-id="${task.id}" data-opportunity-id="${task.opportunityId}"><i class="bi bi-${icon}"></i><div><strong>${escapeHtml(task.title)}</strong><span>${escapeHtml(task.company)} · ${escapeHtml(task.owner)} · ${due.toLocaleDateString("es-PY")}</span></div><div class="task-buttons"><button class="open-task"><i class="bi bi-box-arrow-up-right"></i> Abrir</button><button class="complete-task"><i class="bi bi-check-lg"></i> Hecho</button></div></article>`;
    }).join("") || '<div class="empty-signals"><strong>Agenda al día.</strong><span>No hay tareas vencidas ni programadas para hoy.</span></div>';
  } catch (_error) {
    $("todayTasks").innerHTML = "<p>No se pudo cargar la agenda comercial.</p>";
  }
}

$("refreshToday").addEventListener("click", loadToday);
$("todayTasks").addEventListener("click", async (event) => {
  const openButton = event.target.closest(".open-task");
  if (openButton) {
    const row = openButton.closest(".task-item");
    const lead = leads.find((item) => String(item.id) === row.dataset.opportunityId);
    if (lead) { selectLead(lead); toast("Ficha abierta en el panel derecho"); }
    return;
  }
  const button = event.target.closest(".complete-task");
  if (!button) return;
  const task = button.closest(".task-item");
  const response = await fetch(`/api/tasks/${task.dataset.taskId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: "DONE" }) });
  if (!response.ok) return toast("No se pudo completar la tarea");
  task.remove(); toast("Tarea completada"); loadToday();
});

const visitDialog = $("visitDialog");
const proposalDialog = $("proposalDialog");
$("registerVisit").addEventListener("click", () => {
  if (!selected || selected.demo) return toast("Seleccione una oportunidad real");
  $("visitOpportunityId").value = selected.id; $("visitCompany").textContent = selected.company; visitDialog.showModal();
});
$("createProposal").addEventListener("click", () => {
  if (!selected || selected.demo) return toast("Seleccione una oportunidad real");
  $("proposalCompany").textContent = selected.company;
  $("proposalForm").elements.amount.value = Number(selected.estimatedValue) || 0;
  $("proposalForm").elements.scope.value = `Suministro e instalación de ${(selected.products || []).join(", ") || "soluciones de accesos industriales"}. Incluye relevamiento técnico, puesta en marcha y orientación operativa.`;
  proposalDialog.showModal();
});
document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => $(button.dataset.closeDialog).close()));

$("visitForm").addEventListener("submit", async (event) => {
  event.preventDefault(); $("visitMessage").textContent = "Guardando visita y fotografías...";
  const response = await fetch("/api/visits", { method: "POST", body: new FormData(event.target) });
  const data = await response.json();
  if (!response.ok) return $("visitMessage").textContent = data.error || "No se pudo guardar la visita";
  selected.status = "VISITA"; selected.probability = Math.max(Number(selected.probability) || 0, 50); render();
  event.target.reset(); visitDialog.close(); toast("Visita registrada en la cronología"); loadToday();
});

$("proposalForm").addEventListener("submit", async (event) => {
  event.preventDefault(); $("proposalMessage").textContent = "Generando propuesta PDF...";
  const payload = Object.fromEntries(new FormData(event.target));
  const response = await fetch(`/api/proposals/${selected.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) return $("proposalMessage").textContent = data.error || "No se pudo generar la propuesta";
  selected.status = "ORCAMENTO"; selected.estimatedValue = Number(payload.amount); selected.probability = Math.max(Number(selected.probability) || 0, 60); render();
  const download = document.createElement("a"); download.href = data.downloadUrl; download.download = ""; document.body.appendChild(download); download.click(); download.remove();
  proposalDialog.close(); toast(`Propuesta ${data.number} generada`); loadToday();
});

async function loadCommandCenter() {
  try {
    const response = await fetch("/api/radar/command-center");
    if (!response.ok) throw new Error("command center");
    const data = await response.json();
    const values = [data.summary.hot, data.summary.buyingWindow, data.summary.accelerating, money(data.summary.pipelinePotential)];
    document.querySelectorAll("#commandMetrics article b").forEach((el, index) => { el.textContent = values[index]; });
    const opportunityCard = (lead) => `<article class="radar-row" data-opportunity-id="${lead.id}"><div><strong>${escapeHtml(lead.company)}</strong><span>${escapeHtml(lead.project)} · ${escapeHtml(lead.department || "")}</span></div><div class="radar-badges"><b>${Number(lead.score) || 0}</b><em>BW ${Number(lead.buyingWindow) || 0}</em><em>↑ ${Number(lead.momentum) || 0}</em></div><p>${escapeHtml(lead.whyNow || "Señal comercial prioritaria")}</p><small>${escapeHtml(lead.nextBestAction || "Validar responsables y cronograma")}</small></article>`;
    $("hotNowList").innerHTML = (data.hotNow || []).map(opportunityCard).join("") || '<p>No hay oportunidades HOT en este momento.</p>';
    $("momentumList").innerHTML = (data.momentum || []).map(opportunityCard).join("") || '<p>No hay cuentas acelerando.</p>';
    $("researchQueue").innerHTML = (data.researchQueue || []).map((row) => `<article class="radar-row"><div><strong>${escapeHtml(row.company)}</strong><span>Afinidad ${row.fit} · Acceso ${row.accessibility}</span></div><p>Falta: ${escapeHtml((row.missing || []).join(", ") || "enriquecimiento general")}</p></article>`).join("") || '<p>No hay cuentas pendientes de enriquecimiento.</p>';
  } catch (_error) {
    $("hotNowList").innerHTML = '<p>No se pudo cargar el Centro de inteligencia.</p>';
  }
}

$("refreshCommandCenter").addEventListener("click", loadCommandCenter);
["hotNowList", "momentumList"].forEach((id) => $(id).addEventListener("click", (event) => {
  const row = event.target.closest("[data-opportunity-id]");
  if (!row) return;
  const lead = leads.find((item) => String(item.id) === row.dataset.opportunityId);
  if (lead) { selectLead(lead); $("drawer").scrollIntoView({ behavior: "smooth", block: "start" }); }
}));

render();
if (selected) selectLead(selected);
loadToday();
loadCommandCenter();


$("closeSiteDiagnostic")?.addEventListener("click",()=>$("siteDiagnosticDialog").close());
$("siteDiagnosticDialog")?.addEventListener("click",event=>{
  const analyze=event.target.closest(".analyze-alternative");
  const open=event.target.closest(".open-alternative");
  const use=event.target.closest(".use-alternative");
  const row=event.target.closest(".alternative-site-row");
  if (!row) return;
  const url=row.dataset.altUrl;
  if (open) window.open(url,"_blank","noopener");
  if (use) { $("companyWebsite").value=url; $("siteDiagnosticDialog").close(); setScanProgress("Sitio principal actualizado",0,"La dirección alternativa quedó seleccionada. Presione Analizar empresa para continuar.",false); }
  if (analyze) { $("companyWebsite").value=url; $("siteDiagnosticDialog").close(); $("siteAnalysisForm").requestSubmit(); }
});
