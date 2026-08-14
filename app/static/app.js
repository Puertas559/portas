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
  `).join("") || "<p>Nenhuma oportunidade encontrada.</p>";

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

render();
if (selected) selectLead(selected);
