import hashlib
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from ..extensions import db
from ..models import CollectorRun, ProspectSignal
from ..tenant import current_tenant
from .intelligence import estimate_deal_range, infer_buying_window, infer_lifecycle

USER_AGENT = os.getenv("RADAR_USER_AGENT", "IndustrialRevenueRadar/2.0")
MIN_SIGNAL_SCORE = int(os.getenv("COLLECTOR_MIN_SCORE", "52"))
MAX_SIGNAL_AGE_DAYS = int(os.getenv("COLLECTOR_MAX_AGE_DAYS", "180"))


def google_news_feed(name, query, reliability=65):
    return {
        "name": name,
        "url": "https://news.google.com/rss/search?q=" + quote(query) + "&hl=es-419&gl=PY&ceid=PY:es-419",
        "type": "AGGREGATOR", "reliability": reliability,
    }


DEFAULT_FEEDS = [
    {"name": "MIC Paraguay", "url": "https://www.mic.gov.py/feed/", "type": "OFFICIAL", "reliability": 95},
    google_news_feed("Inversiones y radicación", '(inversión OR radicación OR maquila OR "nueva planta") Paraguay empresa', 68),
    google_news_feed("Terrenos y parques industriales", '("adquiere terreno" OR "compra terreno" OR "parque industrial") Paraguay empresa', 65),
    google_news_feed("Licencias y ambiente", '("licencia ambiental" OR "impacto ambiental") (planta OR fábrica OR depósito OR frigorífico) Paraguay', 67),
    google_news_feed("Financiación industrial", '(financiamiento OR crédito OR préstamo) (industria OR fábrica OR frigorífico OR logística) Paraguay', 65),
    google_news_feed("Obras industriales", '(terraplenado OR construcción OR "estructura metálica" OR galpón OR "nave industrial") empresa Paraguay', 67),
    google_news_feed("Logística y distribución", '("centro de distribución" OR "centro logístico" OR "nuevo depósito" OR warehouse) Paraguay', 68),
    google_news_feed("Cadena de frío", '(frigorífico OR "cámara frigorífica" OR "cadena de frío" OR "planta de alimentos") Paraguay', 68),
    google_news_feed("Hangares y aeronáutica", '(hangar OR aeropuerto OR aviación) (construcción OR ampliación OR proyecto) Paraguay', 65),
    google_news_feed("Contrataciones y expansión", '(contrata OR contratación OR vacantes OR empleo) (ingeniero OR mantenimiento OR logística OR planta) empresa Paraguay', 55),
    google_news_feed("Equipos y nuevas líneas", '(importa OR instala OR recibe) (maquinaria OR equipos OR "línea de producción") empresa Paraguay', 60),
    google_news_feed("Retail y supermercados", '(nuevo supermercado OR expansión OR "centro comercial") Paraguay empresa', 58),
]

DNCP_TERMS = [
    "puertas automáticas", "portones", "muelle de carga", "nivelador de muelle", "hangar",
    "cámara frigorífica", "galpón industrial", "centro de distribución", "depósito industrial",
]

EVENT_RULES = [
    ("LAND_ACQUISITION", ("adquiere terreno", "compra terreno", "adquisición de terreno", "lote industrial"), 34),
    ("ENVIRONMENTAL_LICENSE", ("licencia ambiental", "declaración de impacto ambiental", "impacto ambiental"), 34),
    ("FINANCING_APPROVED", ("financiamiento aprobado", "crédito aprobado", "préstamo aprobado", "financiará"), 32),
    ("PROJECT_ANNOUNCEMENT", ("proyecto industrial", "proyecta construir", "prevé construir", "anuncia inversión"), 28),
    ("NEW_FACTORY", ("nueva fábrica", "nueva planta", "planta industrial", "instalación industrial"), 34),
    ("EXPANSION", ("ampliación", "expansión", "aumento de capacidad", "segunda etapa", "duplicará capacidad"), 31),
    ("NEW_LOGISTICS_CENTER", ("centro logístico", "centro de distribución", "nuevo depósito", "nuevo almacen", "nave logística"), 34),
    ("COLD_CHAIN_PROJECT", ("nuevo frigorífico", "planta frigorífica", "cámara frigorífica", "cadena de frío"), 34),
    ("CONSTRUCTION_START", ("inició obras", "inician obras", "inicio de obras", "comenzó la construcción", "terraplenado"), 33),
    ("CONSTRUCTION", ("construcción", "estructura metálica", "obra industrial", "galpón industrial", "nave industrial"), 25),
    ("TENDER", ("licitación", "licitacion", "convocatoria", "adjudicación", "adjudicacion"), 26),
    ("EQUIPMENT_IMPORT", ("importa maquinaria", "llegada de equipos", "instala maquinaria", "línea de producción"), 24),
    ("HIRING_SURGE", ("contratación masiva", "nuevas vacantes", "incorpora personal", "contrata ingenieros", "busca gerente"), 20),
    ("INAUGURATION", ("inaugura", "inauguración", "entra en operación", "puesta en marcha"), 12),
]

CAUSALITY_RULES = [
    (("frigorífico", "frigorifico", "cámara fría", "cadena de frío", "refrigerado"), ["Separación térmica", "Alto flujo", "Higiene"], ["Puerta rápida", "Puerta frigorífica", "Puerta seccional"]),
    (("centro logístico", "centro de distribución", "depósito", "almacén", "warehouse", "muelle"), ["Carga y descarga", "Múltiples accesos", "Flujo logístico"], ["Puerta seccional", "Nivelador de andén", "Abrigo de muelle", "Puerta rápida"]),
    (("fábrica", "fabrica", "planta", "manufactura", "producción", "industrial"), ["Accesos industriales", "Continuidad operativa"], ["Puerta seccional", "Puerta rápida", "Automatización", "Mantenimiento"]),
    (("hangar", "aviación", "aeronáutico", "aeropuerto"), ["Gran vano", "Acceso de aeronaves"], ["Puerta de hangar", "Automatización"]),
    (("supermercado", "shopping", "centro comercial", "retail"), ["Recepción de mercadería", "Acceso de servicio"], ["Puerta seccional", "Puerta rápida", "Nivelador de andén"]),
]

NEGATIVE_TERMS = {
    "vivienda": -20, "ruta": -14, "empedrado": -18, "alcantarillado": -20, "plaza": -20,
    "escuela": -20, "consultoría": -20, "medicamentos": -25, "puente": -22, "carretera": -22,
    "agua potable": -25, "hospital": -18, "vereda": -18,
}

DEPARTMENTS = [
    "Alto Paraná", "Central", "Itapúa", "Caaguazú", "Presidente Hayes", "Amambay", "Concepción",
    "Paraguarí", "Cordillera", "San Pedro", "Canindeyú", "Boquerón", "Guairá", "Misiones", "Ñeembucú",
]

PRIORITY_LOCATIONS = {
    "alto paraná": 100, "ciudad del este": 100, "hernandarias": 100, "minga guazú": 100,
    "santa rita": 95, "san alberto": 95, "central": 80, "asunción": 80, "itapúa": 75,
}


def _fetch(url):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5"})
    with urlopen(request, timeout=20) as response:
        return response.read()


def _plain(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _parse_date(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def _extra_feeds():
    raw = os.getenv("COLLECTOR_EXTRA_FEEDS", "").strip()
    if not raw:
        return []
    feeds = []
    for index, url in enumerate(part.strip() for part in raw.split(",") if part.strip()):
        if url.startswith(("https://", "http://")):
            feeds.append({"name": f"Fuente personalizada {index + 1}", "url": url, "type": "CUSTOM", "reliability": 55})
    return feeds


def collect_feed(source):
    root = ElementTree.fromstring(_fetch(source["url"]))
    items = []
    for node in root.findall(".//item")[:80]:
        title = _plain(node.findtext("title"))
        link = _plain(node.findtext("link"))
        summary = _plain(node.findtext("description") or node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded"))
        if title and link:
            items.append({"company": infer_company(title), "title": title, "summary": summary, "url": link, "published_at": _parse_date(node.findtext("pubDate")), "source": source})
    return items


def collect_dncp():
    source = {"name": "DNCP Datos Abiertos", "type": "OFFICIAL", "reliability": 100}
    items = []
    base = "https://www.contrataciones.gov.py/datos/api/v3/doc/search/processes"
    for term in DNCP_TERMS:
        url = base + "?" + urlencode({"tender.title": term, "items_per_page": "20", "order": "date desc"})
        payload = json.loads(_fetch(url).decode("utf-8"))
        for record in payload.get("records", []):
            release = record.get("compiledRelease") or {}
            tender = release.get("tender") or {}
            buyer = release.get("buyer") or tender.get("procuringEntity") or {}
            title = _plain(tender.get("title"))
            if not title:
                continue
            items.append({
                "company": _plain(buyer.get("name")) or "Entidad por validar", "title": title,
                "summary": _plain(tender.get("mainProcurementCategoryDetails") or tender.get("procurementMethodDetails")),
                "url": "https://www.contrataciones.gov.py/buscador/licitaciones.html?" + urlencode({"nro_nombre_licitacion": title}),
                "published_at": _parse_date(release.get("date")), "source": source,
                "external_id": record.get("ocid") or tender.get("id"),
            })
    return items


def infer_company(title):
    patterns = [
        r"^(.{2,90}?)\s+(?:anuncia|invierte|inaugura|amplía|amplia|construye|instala|proyecta|abre|adquiere|compra|obtiene|recibe)\b",
        r"^(?:la\s+)?(?:empresa|firma|compañía)\s+(.{2,80}?)\s+(?:anuncia|invierte|inaugura|amplía|construye|proyecta|obtiene)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip(" -:,.\"")
            candidate = re.sub(r"^(?:grupo|empresa|firma|compañía)\s+", "", candidate, flags=re.I)
            if candidate and 1 <= len(candidate.split()) <= 9:
                return candidate
    return "Empresa por validar"


def _event_detection(text):
    best = ("MARKET_SIGNAL", 0)
    for event, terms, points in EVENT_RULES:
        matches = sum(1 for term in terms if term in text)
        value = points + max(0, matches - 1) * 5 if matches else 0
        if value > best[1]:
            best = (event, value)
    return best


def _causality(text):
    causes, products = [], []
    for terms, detected_causes, detected_products in CAUSALITY_RULES:
        if any(term in text for term in terms):
            causes.extend(detected_causes)
            products.extend(detected_products)
    return list(dict.fromkeys(causes)), list(dict.fromkeys(products))


def _geographic_fit(text):
    score = 55 if "paraguay" in text else 25
    for term, value in PRIORITY_LOCATIONS.items():
        if term in text:
            return max(score, value)
    if any(department.lower() in text for department in DEPARTMENTS):
        return max(score, 72)
    return score


def analyze(item):
    text = f"{item['title']} {item.get('summary', '')}".lower()
    event_type, event_points = _event_detection(text)
    causality, products = _causality(text)
    geographic = _geographic_fit(text)
    source_reliability = int(item["source"].get("reliability", 50))
    buying_window = infer_buying_window(event_type)
    lifecycle = infer_lifecycle(event_type, buying_window)

    score = round(source_reliability * 0.20) + event_points
    reasons = [f"Fuente con confianza {source_reliability}%"]
    if event_points:
        score += 10
        reasons.append(f"Evento precursor detectado: {event_type}")
    if causality:
        score += min(24, 8 + len(causality) * 4)
        reasons.append("Demanda inferida por causalidad industrial, no solo por mención de puertas")
    if geographic >= 75:
        score += 12
        reasons.append("Ubicación prioritaria para cobertura comercial")
    elif geographic >= 55:
        score += 7
    if item.get("company") not in {"Empresa por validar", "Entidad por validar"}:
        score += 7
        reasons.append("Empresa o entidad identificada")
    for term, penalty in NEGATIVE_TERMS.items():
        if term in text:
            score += penalty
    if event_type in {"INAUGURATION"}:
        reasons.append("Señal tardía: priorizar mantenimiento/retrofit y validar compras ya realizadas")
    if event_type == "MARKET_SIGNAL" and not causality:
        score = min(score, 42)
        reasons.append("Señal débil: requiere investigación antes de activar ventas")
    if item["source"].get("type") == "AGGREGATOR" and geographic < 55:
        score = min(score, 40)
        reasons.append("Sin ubicación paraguaya suficientemente clara")

    score = max(0, min(100, score))
    level = "HOT" if score >= 88 else "HIGH" if score >= 72 else "MEDIUM" if score >= 52 else "LOW"
    demand_probability = min(100, 35 + len(products) * 10 + (20 if event_type in {"NEW_FACTORY", "NEW_LOGISTICS_CENTER", "COLD_CHAIN_PROJECT", "EXPANSION", "CONSTRUCTION_START"} else 0))
    low, high = estimate_deal_range(event_type, products)
    momentum_delta = {
        "LAND_ACQUISITION": 10, "ENVIRONMENTAL_LICENSE": 14, "FINANCING_APPROVED": 16,
        "PROJECT_ANNOUNCEMENT": 12, "NEW_INVESTMENT": 16, "NEW_FACTORY": 18, "EXPANSION": 18,
        "CONSTRUCTION_START": 22, "CONSTRUCTION": 18, "NEW_LOGISTICS_CENTER": 20,
        "COLD_CHAIN_PROJECT": 20, "TENDER": 24, "EQUIPMENT_IMPORT": 14, "HIRING_SURGE": 9,
        "INAUGURATION": -5,
    }.get(event_type, 3)
    why_now = (
        f"Se detectó {event_type} con buying window {buying_window}/100. "
        + (f"La infraestructura sugiere {', '.join(causality[:3])}. " if causality else "")
        + ("La cuenta está en una fase donde conviene validar cronograma y responsables antes de que la especificación quede cerrada." if buying_window >= 75 else "Conviene enriquecer y seguir monitoreando antes de activar una cadencia intensa.")
    )
    return {
        "score": score, "level": level, "event_type": event_type, "products": products,
        "reasons": reasons, "buying_window": buying_window, "lifecycle": lifecycle,
        "momentum_delta": momentum_delta, "demand_probability": demand_probability,
        "causality": causality, "deal_min": low, "deal_max": high, "why_now": why_now,
    }


def _fingerprint(item):
    identity = item.get("external_id") or item.get("url") or item.get("title")
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _is_older_than(value, cutoff):
    if not value:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value < cutoff


def requalify_pending_signals():
    tenant = current_tenant()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_SIGNAL_AGE_DAYS)
    rows = ProspectSignal.query.filter_by(tenant_id=tenant.id, status="PENDING_VALIDATION").all()
    for signal in rows:
        item = {
            "company": signal.company_name, "title": signal.title, "summary": signal.summary,
            "source": {"name": signal.source_name, "type": signal.source_type, "reliability": signal.source_reliability},
        }
        result = analyze(item)
        if result["score"] < MIN_SIGNAL_SCORE or _is_older_than(signal.published_at, cutoff):
            signal.status = "DISCARDED"
            continue
        signal.score, signal.level, signal.event_type = result["score"], result["level"], result["event_type"]
        signal.products, signal.reasons = result["products"], result["reasons"]
        signal.buying_window_score, signal.lifecycle_stage = result["buying_window"], result["lifecycle"]
        signal.momentum_delta, signal.demand_probability = result["momentum_delta"], result["demand_probability"]
        signal.causality = result["causality"]
        signal.estimated_deal_min, signal.estimated_deal_max = result["deal_min"], result["deal_max"]
        signal.why_now = result["why_now"]


def run_collector():
    tenant = current_tenant()
    run = CollectorRun(tenant_id=tenant.id)
    db.session.add(run)
    db.session.commit()
    requalify_pending_signals()
    errors, scanned, created, sources_scanned = [], 0, 0, 0
    batches = []
    for source in DEFAULT_FEEDS + _extra_feeds():
        try:
            batches.append(collect_feed(source)); sources_scanned += 1
        except Exception as exc:
            errors.append(f"{source['name']}: {str(exc)[:180]}")
    try:
        batches.append(collect_dncp()); sources_scanned += 1
    except Exception as exc:
        errors.append(f"DNCP Datos Abiertos: {str(exc)[:180]}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_SIGNAL_AGE_DAYS)
    for batch in batches:
        for item in batch:
            scanned += 1
            if _is_older_than(item.get("published_at"), cutoff):
                continue
            fingerprint = _fingerprint(item)
            if ProspectSignal.query.filter_by(tenant_id=tenant.id, fingerprint=fingerprint).first():
                continue
            result = analyze(item)
            if result["score"] < MIN_SIGNAL_SCORE:
                continue
            text = f"{item['title']} {item.get('summary', '')}"
            department = next((name for name in DEPARTMENTS if name.lower() in text.lower()), None)
            db.session.add(ProspectSignal(
                tenant_id=tenant.id, fingerprint=fingerprint, company_name=item["company"], title=item["title"],
                summary=item.get("summary") or item["title"], source_name=item["source"]["name"], source_url=item["url"],
                source_type=item["source"]["type"], source_reliability=item["source"]["reliability"],
                published_at=item.get("published_at"), department=department, event_type=result["event_type"],
                score=result["score"], level=result["level"], products=result["products"], reasons=result["reasons"],
                buying_window_score=result["buying_window"], lifecycle_stage=result["lifecycle"],
                momentum_delta=result["momentum_delta"], demand_probability=result["demand_probability"],
                causality=result["causality"], estimated_deal_min=result["deal_min"], estimated_deal_max=result["deal_max"],
                why_now=result["why_now"],
            ))
            created += 1
    run.sources_scanned, run.items_scanned, run.signals_created = sources_scanned, scanned, created
    run.errors, run.status, run.finished_at = errors, "COMPLETED" if sources_scanned else "FAILED", datetime.now(timezone.utc)
    db.session.commit()
    return run
