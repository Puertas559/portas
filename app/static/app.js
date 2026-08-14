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

function tag(priority, score) {
  const safePriority = escapeHtml(priority || "MEDIUM");
  return `<span class="level ${safePriority.toLowerCase()}">${safePriority} · ${Number(score) || 0}</span>`;
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
  $("companyName").textContent = lead.company || "Empresa não informada";
  $("companyMeta").textContent = `${lead.sector || "Setor não informado"} · ${lead.origin || "Paraguai"}`;
  $("companyPlace").textContent = `⌖ ${lead.city || "Cidade não informada"}, ${lead.department || ""}`;
  $("drawerLevel").className = `level ${(lead.level || "MEDIUM").toLowerCase()}`;
  $("drawerLevel").textContent = `${lead.level || "MEDIUM"} · ${Number(lead.score) || 0}`;
  $("whyText").textContent = `${lead.project || "O projeto"} pode gerar demanda por acessos industriais em áreas de operação, carga e circulação de veículos.`;
  $("eventType").textContent = lead.event || "Não informado";
  $("stage").textContent = lead.stage || "A validar";
  $("investment").textContent = lead.investment || "Não divulgado";
  $("productList").innerHTML = (lead.products || []).map((product) => `<span>${escapeHtml(product)}</span>`).join("");
  $("evidenceText").textContent = lead.evidence || "Sem evidência cadastrada.";
  $("status").value = lead.status || "NOVO";
  $("approach").value = `Olá! Identificamos que a ${lead.company} está desenvolvendo ${String(lead.project || "um novo projeto").toLowerCase()} em ${lead.city}. A Puertas Brasil PY atua com soluções para acessos industriais e gostaríamos de entender se essa etapa já possui fornecedor definido.`;
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
    $("timelineList").innerHTML = "<article><i></i><small>DESCOBERTA</small><strong>Evento demonstrativo identificado pelo radar</strong></article>";
    return;
  }
  try {
    const response = await fetch(`/api/timeline/${selected.id}`);
    if (!response.ok) throw new Error("Falha ao carregar timeline");
    const rows = await response.json();
    $("timelineList").innerHTML = rows.map((event) => `<article><i></i><small>${escapeHtml(event.type)}</small><strong>${escapeHtml(event.description)}</strong></article>`).join("") || "<p>Nenhum evento registrado.</p>";
  } catch (_error) {
    toast("Não foi possível carregar a timeline");
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
    toast("DEMO DATA: cadastre uma oportunidade para salvar no CRM");
    event.target.value = selected.status || "NOVO";
    return;
  }
  try {
    const response = await fetch(`/api/opportunities/${selected.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: event.target.value }),
    });
    if (!response.ok) throw new Error("Falha ao salvar status");
    selected.status = event.target.value;
    toast("Status salvo no PostgreSQL");
  } catch (_error) {
    event.target.value = selected.status || "NOVO";
    toast("Não foi possível salvar o status");
  }
});

$("copyApproach").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("approach").value);
    toast("Abordagem copiada");
  } catch (_error) {
    $("approach").select();
    document.execCommand("copy");
    toast("Abordagem copiada");
  }
});

document.querySelectorAll(".channels button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".channels button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    toast(`Canal selecionado: ${button.textContent}`);
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
  $("formMessage").textContent = "Salvando...";
  try {
    const response = await fetch("/api/opportunities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error("Falha ao cadastrar oportunidade");
    $("formMessage").textContent = "Oportunidade salva. Atualizando...";
    window.setTimeout(() => window.location.reload(), 500);
  } catch (_error) {
    $("formMessage").textContent = "Verifique os campos e a conexão com o banco.";
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
      toast(target === "#empresas" ? "Empresas estão organizadas nas oportunidades" : "Projetos estão organizados nas oportunidades");
    } else if (target === "#crm") {
      event.preventDefault();
      activateTab("overview");
      $("status").focus();
      toast("CRM aberto no painel lateral");
    } else if (target === "#timeline") {
      event.preventDefault();
      await loadTimeline();
    } else if (target === "#pesquisas") {
      event.preventDefault();
      $("search").focus();
      toast("Use a busca para pesquisar empresa, cidade ou projeto");
    }
  });
});

$("drawerMenu").addEventListener("click", () => toast("Selecione uma oportunidade para ver as ações"));

render();
if (selected) selectLead(selected);
