import html
import ipaddress
import json
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ..extensions import db
from ..models import WebsiteAnalysis
from ..tenant import current_tenant

USER_AGENT = os.getenv("RADAR_USER_AGENT", "PuertasBrasilRevenueRadar/2.1")
MAX_BYTES = 2_000_000
MAX_PAGES = 18
MAX_SITEMAP_URLS = 80

SECTORS = {
    "Logística y distribución": ["logística", "logistica", "distribución", "distribucion", "depósito", "deposito", "almacén", "almacen", "transportadora", "centro de distribución", "cross docking", "cross-docking"],
    "Alimentos y bebidas": ["alimentos", "bebidas", "lácteos", "lacteos", "molino", "panificadora", "supermercado", "producción alimentaria", "procesamiento de alimentos"],
    "Frigorífico y cadena de frío": ["frigorífico", "frigorifico", "frigorífica", "frigorifica", "refrigerado", "cámara fría", "cámaras frías", "camara fria", "camaras frias", "congelados", "cadena de frío"],
    "Industria y manufactura": ["industria", "industrial", "fábrica", "fabrica", "manufactura", "producción", "produccion", "metalúrgica", "metalurgica", "planta productiva"],
    "Agronegocio": ["agro", "semillas", "granos", "silo", "cooperativa", "agricultura", "fertilizantes", "acopio", "agroindustrial"],
    "Aeronáutico": ["aeronáutica", "aeronautica", "aeronave", "hangar", "aviación", "aviacion", "aeropuerto"],
    "Comercio de gran porte": ["shopping", "centro comercial", "retail", "hipermercado", "tienda", "importadora", "estacionamiento"],
    "Construcción e ingeniería": ["constructora", "construcción", "construccion", "ingeniería", "ingenieria", "arquitectura", "obra industrial", "estructura metálica"],
}

PRODUCT_RULES = [
    (["muelle", "dársena", "darsena", "carga y descarga", "camiones", "centro de distribución", "cross docking", "logística", "depósito"], ["Puertas seccionales", "Niveladoras de docas", "Abrigos/sellos de docas"]),
    (["frigorífico", "frigorífica", "refrigerado", "cámara fría", "cámaras frías", "congelados", "cadena de frío"], ["Puertas rápidas frigoríficas", "Abrigos/sellos de docas", "Puertas seccionales"]),
    (["alto flujo", "línea de producción", "linea de produccion", "higiene", "alimentos", "farmacéutica", "farmaceutica"], ["Puertas rápidas de lona enrollables"]),
    (["hangar", "aeronave", "aviación", "gran formato", "aeropuerto"], ["Puertas de gran formato para hangares", "Puertas rápidas plegables"]),
    (["galpón", "galpon", "nave industrial", "fábrica", "fabrica", "planta industrial", "centro industrial"], ["Puertas seccionales", "Puertas de acero enrollables", "Puertas rápidas plegables"]),
    (["seguridad contra incendios", "protección contra incendios", "cortafuego", "corta fuego"], ["Puertas cortafuego bajo proyecto"]),
    (["shopping", "comercio", "local comercial", "estacionamiento", "retail"], ["Puertas de acero enrollables", "Automatización de accesos"]),
]

PROJECT_SIGNALS = {
    "expansión": ["expansión", "expansion", "ampliación", "ampliacion", "ampliamos", "expandimos"],
    "nueva planta": ["nueva planta", "nueva fábrica", "nueva fabrica", "planta industrial", "nuevas instalaciones"],
    "obra/construcción": ["construcción", "construccion", "obra", "terraplenado", "estructura metálica", "estructura metalica"],
    "inversión": ["inversión", "inversion", "invertirá", "invertira", "financiamiento", "financiación", "financiacion"],
    "nuevo centro logístico": ["centro de distribución", "centro logistico", "centro logístico", "nuevo depósito", "nuevo deposito", "almacén logístico"],
    "capacidad productiva": ["aumento de capacidad", "capacidad productiva", "nueva línea de producción", "nueva linea de produccion", "duplicar la producción", "triplicar la producción"],
    "adquisición/terreno": ["adquisición de terreno", "adquisicion de terreno", "compra de terreno", "nuevo predio", "nuevo inmueble"],
    "licencia/proyecto": ["licencia ambiental", "evaluación de impacto", "evaluacion de impacto", "proyecto ejecutivo", "proyecto industrial"],
    "contratación": ["estamos contratando", "trabajá con nosotros", "trabaja con nosotros", "vacantes", "buscamos ingeniero", "buscamos gerente"],
}

ROLE_TERMS = (
    "gerente", "director", "directora", "responsable", "jefe", "jefa", "encargado", "encargada",
    "coordinador", "coordinadora", "supervisor", "supervisora"
)
ROLE_AREAS = (
    "mantenimiento", "operaciones", "ingeniería", "ingenieria", "logística", "logistica", "proyectos",
    "infraestructura", "compras", "abastecimiento", "industrial", "planta", "facilities"
)

PRIORITY_PATH_TERMS = {
    "contact": 100, "contacto": 100, "contato": 100,
    "proyecto": 96, "project": 96, "obra": 96, "expansion": 96, "expansión": 96,
    "noticia": 92, "news": 92, "novedad": 92, "prensa": 92,
    "infraestructura": 90, "instalacion": 90, "instalación": 90, "planta": 90,
    "logistica": 88, "logística": 88, "deposito": 88, "depósito": 88, "frigor": 88,
    "servicio": 82, "solucion": 82, "solución": 82, "producto": 82,
    "empresa": 80, "nosotros": 80, "quienes": 80, "about": 80, "historia": 78,
    "sucursal": 76, "ubicacion": 76, "ubicación": 76, "location": 76,
    "trabaja": 72, "empleo": 72, "career": 72, "vacante": 72,
}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.links = []
        self.title = ""
        self.meta = []
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and attrs.get("href"):
            label = " ".join(filter(None, (attrs.get("aria-label"), attrs.get("title"))))
            self.links.append((attrs.get("href"), label))
        if tag == "meta" and attrs.get("content"):
            key = (attrs.get("name") or attrs.get("property") or "").lower()
            if key in {"description", "og:description", "og:title", "twitter:description", "twitter:title"}:
                self.meta.append(attrs.get("content"))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        clean = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if clean:
            self.text.append(clean)
            if self._in_title:
                self.title += clean + " "


def _normalize_url(value):
    value = (value or "").strip()
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("Ingrese una dirección web válida")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("No se pudo localizar el sitio") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("El sitio utiliza una dirección no permitida")
    return parsed._replace(fragment="").geturl()


def _fetch_resource(url, accepted=("html", "xml", "text"), timeout=20):
    request = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,text/plain;q=0.9,*/*;q=0.1",
    })
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "").lower()
        if accepted and not any(kind in content_type for kind in accepted):
            raise ValueError("El recurso no contiene contenido analizable")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(MAX_BYTES).decode(charset, errors="replace"), response.geturl(), content_type


def _fetch_page(url, timeout=20):
    raw, final_url, content_type = _fetch_resource(url, accepted=("html", "xhtml"), timeout=timeout)
    return raw, final_url, content_type


def _unique(values):
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _best_company_name(titles, host, structured_names=None):
    for candidate in structured_names or []:
        candidate = re.sub(r"\s+", " ", str(candidate)).strip()
        if 2 < len(candidate) < 120:
            return candidate
    for title in titles:
        candidate = re.split(r"[|–—•]", title)[0].strip(" -")
        if 2 < len(candidate) < 100 and candidate.lower() not in {"inicio", "home", "contacto", "bienvenidos"}:
            return candidate
    return host.removeprefix("www.").split(".")[0].replace("-", " ").title()


def _extract_address(text, structured_addresses=None):
    for value in structured_addresses or []:
        if value and len(value) >= 8:
            return re.sub(r"\s+", " ", value).strip(" .,-")[:300]
    patterns = [
        r"(?:dirección|direccion|ubicación|ubicacion|domicilio)\s*[:\-]?\s*([^\n|]{8,180})",
        r"((?:Av\.|Avenida|Ruta|Calle|Rúa|Rua|Km\.?\s*\d+)[^\n|]{5,180})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" .,-")[:300]
    return None


def _estimate_size(text, structured_employees=None):
    numeric = [int(value) for value in re.findall(r"(\d{2,6})\s+(?:empleados|colaboradores|funcionarios|trabajadores|personas)", text, re.I)]
    for value in structured_employees or []:
        try:
            numeric.append(int(re.sub(r"\D", "", str(value))))
        except ValueError:
            pass
    if numeric:
        amount = max(numeric)
        return "Grande" if amount >= 250 else "Mediana" if amount >= 50 else "Pequeña"
    lower = text.lower()
    if any(term in lower for term in ["multinacional", "más de 500", "mas de 500", "varias plantas", "sucursales en", "líder nacional", "lider nacional", "exportamos a"]):
        return "Grande (estimación por presencia operativa)"
    if any(term in lower for term in ["planta industrial", "centro de distribución", "fábrica", "fabrica", "frigorífico", "frigorifico", "exportamos", "complejo industrial"]):
        return "Mediana o grande (estimación por infraestructura)"
    return "No determinado"


def _link_priority(url, label=""):
    parsed = urlparse(url)
    haystack = f"{parsed.path} {parsed.query} {label}".lower()
    score = max((weight for term, weight in PRIORITY_PATH_TERMS.items() if term in haystack), default=20)
    depth_penalty = min(18, parsed.path.count("/") * 3)
    return score - depth_penalty


def _same_host(url, host):
    candidate = (urlparse(url).hostname or "").lower().removeprefix("www.")
    expected = (host or "").lower().removeprefix("www.")
    return candidate == expected


def _sitemap_urls(base_url, host, timeout=8):
    candidates = [urljoin(base_url, "/sitemap.xml"), urljoin(base_url, "/sitemap_index.xml")]
    found = []
    for sitemap_url in candidates:
        try:
            raw, _, _ = _fetch_resource(sitemap_url, accepted=("xml", "text"), timeout=timeout)
        except Exception:
            continue
        for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", raw, re.I | re.S):
            clean = html.unescape(re.sub(r"\s+", "", loc))
            if _same_host(clean, host) and clean not in found:
                found.append(clean)
            if len(found) >= MAX_SITEMAP_URLS:
                return found
        if found:
            break
    return found


def _flatten_jsonld(value, bucket):
    if isinstance(value, list):
        for item in value:
            _flatten_jsonld(item, bucket)
        return
    if not isinstance(value, dict):
        return
    kind = value.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    if any(item in {"Organization", "Corporation", "LocalBusiness", "Store", "Factory", "Place"} for item in kinds):
        if value.get("name"):
            bucket["names"].append(str(value["name"]))
        for key in ("email", "telephone"):
            if value.get(key):
                bucket[key].append(str(value[key]))
        address = value.get("address")
        if isinstance(address, dict):
            pieces = [address.get(key) for key in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
            formatted = ", ".join(str(piece) for piece in pieces if piece)
            if formatted:
                bucket["addresses"].append(formatted)
        elif address:
            bucket["addresses"].append(str(address))
        employees = value.get("numberOfEmployees")
        if isinstance(employees, dict):
            employees = employees.get("value") or employees.get("minValue")
        if employees:
            bucket["employees"].append(str(employees))
    for nested in value.values():
        if isinstance(nested, (dict, list)):
            _flatten_jsonld(nested, bucket)


def _extract_jsonld(raw):
    bucket = {"names": [], "email": [], "telephone": [], "addresses": [], "employees": []}
    blocks = re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", raw, re.I | re.S)
    for block in blocks[:20]:
        try:
            _flatten_jsonld(json.loads(html.unescape(block).strip()), bucket)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return bucket


def _project_signals(searchable):
    detected = []
    for label, terms in PROJECT_SIGNALS.items():
        if any(term in searchable for term in terms):
            detected.append(label)
    return detected


def _contact_names(text):
    names = []
    area_pattern = "|".join(map(re.escape, ROLE_AREAS))
    role_pattern = "|".join(map(re.escape, ROLE_TERMS))
    patterns = [
        rf"(?:{role_pattern})\s+(?:de\s+)?(?:{area_pattern})\s*[:\-–|]?\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.'-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.'-]+){{1,3}})",
        rf"([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.'-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.'-]+){{1,3}})\s*[|–-]\s*(?:{role_pattern})\s+(?:de\s+)?(?:{area_pattern})",
    ]
    for pattern in patterns:
        names.extend(match.group(1) for match in re.finditer(pattern, text, re.I))
    return _unique(names)[:12]


def _signal_excerpt(documents, terms):
    snippets = []
    for document in documents:
        sentences = re.split(r"(?<=[.!?])\s+|\n+", document)
        for sentence in sentences:
            lower = sentence.lower()
            if 35 <= len(sentence) <= 320 and any(term in lower for term in terms):
                snippets.append(re.sub(r"\s+", " ", sentence).strip())
    return _unique(snippets)[:6]


def normalize_website_url(url):
    return _normalize_url(url)


def analyze_website(url, max_pages=MAX_PAGES, use_sitemap=True, request_timeout=20, analysis=None, status="COMPLETED"):
    normalized = _normalize_url(url)
    parsed = urlparse(normalized)
    host = parsed.hostname
    queue = [(1000, normalized)]
    if use_sitemap:
        for candidate in _sitemap_urls(normalized, host, timeout=min(request_timeout, 8)):
            queue.append((_link_priority(candidate), candidate))
    seen, queued, documents, titles, all_links, raw_pages, meta_text = set(), {normalized}, [], [], [], [], []

    while queue and len(documents) < max_pages:
        queue.sort(key=lambda item: item[0], reverse=True)
        _, current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        try:
            raw, final_url, _ = _fetch_page(current, timeout=request_timeout)
        except Exception:
            if not documents:
                raise
            continue
        if not _same_host(final_url, host):
            continue
        parser = PageParser()
        parser.feed(raw)
        visible = "\n".join(parser.text)
        if visible.strip():
            documents.append(visible)
            raw_pages.append(raw)
        if parser.title.strip():
            titles.append(parser.title.strip())
        meta_text.extend(parser.meta)
        for href, label in parser.links:
            absolute = urljoin(final_url, href)
            link_parsed = urlparse(absolute)
            if link_parsed.scheme not in {"http", "https", "mailto", "tel"}:
                continue
            all_links.append(absolute)
            if link_parsed.scheme in {"http", "https"} and _same_host(absolute, host):
                clean = link_parsed._replace(fragment="").geturl()
                if clean not in seen and clean not in queued:
                    priority = _link_priority(clean, label)
                    if priority >= 55:
                        queue.append((priority, clean)); queued.add(clean)

    text = "\n".join(meta_text + documents)
    searchable = text.lower()
    structured = {"names": [], "email": [], "telephone": [], "addresses": [], "employees": []}
    for raw in raw_pages:
        data = _extract_jsonld(raw)
        for key in structured:
            structured[key].extend(data[key])

    mailto = [urlparse(link).path for link in all_links if link.lower().startswith("mailto:")]
    tel_links = [urlparse(link).path for link in all_links if link.lower().startswith("tel:")]
    emails = _unique(structured["email"] + mailto + re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, re.I))[:16]
    phones = _unique(structured["telephone"] + tel_links + re.findall(r"(?:\+?595[\s().-]*)?(?:0?\d{2,4}[\s().-]*)?\d{3}[\s.-]*\d{3,4}", text))
    phones = [re.sub(r"\s+", " ", phone).strip() for phone in phones if len(re.sub(r"\D", "", phone)) >= 7][:16]

    whatsapp_links = [link for link in all_links if "wa.me/" in link.lower() or "api.whatsapp.com" in link.lower() or "whatsapp.com/send" in link.lower()]
    whatsapp = None
    if whatsapp_links:
        number = re.search(r"(?:wa\.me/|phone=)(\+?\d+)", whatsapp_links[0])
        whatsapp = number.group(1) if number else whatsapp_links[0]

    contacts = _contact_names(text)
    social = {}
    for network in ["linkedin", "facebook", "instagram", "youtube"]:
        match = next((link for link in all_links if network + ".com" in link.lower()), None)
        if match:
            social[network] = match

    sector_scores = {sector: sum(searchable.count(term) for term in terms) for sector, terms in SECTORS.items()}
    sector = max(sector_scores, key=sector_scores.get)
    sector_strength = sector_scores[sector]
    if not sector_strength:
        sector = "Por validar"

    products = []
    matched_product_groups = 0
    for terms, matches in PRODUCT_RULES:
        if any(term in searchable for term in terms):
            products.extend(matches); matched_product_groups += 1
    products = _unique(products)
    project_signals = _project_signals(searchable)

    operational_terms = ["planta", "fábrica", "fabrica", "depósito", "deposito", "galpón", "galpon", "muelle", "hangar", "frigorífico", "frigorifico", "centro de distribución", "logística", "industrial", "nave industrial", "cámara fría", "camara fria"]
    operational_hits = sum(min(3, searchable.count(term)) for term in operational_terms)

    score, reasons = 0, []
    if operational_hits:
        points = min(26, 10 + operational_hits * 2)
        score += points; reasons.append(f"Infraestructura industrial detectada ({operational_hits} señales operativas)")
    if products:
        points = min(24, 8 + matched_product_groups * 5)
        score += points; reasons.append("Aplicaciones probables: " + ", ".join(products[:4]))
    if project_signals:
        points = min(26, 9 + len(project_signals) * 4)
        score += points; reasons.append("Señales de movimiento: " + ", ".join(project_signals[:5]))
    contact_channels = sum(bool(value) for value in (emails, phones, whatsapp))
    if contact_channels:
        score += 5 + contact_channels * 3; reasons.append(f"{contact_channels} tipo(s) de canal de contacto localizados")
    if contacts:
        score += 8; reasons.append("Posible decisor o responsable funcional identificado")
    if social.get("linkedin"):
        score += 3; reasons.append("Presencia corporativa en LinkedIn localizada")
    if sector in {"Frigorífico y cadena de frío", "Logística y distribución", "Industria y manufactura", "Aeronáutico", "Alimentos y bebidas", "Agronegocio"}:
        score += min(12, 7 + sector_strength); reasons.append(f"Alta afinidad sectorial: {sector}")
    if len(documents) >= 12:
        score += 5; reasons.append("Cobertura web profunda: 12+ páginas relevantes revisadas")
    elif len(documents) >= 6:
        score += 3; reasons.append("Cobertura web ampliada: múltiples páginas relevantes revisadas")

    score = min(100, score)
    level = "MUY ALTO" if score >= 85 else "ALTO" if score >= 68 else "MEDIO" if score >= 45 else "BAJO"
    services = ["Visita técnica y relevamiento"] if score >= 45 else ["Validación comercial inicial"]
    if products:
        services.extend(["Proyecto y suministro a medida", "Instalación y puesta en marcha"])
    if any(term in searchable for term in ["mantenimiento", "operación", "operacion", "planta", "fábrica", "fabrica", "frigorífico", "frigorifico"]):
        services.extend(["Mantenimiento preventivo y correctivo", "Repuestos multimarca y retrofit"])

    signal_terms = [term for terms in PROJECT_SIGNALS.values() for term in terms] + operational_terms
    excerpts = _signal_excerpt(documents, signal_terms)
    summary_parts = []
    if excerpts:
        summary_parts.append("Señales relevantes: " + " | ".join(excerpts[:4]))
    elif meta_text:
        summary_parts.append(" ".join(meta_text[:3]))
    summary_parts.append(f"Cobertura: {len(documents)} páginas relevantes analizadas de {len(seen)} URLs intentadas.")
    summary = " ".join(summary_parts)[:2200]

    if analysis is None:
        analysis = WebsiteAnalysis(tenant_id=current_tenant().id, url=normalized)
    analysis.url = normalized
    analysis.company_name = _best_company_name(titles, host, structured["names"])
    analysis.sector = sector
    analysis.address = _extract_address(text, structured["addresses"])
    analysis.phones = phones
    analysis.whatsapp = whatsapp
    analysis.emails = emails
    analysis.contacts = contacts
    analysis.social_links = social
    analysis.company_size = _estimate_size(text, structured["employees"])
    analysis.potential_score = score
    analysis.potential_level = level
    analysis.products = products
    analysis.services = _unique(services)
    analysis.reasons = reasons
    analysis.pages_analyzed = len(documents)
    analysis.summary = summary or "No se encontró texto público suficiente para una calificación profunda."
    analysis.status = status
    db.session.add(analysis)
    db.session.commit()
    return analysis
