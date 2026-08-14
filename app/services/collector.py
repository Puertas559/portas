import hashlib
import html
import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from ..extensions import db
from ..models import CollectorRun, ProspectSignal

USER_AGENT = "PuertasBrasilPY-ProspectingRadar/1.0 (+https://portas-production.up.railway.app)"
MIN_SIGNAL_SCORE = int(os.getenv("COLLECTOR_MIN_SCORE", "45"))

DEFAULT_FEEDS = [
    {"name": "MIC Paraguay", "url": "https://www.mic.gov.py/feed/", "type": "OFFICIAL", "reliability": 95},
    {"name": "Noticias industriales Paraguay", "url": "https://news.google.com/rss/search?q=" + quote('("nueva fábrica" OR "ampliación industrial" OR "centro logístico" OR maquila OR frigorífico OR "nave industrial") Paraguay') + "&hl=es-419&gl=PY&ceid=PY:es-419", "type": "AGGREGATOR", "reliability": 60},
    {"name": "Inversiones Paraguay", "url": "https://news.google.com/rss/search?q=" + quote('(inversión OR planta OR depósito OR construcción) (empresa OR industria) Paraguay') + "&hl=es-419&gl=PY&ceid=PY:es-419", "type": "AGGREGATOR", "reliability": 58},
    {"name": "Parques y logística Paraguay", "url": "https://news.google.com/rss/search?q=" + quote('("parque industrial" OR "zona franca" OR "centro de distribución" OR logística) Paraguay') + "&hl=es-419&gl=PY&ceid=PY:es-419", "type": "AGGREGATOR", "reliability": 58},
    {"name": "Agroindustria Paraguay", "url": "https://news.google.com/rss/search?q=" + quote('(agroindustria OR frigorífico OR silo OR molino OR alimentos) (inversión OR planta OR ampliación) Paraguay') + "&hl=es-419&gl=PY&ceid=PY:es-419", "type": "AGGREGATOR", "reliability": 58},
]

DNCP_TERMS = ["construcción", "planta industrial", "depósito", "centro logístico", "mantenimiento industrial"]

KEYWORDS = {
    "NEW_FACTORY": [("nueva fábrica", 30), ("nueva planta", 28), ("instalación industrial", 24), ("industria", 8)],
    "EXPANSION": [("ampliación", 25), ("expansión", 25), ("aumento de capacidad", 22), ("segunda etapa", 12)],
    "NEW_LOGISTICS_CENTER": [("centro logístico", 30), ("depósito", 22), ("almacén", 18), ("nave industrial", 28), ("centro de distribución", 28)],
    "INVESTMENT": [("inversión", 20), ("millones", 10), ("maquila", 18), ("radicación", 20)],
    "CONSTRUCTION": [("construcción", 15), ("obra", 10), ("licitación", 8), ("infraestructura", 8)],
}

NEGATIVE_TERMS = {
    "vivienda": -18, "ruta": -12, "empedrado": -15, "alcantarillado": -15,
    "plaza": -12, "escuela": -10, "consultoría": -12, "medicamentos": -18,
}

DEPARTMENTS = ["Alto Paraná", "Central", "Itapúa", "Caaguazú", "Presidente Hayes", "Amambay", "Concepción", "Paraguarí", "Cordillera"]


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
            feeds.append({"name": f"Fuente personalizada {index + 1}", "url": url, "type": "CUSTOM", "reliability": 50})
    return feeds


def collect_feed(source):
    root = ElementTree.fromstring(_fetch(source["url"]))
    items = []
    for node in root.findall(".//item")[:60]:
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
            ocid = record.get("ocid") or tender.get("id")
            items.append({
                "company": _plain(buyer.get("name")) or "Entidad por validar",
                "title": title,
                "summary": _plain(tender.get("mainProcurementCategoryDetails") or tender.get("procurementMethodDetails")),
                "url": f"https://www.contrataciones.gov.py/licitaciones/convocatoria/{tender.get('id')}" if tender.get("id") else url,
                "published_at": _parse_date(release.get("date")), "source": source, "external_id": ocid,
            })
    return items


def infer_company(title):
    verb = r"anuncia|invierte|inaugura|amplía|amplia|construye|instala|proyecta|gana|abre"
    match = re.search(rf"^(.{{2,70}}?)\s+(?:{verb})\b", title, re.IGNORECASE)
    if match:
        candidate = match.group(1).strip(" -:,.")
        candidate = re.sub(r"^(?:la\s+)?(?:empresa|firma|compañía)\s+", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"^grupo\s+", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"^(?:paraguaya|brasileña|argentina|española|español|farmacéutica|industrial)\s+", "", candidate, flags=re.IGNORECASE)
        generic = {"paraguaya", "brasileña", "argentina", "española", "español", "farmacéutica", "industrial", "sector"}
        if candidate and candidate.lower() not in generic and len(candidate.split()) <= 6:
            return candidate
    return "Empresa por validar"


def analyze(item):
    text = f"{item['title']} {item.get('summary', '')}".lower()
    score = round(item["source"]["reliability"] * 0.2)
    reasons = [f"Fuente con confianza {item['source']['reliability']}%"]
    event_type = "MARKET_SIGNAL"
    best_event_points = 0
    for candidate, terms in KEYWORDS.items():
        event_points = sum(points for term, points in terms if term in text)
        if event_points > best_event_points:
            event_type, best_event_points = candidate, event_points
    score += min(best_event_points, 40)
    if best_event_points:
        reasons.append("Evento compatible con expansión, inversión u obra")
    if "paraguay" in text or any(department.lower() in text for department in DEPARTMENTS):
        score += 12
        reasons.append("Ubicación compatible con el mercado paraguayo")
    for term, penalty in NEGATIVE_TERMS.items():
        if term in text:
            score += penalty
    if item.get("company") not in {"Empresa por validar", "Entidad por validar"}:
        score += 8
        reasons.append("Empresa o entidad identificada")
    score = max(0, min(100, score))
    level = "HOT" if score >= 85 else "HIGH" if score >= 68 else "MEDIUM" if score >= 50 else "LOW"
    products = []
    if any(term in text for term in ["logístico", "depósito", "almacén", "distribución", "nave"]):
        products.extend(["Puerta seccional", "Puerta rápida", "Nivelador de andén"])
    if any(term in text for term in ["frigorífico", "alimentos", "cámara", "refriger"]):
        products.extend(["Puerta rápida", "Puerta frigorífica"])
    if any(term in text for term in ["fábrica", "planta", "industrial", "construcción", "obra"]):
        products.extend(["Puerta seccional", "Automatización", "Mantenimiento"])
    return score, level, event_type, list(dict.fromkeys(products)), reasons


def _fingerprint(item):
    identity = item.get("external_id") or item.get("url") or item.get("title")
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def run_collector():
    run = CollectorRun()
    db.session.add(run)
    db.session.commit()
    errors, scanned, created, sources_scanned = [], 0, 0, 0
    sources = DEFAULT_FEEDS + _extra_feeds()
    batches = []
    for source in sources:
        try:
            batches.append(collect_feed(source))
            sources_scanned += 1
        except Exception as exc:
            errors.append(f"{source['name']}: {str(exc)[:180]}")
    try:
        batches.append(collect_dncp())
        sources_scanned += 1
    except Exception as exc:
        errors.append(f"DNCP Datos Abiertos: {str(exc)[:180]}")
    for batch in batches:
        for item in batch:
            scanned += 1
            fingerprint = _fingerprint(item)
            if ProspectSignal.query.filter_by(fingerprint=fingerprint).first():
                continue
            score, level, event_type, products, reasons = analyze(item)
            if score < MIN_SIGNAL_SCORE:
                continue
            text = f"{item['title']} {item.get('summary', '')}"
            department = next((name for name in DEPARTMENTS if name.lower() in text.lower()), None)
            db.session.add(ProspectSignal(
                fingerprint=fingerprint, company_name=item["company"], title=item["title"], summary=item.get("summary") or item["title"],
                source_name=item["source"]["name"], source_url=item["url"], source_type=item["source"]["type"],
                source_reliability=item["source"]["reliability"], published_at=item.get("published_at"), department=department,
                event_type=event_type, score=score, level=level, products=products, reasons=reasons,
            ))
            created += 1
    run.sources_scanned, run.items_scanned, run.signals_created = sources_scanned, scanned, created
    run.errors, run.status, run.finished_at = errors, "COMPLETED" if sources_scanned else "FAILED", datetime.now(timezone.utc)
    db.session.commit()
    return run
