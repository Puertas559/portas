import html
import json
import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ..extensions import db
from ..models import HubEvent, HubEventAccount, HubEventAction, HubEventSource
from .entity_resolution import normalize_name, normalize_domain

KEYWORDS = (
    "evento", "event", "feira", "feria", "expo", "congreso", "congress", "summit", "business",
    "rueda", "ronda", "misión", "mision", "encuentro", "forum", "fórum", "jornada", "conferencia",
    "conference", "seminario", "seminar", "workshop", "networking", "convención", "convencao",
)
EVENT_PATH_HINTS = ("evento", "event", "agenda", "noticia", "news", "actualidad", "actividades", "calendar", "blog", "prensa")
MONTHS = {
    "enero": 1, "janeiro": 1, "january": 1, "febrero": 2, "fevereiro": 2, "february": 2,
    "marzo": 3, "marco": 3, "march": 3, "abril": 4, "april": 4, "mayo": 5, "maio": 5, "may": 5,
    "junio": 6, "junho": 6, "june": 6, "julio": 7, "julho": 7, "july": 7, "agosto": 8, "august": 8,
    "septiembre": 9, "setiembre": 9, "setembro": 9, "september": 9, "octubre": 10, "outubro": 10, "october": 10,
    "noviembre": 11, "novembro": 11, "november": 11, "diciembre": 12, "dezembro": 12, "december": 12,
}
CITY_HINTS = [
    "Ciudad del Este", "Asunción", "Asuncion", "Hernandarias", "Presidente Franco", "Minga Guazú", "Minga Guazu",
    "Santa Rita", "Encarnación", "Encarnacion", "Caaguazú", "Caaguazu", "Luque", "San Lorenzo", "Limpio",
    "São Paulo", "Sao Paulo", "Foz do Iguaçu", "Foz do Iguacu", "Curitiba", "Cascavel", "Goiânia", "Goiania",
]
SECTOR_TERMS = {
    "Indústria": ("industria", "industrial", "manufactura", "manufacturing"),
    "Logística": ("logistica", "logistics", "centro de distrib", "supply chain", "almacen"),
    "Agro": ("agro", "agronegocio", "agriculture", "agricola", "ganader"),
    "Construção": ("construc", "arquitet", "arquitect", "ingenier", "engenhar"),
    "Alimentos": ("alimento", "food", "frigor", "carne", "lacte", "bebida"),
    "Investimentos": ("inversion", "investimento", "investment", "maquila", "implant", "expansion", "expansão"),
}

def _fold(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value).strip().casefold()


def event_key(name, start_date=None, city=None, organizer=None):
    return "|".join([normalize_name(name), str(start_date or ""), normalize_name(city), normalize_name(organizer)])[:500]


def fetch_html(url, timeout=15):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; HG-Radar-HUB/2.0; +event-intelligence)"})
    with urlopen(req, timeout=timeout) as response:
        ctype = response.headers.get("Content-Type", "")
        if "html" not in ctype.lower() and "xml" not in ctype.lower():
            raise ValueError("La fuente no devuelve HTML/XML")
        return response.read(2_000_000).decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def _clean_text(raw):
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _meta(raw, key):
    patterns = [
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']{re.escape(key)}["\']',
    ]
    for p in patterns:
        m = re.search(p, raw, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def _jsonld(raw):
    out = []
    for blob in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw, re.I | re.S):
        try:
            data = json.loads(html.unescape(blob).strip())
            if isinstance(data, list): out.extend(data)
            elif isinstance(data, dict):
                graph = data.get("@graph")
                if isinstance(graph, list): out.extend(graph)
                out.append(data)
        except Exception:
            continue
    return out


def _parse_iso_date(value):
    if not value: return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except Exception:
        try: return date.fromisoformat(str(value)[:10])
        except Exception: return None


def _parse_dates(text, year_hint=None):
    folded = _fold(text)
    year_hint = year_hint or datetime.now().year
    # 11 al 13 de Noviembre de 2026 / 11-13 novembro 2026
    month_alt = "|".join(re.escape(k) for k in MONTHS)
    m = re.search(rf'\b(\d{{1,2}})\s*(?:al|a|ate|até|[-–—])\s*(\d{{1,2}})\s*(?:de\s+)?({month_alt})(?:\s*(?:de\s+)?(20\d{{2}}))?', folded, re.I)
    if m:
        y = int(m.group(4) or year_hint); mo = MONTHS[m.group(3)]; d1, d2 = int(m.group(1)), int(m.group(2))
        try: return date(y, mo, d1), date(y, mo, d2)
        except ValueError: pass
    m = re.search(rf'\b(\d{{1,2}})\s*(?:de\s+)?({month_alt})(?:\s*(?:de\s+)?(20\d{{2}}))?', folded, re.I)
    if m:
        y = int(m.group(3) or year_hint); mo = MONTHS[m.group(2)]; d = int(m.group(1))
        try: return date(y, mo, d), None
        except ValueError: pass
    m = re.search(r'\b(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2})\b', folded)
    if m:
        try: return date(int(m.group(3)), int(m.group(2)), int(m.group(1))), None
        except ValueError: pass
    return None, None


def _extract_location(obj, text):
    city = country = None
    loc = obj.get("location") if isinstance(obj, dict) else None
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            city = addr.get("addressLocality") or addr.get("addressRegion")
            country = addr.get("addressCountry")
        elif isinstance(addr, str): city = addr
        city = city or loc.get("name")
    for hint in CITY_HINTS:
        if _fold(hint) in _fold(text):
            city = hint
            break
    if not country:
        ft = _fold(text)
        country = "Paraguay" if "paraguay" in ft else ("Brasil" if "brasil" in ft or "brazil" in ft else None)
    return city, country


def _org_name(value):
    if isinstance(value, dict): return value.get("name")
    if isinstance(value, str): return value
    if isinstance(value, list):
        names = [_org_name(x) for x in value]
        return ", ".join(x for x in names if x) or None
    return None


def _extract_accounts(jsonlds, raw, base_url):
    found = []
    def add(name, website=None, role="PARTICIPANT"):
        name = re.sub(r"\s+", " ", html.unescape(str(name or ""))).strip()
        if len(name) < 3 or len(name) > 220: return
        key = normalize_name(name)
        if not key or any(normalize_name(x["companyName"]) == key for x in found): return
        found.append({"companyName": name, "website": website, "role": role})
    for obj in jsonlds:
        if not isinstance(obj, dict): continue
        for field, role in (("sponsor", "SPONSOR"), ("funder", "SPONSOR"), ("performer", "SPEAKER"), ("contributor", "PARTICIPANT")):
            val = obj.get(field)
            vals = val if isinstance(val, list) else [val]
            for item in vals:
                if isinstance(item, dict): add(item.get("name"), item.get("url"), role)
    # Anchors explicitly labelled as exhibitors/sponsors/participants (conservative)
    for href, label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw, re.I | re.S):
        clean = re.sub(r"<[^>]+>", " ", html.unescape(label)); clean = re.sub(r"\s+", " ", clean).strip()
        hay = _fold(clean + " " + href)
        if 3 <= len(clean) <= 100 and any(k in hay for k in ("expositor", "exhibitor", "sponsor", "patrocin", "empresa participante")):
            add(clean, urljoin(base_url, href), "EXHIBITOR")
    return found[:80]


def extract_page(url):
    raw = fetch_html(url)
    text = _clean_text(raw)
    jsonlds = _jsonld(raw)
    event_objs = [o for o in jsonlds if isinstance(o, dict) and "event" in str(o.get("@type", "")).casefold()]
    obj = event_objs[0] if event_objs else {}

    title = obj.get("name") if isinstance(obj, dict) else None
    title = title or _meta(raw, "og:title") or _meta(raw, "twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        title = re.sub(r"<[^>]+>", " ", html.unescape(m.group(1))) if m else urlparse(url).netloc
    title = re.sub(r"\s+", " ", str(title)).strip()[:320]

    desc = (obj.get("description") if isinstance(obj, dict) else None) or _meta(raw, "description") or _meta(raw, "og:description") or text[:1200]
    desc = re.sub(r"\s+", " ", html.unescape(str(desc or ""))).strip()[:1800]
    combined = f"{title} {desc} {text[:12000]}"

    start = _parse_iso_date(obj.get("startDate")) if isinstance(obj, dict) else None
    end = _parse_iso_date(obj.get("endDate")) if isinstance(obj, dict) else None
    if not start:
        start, parsed_end = _parse_dates(combined)
        end = end or parsed_end
    city, country = _extract_location(obj, combined)
    organizer = _org_name(obj.get("organizer")) if isinstance(obj, dict) else None
    sectors = [name for name, terms in SECTOR_TERMS.items() if any(_fold(t) in _fold(combined) for t in terms)]
    event_type = "EVENT"
    ft = _fold(combined)
    if "expo" in ft or "feria" in ft or "feira" in ft: event_type = "EXPO"
    elif "mision" in ft or "missao" in ft: event_type = "MISSION"
    elif "rueda" in ft or "rodada" in ft: event_type = "MATCHMAKING"
    elif "congres" in ft or "summit" in ft or "conference" in ft: event_type = "CONGRESS"

    info = {"name": title, "url": url, "description": desc, "raw": raw, "text": text[:20000],
            "startDate": start, "endDate": end, "city": city, "country": country,
            "organizer": organizer, "eventType": event_type, "sectors": sectors,
            "accounts": _extract_accounts(jsonlds, raw, url)}
    return info


def _evidence(text, terms, label, limit=4):
    ft = _fold(text); hits = []
    for term in terms:
        if _fold(term) in ft: hits.append(term)
        if len(hits) >= limit: break
    return f"{label}: " + ", ".join(hits) if hits else None


def automatic_analysis(info, cost_estimate=0):
    text = f"{info.get('name','')} {info.get('description','')} {info.get('text','')} {' '.join(info.get('sectors') or [])}"
    ft = _fold(text)
    icp_terms = ("industr", "logistic", "agro", "frigor", "manufact", "construc", "ingenier", "engenhar", "maquila", "centro de distrib", "infrastructure")
    timing_terms = ("inversion", "investimento", "expansion", "expansao", "implant", "nueva planta", "nova fabrica", "proyecto", "projeto", "negocios", "business", "maquila")
    decision_terms = ("empresario", "director", "ceo", "gerente", "ejecutiv", "executiv", "autoridad", "compras", "ingenier", "matchmaking", "rueda de negocios", "rodada de negocios")
    pre_terms = ("inscripcion", "registro", "matchmaking", "agenda", "expositor", "participante", "reunion", "reunião", "rueda", "rodada")
    partner_terms = ("camara", "câmara", "federacion", "federação", "ministerio", "rediex", "mic", "uip", "asociacion", "associação", "organizador")
    visibility_terms = ("internacional", "nacional", "business week", "expo", "congreso", "summit", "visitantes", "stands", "estandes", "delegacion", "delegação")
    def score(terms, base=20, per=12, cap=100):
        return min(cap, base + sum(1 for t in terms if _fold(t) in ft) * per)
    icp = score(icp_terms, 20, 10)
    timing = score(timing_terms, 20, 11)
    decision = score(decision_terms, 15, 10)
    pre = score(pre_terms, 15, 10)
    partnership = score(partner_terms, 20, 12)
    visibility = score(visibility_terms, 20, 11)
    # Sem custo conhecido, nota neutra; com custo baixo, sobe, alto reduz.
    cost = float(cost_estimate or 0)
    economic = 65 if not cost else (90 if cost <= 300 else 80 if cost <= 1000 else 65 if cost <= 3000 else 45)
    evidence = {
        "icp": _evidence(text, icp_terms, "Sinais de aderência"),
        "timing": _evidence(text, timing_terms, "Sinais de momento de compra"),
        "decisionAccess": _evidence(text, decision_terms, "Sinais de decisores"),
        "preAccess": _evidence(text, pre_terms, "Sinais de acesso pré-evento"),
        "economicEfficiency": "Custo ainda não publicado; eficiência inicia neutra em 65/100." if not cost else f"Custo estimado informado: {cost:.2f}.",
        "partnership": _evidence(text, partner_terms, "Sinais de parceria institucional"),
        "visibility": _evidence(text, visibility_terms, "Sinais de visibilidade"),
    }
    values = {"icp": icp, "timing": timing, "decisionAccess": decision, "preAccess": pre,
              "economicEfficiency": economic, "partnership": partnership, "visibility": visibility}
    commercial = icp*.25 + timing*.20 + decision*.15 + pre*.10
    strategic = partnership*.5 + visibility*.5
    total = round(commercial + economic*.20 + strategic*.10)
    return values, evidence, round(commercial/.70), economic, round(strategic), total


def automatic_projection(info, analysis_values, cost_estimate=0, average_ticket=0):
    accounts_found = len(info.get("accounts") or [])
    # Se não há lista pública, cria hipótese conservadora baseada no score.
    relevant = accounts_found or max(4, round((analysis_values.get("icp", 50) / 100) * 12))
    meetings = max(1, round(relevant * (0.18 if analysis_values.get("preAccess", 0) >= 60 else 0.10)))
    visits = max(0, round(meetings * 0.30))
    opportunities = max(1 if meetings >= 3 else 0, round(meetings * 0.25))
    probability = 20
    ticket = float(average_ticket or 0)
    raw = opportunities * ticket
    weighted = raw * probability/100
    cost = float(cost_estimate or 0)
    return {"relevantAccounts": relevant, "meetings": meetings, "visits": visits, "opportunities": opportunities,
            "averageTicket": ticket, "probability": probability, "pipelinePotential": raw,
            "weightedPipeline": weighted, "pipelineCostMultiple": round(raw/cost, 1) if cost and raw else None,
            "automatic": True, "basis": "Projeção preliminar baseada em contas públicas detectadas e score do evento."}


def apply_automatic_intelligence(event, info, create_accounts=True):
    if info.get("startDate"): event.start_date = info["startDate"]
    if info.get("endDate"): event.end_date = info["endDate"]
    if info.get("city"): event.city = info["city"]
    if info.get("country"): event.country = info["country"]
    if info.get("organizer"): event.organizer = info["organizer"]
    if info.get("eventType"): event.event_type = info["eventType"]
    if info.get("sectors"): event.sectors = info["sectors"]
    if info.get("description"): event.description = info["description"]
    values, evidence, comm, econ, strat, total = automatic_analysis(info, event.cost_estimate)
    event.commercial_score, event.economic_score, event.strategic_score, event.total_score = comm, econ, strat, total
    event.score_details = {**values, "automatic": True, "evidence": evidence, "analyzedAt": datetime.now(timezone.utc).isoformat()}
    event.projection = automatic_projection(info, values, event.cost_estimate, (event.projection or {}).get("averageTicket") or 0)
    event.confidence = min(98, 50 + (15 if event.start_date else 0) + (10 if event.city else 0) + (10 if event.organizer else 0) + (10 if event.sectors else 0))
    event.normalized_key = event_key(event.name, event.start_date, event.city, event.organizer)
    if create_accounts:
        for item in info.get("accounts") or []:
            name = (item.get("companyName") or "").strip()
            if not name: continue
            existing = HubEventAccount.query.filter_by(tenant_id=event.tenant_id, event_id=event.id, company_name=name).first()
            if existing: continue
            website = item.get("website")
            acc = HubEventAccount(tenant_id=event.tenant_id, event_id=event.id, company_name=name, website=website,
                                  role=item.get("role") or "PARTICIPANT", tier="B" if values["icp"] >= 75 else "C",
                                  icp_score=values["icp"], hypothesis="Conta identificada automaticamente na página do evento; revisar antes de prospecção.")
            try:
                from ..models import Company
                domain = normalize_domain(website)
                q = Company.query.filter_by(tenant_id=event.tenant_id, status="ACTIVE")
                company = q.filter_by(domain=domain).first() if domain else q.filter_by(normalized_name=normalize_name(name)).first()
                acc.company_id = company.id if company else None
            except Exception:
                pass
            db.session.add(acc)
    return event


def _candidate_links(raw, base_url, same_host=True):
    host = urlparse(base_url).netloc.casefold()
    found = []
    for href, label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw, re.I | re.S):
        label = re.sub(r"<[^>]+>", " ", html.unescape(label)); label = re.sub(r"\s+", " ", label).strip()
        absolute = urljoin(base_url, href).split("#")[0]
        if not absolute.startswith(("http://", "https://")): continue
        if same_host and urlparse(absolute).netloc.casefold() != host: continue
        hay = _fold(f"{label} {absolute}")
        found.append((absolute, label, hay))
    return found


def scan_source(source, limit=40):
    diagnostics = {"source": source.name, "pagesChecked": 0, "candidates": 0, "errors": []}
    seed_urls = [source.url]
    # sitemap e feeds podem revelar páginas que a home não mostra.
    root = f"{urlparse(source.url).scheme}://{urlparse(source.url).netloc}/"
    for suffix in ("sitemap.xml", "feed/", "rss/"):
        try:
            raw = fetch_html(urljoin(root, suffix), timeout=8); diagnostics["pagesChecked"] += 1
            for loc in re.findall(r"<loc>(.*?)</loc>", raw, re.I | re.S):
                loc = html.unescape(loc).strip()
                if any(h in _fold(loc) for h in EVENT_PATH_HINTS): seed_urls.append(loc)
        except Exception:
            pass
    try:
        home = fetch_html(source.url); diagnostics["pagesChecked"] += 1
        for url, label, hay in _candidate_links(home, source.url):
            if any(k in hay for k in EVENT_PATH_HINTS) or any(k in hay for k in KEYWORDS): seed_urls.append(url)
    except Exception as exc:
        source.last_error = str(exc)[:500]; raise

    candidates = []
    seen_pages = set()
    for page_url in seed_urls[:30]:
        if page_url in seen_pages: continue
        seen_pages.add(page_url)
        try:
            raw = fetch_html(page_url, timeout=10); diagnostics["pagesChecked"] += 1
            page_text = _clean_text(raw)[:25000]
            # A própria página pode ser um evento.
            info = extract_page(page_url)
            hay = _fold(f"{info['name']} {info['description']} {page_text}")
            has_event_word = any(k in hay for k in KEYWORDS)
            has_date = bool(info.get("startDate"))
            if has_event_word and (has_date or len(info.get("sectors") or []) >= 1):
                candidates.append((page_url, info))
            # E pode apontar para eventos.
            for url, label, link_hay in _candidate_links(raw, page_url):
                if any(k in link_hay for k in KEYWORDS):
                    try:
                        child = extract_page(url)
                        chay = _fold(f"{child['name']} {child['description']}")
                        if any(k in chay for k in KEYWORDS) and (child.get("startDate") or len(child.get("sectors") or []) >= 1):
                            candidates.append((url, child))
                    except Exception:
                        continue
                if len(candidates) >= limit: break
        except Exception as exc:
            diagnostics["errors"].append(str(exc)[:160])
        if len(candidates) >= limit: break

    unique, seen = [], set()
    for url, info in candidates:
        clean = url.split("#")[0]
        key = (clean, normalize_name(info.get("name")))
        if key in seen: continue
        seen.add(key); unique.append((clean, info))
    diagnostics["candidates"] = len(unique)
    source.last_checked_at = datetime.now(timezone.utc); source.last_error = None if unique else "Nenhum candidato de evento encontrado nesta varredura."
    return unique[:limit], diagnostics


def create_detected_event(tenant_id, name, url=None, source=None, source_mode="AUTOMATIC", **fields):
    key = event_key(name, fields.get("start_date"), fields.get("city"), fields.get("organizer"))
    existing = HubEvent.query.filter_by(tenant_id=tenant_id, url=url).first() if url else None
    existing = existing or HubEvent.query.filter_by(tenant_id=tenant_id, normalized_key=key).first()
    if not existing:
        # Compatibilidade com eventos antigos criados antes do enriquecimento (sem data/cidade).
        existing = HubEvent.query.filter_by(tenant_id=tenant_id).filter(db.func.lower(HubEvent.name) == str(name).lower()).first()
    if existing:
        if url and not existing.url: existing.url = url
        return existing, False
    row = HubEvent(tenant_id=tenant_id, source_id=source.id if source else None, name=name[:320], normalized_key=key,
                   url=url, source_mode=source_mode, status="DETECTED", country=fields.get("country") or (source.country if source else "Paraguay"),
                   city=fields.get("city"), organizer=fields.get("organizer"), event_type=fields.get("event_type"),
                   description=fields.get("description"), confidence=fields.get("confidence", 55))
    db.session.add(row); db.session.flush()
    return row, True


def build_playbook(event, owner_name="Equipe HUB"):
    if not event.start_date: return 0
    HubEventAction.query.filter_by(tenant_id=event.tenant_id, event_id=event.id).delete()
    plan = [(-30,"T-30","Mapear organizador, participantes, expositores e 20–50 contas potenciais"),(-21,"T-21","Classificar contas Tier A/B/C e iniciar contato com Tier A"),(-14,"T-14","Mapear decisores, hipóteses de necessidade e agendar reuniões"),(-7,"T-7","Preparar briefing por conta, materiais e confirmar agenda"),(-1,"T-1","Confirmar logística, reuniões, responsáveis e metas"),(0,"DIA D","Executar agenda e registrar resultado + próximo passo de cada conversa"),(1,"D+1","Fazer follow-up personalizado de contas Tier A/B"),(3,"D+3","Converter interesses em reuniões, visitas ou oportunidades"),(7,"D+7","Revisar pipeline originado/influenciado pelo evento"),(30,"D+30","Fechar ROI, aprendizados e decisão sobre próxima edição")]
    for offset, phase, title in plan:
        due_date = event.start_date + timedelta(days=offset)
        db.session.add(HubEventAction(tenant_id=event.tenant_id,event_id=event.id,phase=phase,title=title,due_at=datetime.combine(due_date,time(9,0),tzinfo=timezone.utc),owner_name=owner_name))
    return len(plan)


def run_hub_event_scan(tenant_id=None):
    query = HubEventSource.query.filter_by(status="ACTIVE")
    if tenant_id: query = query.filter_by(tenant_id=tenant_id)
    stats = {"sources":0,"found":0,"created":0,"updated":0,"errors":[],"diagnostics":[]}
    for source in query.all():
        stats["sources"] += 1
        try:
            rows, diag = scan_source(source); stats["diagnostics"].append(diag); stats["found"] += len(rows)
            for url, info in rows:
                event, created = create_detected_event(source.tenant_id, info["name"], url=url, source=source, source_mode="AUTOMATIC",
                                                       start_date=info.get("startDate"), city=info.get("city"), organizer=info.get("organizer"),
                                                       country=info.get("country") or source.country, event_type=info.get("eventType"),
                                                       description=info.get("description"), confidence=70)
                apply_automatic_intelligence(event, info, create_accounts=True)
                stats["created"] += int(created); stats["updated"] += int(not created)
        except Exception as exc:
            source.last_error = str(exc)[:500]; stats["errors"].append({"source":source.name,"error":str(exc)})
    db.session.commit(); return stats
