const leads = Array.isArray(window.RADAR_LEADS) ? window.RADAR_LEADS : [];
let selected = leads[0] || null;
let level = "ALL";

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
    const searchable = `${lead.company || ""} ${lead.city || ""} ${lead.project || ""}`.toLowerCase();
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
  $("approach").value = `¡Hola! Identificamos que ${lead.company} está desarrollando ${String(lead.project || "un nuevo proyecto").toLowerCase()} en ${lead.city}. Puertas Brasil PY ofrece soluciones para accesos industriales y nos gustaría saber si esta etapa ya cuenta con un proveedor definido.`;
  render();
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
    toast(`Canal seleccionado: ${button.textContent}`);
  });
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

document.querySelectorAll('.sidebar nav a[href^="#"]').forEach((link) => {
  link.addEventListener("click", async (event) => {
    const target = link.getAttribute("href");
    document.querySelectorAll(".sidebar nav a").forEach((item) => item.classList.remove("active"));
    link.classList.add("active");

    if (["#empresas", "#projetos"].includes(target)) {
      event.preventDefault();
      $("prioridades").scrollIntoView({ behavior: "smooth" });
      toast(target === "#empresas" ? "Las empresas están organizadas por oportunidades" : "Los proyectos están organizados por oportunidades");
    } else if (target === "#crm") {
      event.preventDefault();
      activateTab("overview");
      $("status").focus();
      toast("CRM abierto en el panel lateral");
    } else if (target === "#timeline") {
      event.preventDefault();
      await loadTimeline();
    } else if (target === "#pesquisas") {
      event.preventDefault();
      $("search").focus();
      toast("Use la búsqueda para encontrar una empresa, ciudad o proyecto");
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
    toast(qualify ? "Empresa ingresada al CRM y mensajes generados" : "Empresa desclasificada");
  } catch (error) {
    event.target.disabled = false;
    event.target.textContent = qualify ? "Clasificar e ingresar al CRM" : "Desclasificar";
    toast(error.message);
  }
});

render();
if (selected) selectLead(selected);
