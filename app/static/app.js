const leads = Array.isArray(window.RADAR_LEADS) ? window.RADAR_LEADS : [];
let selected = leads[0] || null;
let level = "ALL";
let selectedChannel = "whatsapp";
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
  if (channel === "email") return `Asunto: Soluciones de accesos industriales para ${lead.company}\n\nEstimado equipo de ${lead.company}:\n\nIdentificamos una posible aplicación de ${products} para su operación en ${lead.city}. Puertas Brasil PY puede realizar una evaluación técnica y proponer una solución a medida.\n\n¿Podemos coordinar una breve conversación con la persona responsable de mantenimiento, operaciones o compras?\n\nAtentamente,\nEquipo comercial de Puertas Brasil PY`;
  if (channel === "call") return `GUION DE LLAMADA\n\nPresentarse como Puertas Brasil PY. Confirmar la actividad de ${lead.company} y preguntar por el responsable de mantenimiento, operaciones o compras. Validar necesidades de ${products}, próximos proyectos y disponibilidad para una visita técnica.`;
  if (channel === "linkedin") return `Hola. Soy parte del equipo comercial de Puertas Brasil PY. Conocimos la operación de ${lead.company} y nos gustaría conectar con la persona responsable de mantenimiento, operaciones o compras para presentar soluciones de accesos industriales.`;
  return `¡Hola! Soy parte del equipo comercial de Puertas Brasil PY. Identificamos que ${lead.company} opera en ${lead.city} y puede tener aplicación para ${products}. ¿Con quién podríamos coordinar una breve conversación técnica?`;
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
      <div class="crm-card-actions"><button class="open-crm-detail"><i class="bi bi-eye"></i> Ver ficha</button><label><input class="visit-check" type="checkbox" ${visitSelection.has(String(lead.id)) ? "checked" : ""}> Incluir en visita</label></div>
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
  $("whyText").textContent = `${lead.project || "El proyecto"} puede generar demanda de accesos industriales en áreas de operación, carga y circulación de vehículos.`;
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
  $("approach").value = contactMessage(lead);
  updateChannelAction();
  render();
}

function updateChannelAction() {
  if (!selected) return;
  const labels = { whatsapp: "Abrir WhatsApp", email: "Redactar correo", call: "Iniciar llamada", linkedin: "Abrir LinkedIn" };
  $("openChannel").innerHTML = `<i class="bi bi-box-arrow-up-right"></i> ${labels[selectedChannel]}`;
  $("approach").value = contactMessage(selected, selectedChannel);
}

function activateTab(tabName) {
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  ["overview", "evidence", "timeline"].forEach((name) => {
    $(name + "Panel").classList.toggle("hidden", name !== tabName);
  });
}

async function loadTimeline() {
  activateTab("timeline");
  if (!selected) return;
  if (selected.demo) {
    $("timelineList").innerHTML = "<article><i></i><small>DESCUBRIMIENTO</small><strong>Evento demostrativo identificado por el radar</strong></article>";
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
    $("drawer").scrollIntoView({ behavior: "smooth", block: "start" });
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
    toast("DATOS DEMO: registre una oportunidad para guardarla en el CRM");
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
  if (!lead || lead.demo) return toast("Los datos demostrativos no se pueden mover");
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
  button.addEventListener("click", () => {
    document.querySelectorAll(".channels button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    selectedChannel = button.dataset.channel;
    updateChannelAction();
    toast(`Canal seleccionado: ${button.textContent.trim()}`);
  });
});

$("openChannel").addEventListener("click", () => {
  if (!selected) return;
  const message = contactMessage(selected, selectedChannel);
  let url;
  if (selectedChannel === "whatsapp") {
    const number = String(selected.whatsapp || selected.phone || "").replace(/\D/g, "");
    if (!number) return toast("Esta empresa todavía no tiene WhatsApp registrado");
    url = `https://wa.me/${number}?text=${encodeURIComponent(message)}`;
  } else if (selectedChannel === "email") {
    if (!selected.email) return toast("Esta empresa todavía no tiene correo registrado");
    const subject = `Soluciones de accesos industriales para ${selected.company}`;
    url = `mailto:${selected.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(message.replace(/^Asunto:.*\n\n/, ""))}`;
  } else if (selectedChannel === "call") {
    if (!selected.phone) return toast("Esta empresa todavía no tiene teléfono registrado");
    url = `tel:${selected.phone}`;
  } else {
    url = selected.linkedin || `https://www.linkedin.com/search/results/companies/?keywords=${encodeURIComponent(selected.company)}`;
  }
  window.open(url, "_blank", "noopener");
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
  const decisionActions = decision === "PENDING"
    ? '<button class="qualify-analysis">Clasificar e ingresar al CRM</button><button class="disqualify-analysis">Desclasificar</button>'
    : `<strong>${decision === "QUALIFIED" ? "✓ Empresa ingresada al CRM" : "Empresa desclasificada"}</strong>`;
  const drafts = decision === "QUALIFIED" ? `
    <div class="outreach-drafts">
      <div><b>Mensaje para WhatsApp</b><textarea readonly>${escapeHtml(analysis.whatsappMessage || "")}</textarea><button class="copy-draft">Copiar WhatsApp</button></div>
      <div><b>Correo personalizado · ${escapeHtml(analysis.emailSubject || "")}</b><textarea readonly>${escapeHtml(analysis.emailBody || "")}</textarea><button class="copy-draft">Copiar correo</button></div>
    </div>` : "";
  return `
    <article class="analysis-card" data-analysis-id="${escapeHtml(analysis.id)}" data-decision="${escapeHtml(decision)}">
      <div class="analysis-score"><strong>${Number(analysis.score) || 0}</strong><small>${escapeHtml(analysis.level)}</small></div>
      <div class="analysis-main"><span class="source-type">${Number(analysis.pagesAnalyzed) || 0} PÁGINAS ANALIZADAS · ${decisionLabel}</span><h3>${escapeHtml(analysis.company)}</h3><p><b>Sector:</b> ${escapeHtml(analysis.sector)} · <b>Tamaño:</b> ${escapeHtml(analysis.companySize)}</p><a href="${escapeHtml(analysis.url)}" target="_blank" rel="noopener">Abrir sitio ↗</a></div>
      <div class="analysis-grid">
        <div><b>Contacto</b><span>${list(analysis.emails)}</span><span>${list(analysis.phones)}</span>${analysis.whatsapp ? `<span>WhatsApp: ${escapeHtml(analysis.whatsapp)}</span>` : ""}</div>
        <div><b>Dirección y responsables</b><span>${escapeHtml(analysis.address || "No encontrado")}</span><span>${list(analysis.contacts, "No identificado")}</span></div>
        <div><b>Productos probables</b><span>${list(analysis.products, "Requiere validación")}</span></div>
        <div><b>Servicios recomendados</b><span>${list(analysis.services)}</span></div>
      </div>
      <div class="analysis-reasons"><b>Razones de la calificación</b><span>${list(analysis.reasons, "Sin evidencia suficiente")}</span></div>
      <div class="analysis-decision">${decisionActions}</div>
      ${drafts}
    </article>`;
}

$("siteAnalysisForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  const url = $("companyWebsite").value.trim();
  button.disabled = true;
  button.textContent = "Analizando páginas y contactos...";
  $("siteAnalysisMessage").textContent = "Revisando información pública, responsables, contactos, infraestructura y afinidad comercial.";
  try {
    const response = await fetch("/api/website-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No se pudo analizar el sitio");
    $("siteAnalysisResults").insertAdjacentHTML("afterbegin", renderWebsiteAnalysis(data));
    $("siteAnalysisMessage").textContent = `Análisis completado: potencial ${data.level} con ${data.score} puntos.`;
    toast("Empresa analizada y guardada en PostgreSQL");
  } catch (error) {
    $("siteAnalysisMessage").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "◉ Analizar empresa";
  }
});

$("siteAnalysisResults").addEventListener("click", async (event) => {
  const card = event.target.closest(".analysis-card");
  if (!card) return;
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
      window.setTimeout(() => $("crm").scrollIntoView({ behavior: "smooth" }), 250);
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
    const [todayResponse, metricsResponse] = await Promise.all([fetch("/api/dashboard/today"), fetch("/api/metrics")]);
    const today = await todayResponse.json();
    const metrics = await metricsResponse.json();
    const metricValues = [today.dueToday, today.overdue, money(metrics.pipelineValue), `${metrics.responseRate}%`, metrics.won];
    document.querySelectorAll("#salesMetrics article b").forEach((element, index) => { element.textContent = metricValues[index]; });
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

render();
if (selected) selectLead(selected);
loadToday();
