import html
import re
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ..extensions import db
from ..models import HubEvent, HubEventAction, HubEventSource
from .entity_resolution import normalize_name

KEYWORDS = ("evento", "event", "feira", "feria", "expo", "congreso", "congress", "summit", "business", "rueda", "ronda", "misión", "mision", "encuentro", "forum", "fórum", "jornada")


def event_key(name, start_date=None, city=None, organizer=None):
    return "|".join([normalize_name(name), str(start_date or ""), normalize_name(city), normalize_name(organizer)])[:500]


def fetch_html(url, timeout=12):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 HG-Radar-HUB/1.0"})
    with urlopen(req, timeout=timeout) as response:
        ctype = response.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            raise ValueError("La fuente no devuelve una página HTML")
        return response.read(1_500_000).decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def extract_page(url):
    raw = fetch_html(url)
    title = ""
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    if match:
        title = re.sub(r"<[^>]+>", " ", html.unescape(match.group(1)))
    og = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', raw, re.I)
    if og:
        title = html.unescape(og.group(1))
    desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)', raw, re.I)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return {"name": re.sub(r"\s+", " ", title).strip()[:320] or urlparse(url).netloc,
            "url": url, "description": (html.unescape(desc.group(1)) if desc else text[:900])[:1600], "raw": raw}


def scan_source(source, limit=30):
    raw = fetch_html(source.url)
    links = []
    for href, label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw, re.I | re.S):
        label = re.sub(r"<[^>]+>", " ", html.unescape(label))
        label = re.sub(r"\s+", " ", label).strip()
        absolute = urljoin(source.url, href)
        hay = f"{label} {absolute}".casefold()
        if len(label) >= 5 and any(k in hay for k in KEYWORDS) and absolute.startswith(("http://", "https://")):
            links.append((absolute, label[:320]))
    unique = []
    seen = set()
    for url, label in links:
        clean = url.split("#")[0]
        if clean in seen: continue
        seen.add(clean); unique.append((clean, label))
        if len(unique) >= limit: break
    source.last_checked_at = datetime.now(timezone.utc); source.last_error = None
    return unique


def create_detected_event(tenant_id, name, url=None, source=None, source_mode="AUTOMATIC", **fields):
    key = event_key(name, fields.get("start_date"), fields.get("city"), fields.get("organizer"))
    existing = HubEvent.query.filter_by(tenant_id=tenant_id, normalized_key=key).first()
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
    plan = [
        (-30, "T-30", "Mapear organizador, participantes, expositores e 20–50 contas potenciais"),
        (-21, "T-21", "Classificar contas Tier A/B/C e iniciar contato com Tier A"),
        (-14, "T-14", "Mapear decisores, hipóteses de necessidade e agendar reuniões"),
        (-7, "T-7", "Preparar briefing por conta, materiais e confirmar agenda"),
        (-1, "T-1", "Confirmar logística, reuniões, responsáveis e metas"),
        (0, "DIA D", "Executar agenda e registrar resultado + próximo passo de cada conversa"),
        (1, "D+1", "Fazer follow-up personalizado de contas Tier A/B"),
        (3, "D+3", "Converter interesses em reuniões, visitas ou oportunidades"),
        (7, "D+7", "Revisar pipeline originado/influenciado pelo evento"),
        (30, "D+30", "Fechar ROI, aprendizados e decisão sobre próxima edição"),
    ]
    for offset, phase, title in plan:
        due_date = event.start_date + timedelta(days=offset)
        due_at = datetime.combine(due_date, time(9, 0), tzinfo=timezone.utc)
        db.session.add(HubEventAction(tenant_id=event.tenant_id, event_id=event.id, phase=phase, title=title, due_at=due_at, owner_name=owner_name))
    return len(plan)


def run_hub_event_scan(tenant_id=None):
    """Varredura automática das fontes HUB ativas; só cria candidatos para triagem."""
    from ..models import HubEventSource
    query = HubEventSource.query.filter_by(status="ACTIVE")
    if tenant_id:
        query = query.filter_by(tenant_id=tenant_id)
    stats = {"sources": 0, "found": 0, "created": 0, "errors": []}
    for source in query.all():
        stats["sources"] += 1
        try:
            links = scan_source(source)
            stats["found"] += len(links)
            for url, label in links:
                _, created = create_detected_event(source.tenant_id, label, url=url, source=source, source_mode="AUTOMATIC", confidence=60)
                stats["created"] += int(created)
        except Exception as exc:
            source.last_error = str(exc)[:500]
            stats["errors"].append({"source": source.name, "error": str(exc)})
    db.session.commit()
    return stats
