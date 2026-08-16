(() => {
  const byId = (id) => document.getElementById(id);
  const section = byId("mapa-prospeccion");
  if (!section) return;

  const state = { rows: [], selected: new Set(), map: null, markers: new Map(), config: null };
  const esc = (v) => String(v ?? "").replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

  function toastMap(message) {
    if (typeof window.toast === "function") return window.toast(message);
    const el = document.createElement("div");
    el.className = "toast"; el.textContent = message; document.body.appendChild(el);
    setTimeout(() => el.remove(), 2600);
  }

  function updateStats() {
    const values = [
      state.rows.length,
      state.rows.filter((r) => !r.inCrm).length,
      state.rows.filter((r) => r.inCrm).length,
      state.rows.filter((r) => r.website).length,
      state.rows.filter((r) => r.phone || r.email || r.website).length,
      state.selected.size,
    ];
    document.querySelectorAll("#mapDiscoveryStats article b").forEach((el, i) => { el.textContent = values[i] ?? 0; });
  }

  function selectedRows() { return state.rows.filter((row) => state.selected.has(row.placeId) && !row.inCrm); }

  function renderRows() {
    const box = byId("mapPlaceResults");
    if (!state.rows.length) { box.innerHTML = ""; updateStats(); return; }
    box.innerHTML = state.rows.map((row) => {
      const checked = state.selected.has(row.placeId);
      const rating = row.rating ? `★ ${Number(row.rating).toFixed(1)} (${row.reviews || 0})` : "Sin valoración";
      return `<article class="map-place-card ${checked ? "selected" : ""} ${row.inCrm ? "in-crm" : ""}" data-place-id="${esc(row.placeId)}">
        <input class="map-place-check" type="checkbox" ${checked ? "checked" : ""} ${row.inCrm ? "disabled" : ""} aria-label="Seleccionar ${esc(row.company)}">
        <div><h3>${esc(row.company)}</h3><p>${esc(row.address || "Dirección no informada")}</p>
        <div class="map-place-meta"><span>${esc(row.primaryType || "Empresa")}</span><span>${esc(rating)}</span><span class="term-badge">${esc(row.matchedTerm || "búsqueda")}</span><span class="source-badge">${esc(row.source || "Fuente pública")}</span>${row.commercialScore ? `<span class="score-badge">FIT ${esc(row.commercialScore)}</span>` : ""}${row.inCrm ? '<span class="crm-badge">YA EN CRM</span>' : ""}</div>
        <div class="map-place-actions">${row.website ? `<a href="${esc(row.website)}" target="_blank" rel="noopener">Sitio</a>` : ""}${row.mapsUrl ? `<a href="${esc(row.mapsUrl)}" target="_blank" rel="noopener">Maps</a>` : ""}${row.phone ? `<button type="button" data-copy-phone="${esc(row.phone)}">${esc(row.phone)}</button>` : ""}${row.email ? `<button type="button" data-copy-email="${esc(row.email)}">${esc(row.email)}</button>` : ""}</div></div>
      </article>`;
    }).join("");
    updateStats(); updateMarkers();
  }

  function markerContent(row, index) {
    const div = document.createElement("div");
    div.className = `map-marker ${row.inCrm ? "crm" : ""} ${state.selected.has(row.placeId) ? "selected" : ""}`;
    div.innerHTML = `<span>${index + 1}</span>`;
    return div;
  }

  async function ensureMap() {
    if (state.map) return true;
    if (!state.config) {
      const response = await fetch("/api/prospecting-map/config");
      state.config = await response.json();
    }
    if (!state.config.browserKey) {
      byId("googleProspectingMap").innerHTML = '<div class="map-empty"><i class="bi bi-key"></i><strong>Falta la clave del mapa</strong><span>Configure GOOGLE_MAPS_BROWSER_KEY en Railway. La lista de empresas puede seguir funcionando con GOOGLE_PLACES_API_KEY.</span></div>';
      return false;
    }
    if (!window.google?.maps) {
      await new Promise((resolve, reject) => {
        window.__initPuertasProspectingMap = resolve;
        const script = document.createElement("script");
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(state.config.browserKey)}&v=weekly&libraries=marker&callback=__initPuertasProspectingMap`;
        script.async = true; script.onerror = reject; document.head.appendChild(script);
      });
    }
    const { Map } = await google.maps.importLibrary("maps");
    state.map = new Map(byId("googleProspectingMap"), { center: { lat: -25.516, lng: -54.617 }, zoom: 10, mapId: "DEMO_MAP_ID", streetViewControl: false, mapTypeControl: false, fullscreenControl: true });
    return true;
  }

  async function updateMarkers() {
    if (!(await ensureMap())) return;
    const { AdvancedMarkerElement } = await google.maps.importLibrary("marker");
    state.markers.forEach((marker) => { marker.map = null; }); state.markers.clear();
    const bounds = new google.maps.LatLngBounds();
    state.rows.forEach((row, index) => {
      if (row.lat == null || row.lng == null) return;
      const position = { lat: Number(row.lat), lng: Number(row.lng) };
      const marker = new AdvancedMarkerElement({ map: state.map, position, title: row.company, content: markerContent(row, index) });
      marker.addListener("click", () => {
        const card = document.querySelector(`.map-place-card[data-place-id="${CSS.escape(row.placeId)}"]`);
        if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); card.animate([{transform:"scale(1)"},{transform:"scale(1.015)"},{transform:"scale(1)"}], {duration:360}); }
      });
      state.markers.set(row.placeId, marker); bounds.extend(position);
    });
    if (!bounds.isEmpty()) state.map.fitBounds(bounds, 56);
  }

  async function runSearch() {
    const button = byId("runMapSearch");
    const params = new URLSearchParams({
      q: byId("mapSearchQuery").value.trim(), city: byId("mapSearchCity").value.trim(),
      region: byId("mapSearchRegion").value, industry: byId("mapSearchIndustry").value,
      depth: byId("mapSearchDepth").value,
    });
    button.disabled = true; button.innerHTML = '<i class="bi bi-hourglass-split"></i> Buscando...';
    byId("mapSearchStatus").textContent = "Consultando múltiples categorías y eliminando duplicados...";
    try {
      const response = await fetch(`/api/prospecting-map/search?${params.toString()}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "No se pudo completar el barrido territorial");
      state.rows = data.results || []; state.selected.clear();
      const newCount = state.rows.filter((r) => !r.inCrm).length;
      const providers = (data.providers || []).join(" + ") || "fuentes públicas";
      const placesText = data.locations?.length ? ` · ${data.locations.length} polos territoriales` : "";
      const googleText = data.googleEnabled ? ` · ${data.calls} consultas Google` : " · Google Places pendiente de clave";
      byId("mapSearchStatus").textContent = `${data.count} empresas únicas · ${newCount} nuevas · ${data.queries.length} familias de búsqueda${placesText}${googleText} · ${providers}.`;
      renderRows();
      if (data.errors?.length) toastMap(`Búsqueda completada con ${data.errors.length} aviso(s)`);
    } catch (error) {
      byId("mapSearchStatus").textContent = error.message;
      toastMap(error.message);
    } finally {
      button.disabled = false; button.innerHTML = '<i class="bi bi-radar"></i> Barrer territorio';
    }
  }

  async function importSelected() {
    const rows = selectedRows();
    if (!rows.length) return toastMap("Seleccione empresas nuevas para agregar al CRM");
    const button = byId("importMapSelection"); button.disabled = true;
    try {
      const response = await fetch("/api/prospecting-map/import", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ places: rows, city: byId("mapSearchCity").value.trim(), region: byId("mapSearchRegion").value, industry: byId("mapSearchIndustry").value }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "No se pudo importar al CRM");
      const importedIds = new Set((data.created || []).map((x) => x.company));
      state.rows.forEach((row) => { if (state.selected.has(row.placeId)) row.inCrm = true; });
      state.selected.clear(); renderRows();
      toastMap(`${data.imported || 0} empresas agregadas al CRM${data.skipped ? ` · ${data.skipped} ya existentes` : ""}`);
      setTimeout(() => window.location.reload(), 1200);
    } catch (error) { toastMap(error.message); }
    finally { button.disabled = false; }
  }

  byId("runMapSearch").addEventListener("click", runSearch);
  ["mapSearchQuery", "mapSearchCity"].forEach((id) => byId(id).addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); runSearch(); } }));
  byId("importMapSelection").addEventListener("click", importSelected);
  byId("selectAllMapResults").addEventListener("change", (event) => {
    state.selected.clear(); if (event.target.checked) state.rows.filter((r) => !r.inCrm).forEach((r) => state.selected.add(r.placeId)); renderRows();
  });
  byId("mapPlaceResults").addEventListener("click", async (event) => {
    const copy = event.target.closest("[data-copy-phone]");
    if (copy) { event.stopPropagation(); await navigator.clipboard.writeText(copy.dataset.copyPhone); return toastMap("Teléfono copiado"); }
    const copyEmail = event.target.closest("[data-copy-email]");
    if (copyEmail) { event.stopPropagation(); await navigator.clipboard.writeText(copyEmail.dataset.copyEmail); return toastMap("E-mail copiado"); }
    const card = event.target.closest(".map-place-card"); if (!card) return;
    const row = state.rows.find((r) => r.placeId === card.dataset.placeId); if (!row || row.inCrm) return;
    if (state.selected.has(row.placeId)) state.selected.delete(row.placeId); else state.selected.add(row.placeId);
    renderRows();
  });

  fetch("/api/prospecting-map/config").then((r) => r.json()).then((config) => { state.config = config; if (config.browserKey) ensureMap(); }).catch(() => {});
})();
