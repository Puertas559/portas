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

USER_AGENT = os.getenv("RADAR_USER_AGENT", "IndustrialRevenueRadar/1.0")
MAX_BYTES = 1_500_000
MAX_PAGES = 6

SECTORS = {
    "Logística y distribución": ["logística", "logistica", "distribución", "distribucion", "depósito", "deposito", "almacén", "almacen", "transportadora"],
    "Alimentos y bebidas": ["alimentos", "bebidas", "lácteos", "lacteos", "molino", "panificadora", "supermercado", "producción alimentaria"],
    "Frigorífico y cadena de frío": ["frigorífico", "frigorifico", "frigorífica", "frigorifica", "refrigerado", "cámara fría", "cámaras frías", "camara fria", "camaras frias", "congelados", "cadena de frío"],
    "Industria y manufactura": ["industria", "industrial", "fábrica", "fabrica", "manufactura", "producción", "produccion", "metalúrgica", "metalurgica"],
    "Agronegocio": ["agro", "semillas", "granos", "silo", "cooperativa", "agricultura", "fertilizantes"],
    "Aeronáutico": ["aeronáutica", "aeronautica", "aeronave", "hangar", "aviación", "aviacion"],
    "Comercio de gran porte": ["shopping", "centro comercial", "retail", "hipermercado", "tienda", "importadora"],
    "Construcción e ingeniería": ["constructora", "construcción", "construccion", "ingeniería", "ingenieria", "arquitectura"],
}

PRODUCT_RULES = [
    (["muelle", "carga y descarga", "camiones", "centro de distribución", "logística", "depósito"], ["Puertas seccionales", "Niveladoras de docas", "Abrigos/sellos de docas"]),
    (["frigorífico", "frigorífica", "refrigerado", "cámara fría", "cámaras frías", "congelados", "cadena de frío"], ["Puertas rápidas frigoríficas", "Abrigos/sellos de docas", "Puertas seccionales"]),
    (["alto flujo", "línea de producción", "linea de produccion", "higiene", "alimentos", "farmacéutica"], ["Puertas rápidas de lona enrollables"]),
    (["hangar", "aeronave", "aviación", "gran formato"], ["Puertas de gran formato para hangares", "Puertas rápidas plegables"]),
    (["galpón", "galpon", "nave industrial", "fábrica", "fabrica", "planta industrial"], ["Puertas seccionales", "Puertas de acero enrollables", "Puertas rápidas plegables"]),
    (["seguridad contra incendios", "protección contra incendios", "cortafuego"], ["Puertas cortafuego bajo proyecto"]),
    (["shopping", "comercio", "local comercial", "estacionamiento"], ["Puertas de acero enrollables", "Automatización de accesos"]),
]


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.links = []
        self.title = ""
        self._in_title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and attrs.get("href"):
            self.links.append((attrs.get("href"), attrs.get("aria-label", "") + " " + attrs.get("title", "")))

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


def _fetch_page(url):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=18) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            raise ValueError("La dirección no contiene una página web")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(MAX_BYTES).decode(charset, errors="replace"), response.geturl()


def _unique(values):
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _best_company_name(titles, host):
    for title in titles:
        candidate = re.split(r"[|–—]", title)[0].strip(" -")
        if 2 < len(candidate) < 100 and candidate.lower() not in {"inicio", "home", "contacto"}:
            return candidate
    return host.removeprefix("www.").split(".")[0].replace("-", " ").title()


def _extract_address(text):
    patterns = [
        r"(?:dirección|direccion|ubicación|ubicacion|domicilio)\s*[:\-]?\s*([^\n|]{8,180})",
        r"((?:Av\.|Avenida|Ruta|Calle|Rúa|Rua)\s+[^\n|]{5,160})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" .,-")[:300]
    return None


def _estimate_size(text):
    numeric = [int(value) for value in re.findall(r"(\d{2,5})\s+(?:empleados|colaboradores|funcionarios|trabajadores)", text, re.I)]
    if numeric:
        amount = max(numeric)
        return "Grande" if amount >= 250 else "Mediana" if amount >= 50 else "Pequeña"
    if any(term in text.lower() for term in ["multinacional", "más de 500", "varias plantas", "sucursales en", "líder nacional"]):
        return "Grande (estimación por presencia operativa)"
    if any(term in text.lower() for term in ["planta industrial", "centro de distribución", "fábrica", "frigorífico", "exportamos"]):
        return "Mediana o grande (estimación por infraestructura)"
    return "No determinado"


def analyze_website(url):
    normalized = _normalize_url(url)
    parsed = urlparse(normalized)
    queue = [normalized]
    seen, documents, titles, all_links = set(), [], [], []
    useful_paths = ("contact", "contacto", "contato", "about", "nosotros", "empresa", "quienes", "ubicacion", "sucurs")
    while queue and len(documents) < MAX_PAGES:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        try:
            raw, final_url = _fetch_page(current)
        except Exception:
            if not documents:
                raise
            continue
        parser = PageParser()
        parser.feed(raw)
        page_text = "\n".join(parser.text)
        documents.append(page_text)
        if parser.title.strip():
            titles.append(parser.title.strip())
        for href, label in parser.links:
            absolute = urljoin(final_url, href)
            link_parsed = urlparse(absolute)
            if link_parsed.hostname == parsed.hostname:
                clean = link_parsed._replace(fragment="").geturl()
                if any(token in (link_parsed.path + " " + label).lower() for token in useful_paths) and clean not in seen:
                    queue.append(clean)
            all_links.append(absolute)

    text = "\n".join(documents)
    searchable = text.lower()
    emails = _unique(re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, re.I))[:12]
    phones = _unique(re.findall(r"(?:\+?595[\s().-]*)?(?:0?\d{2,4}[\s().-]*)?\d{3}[\s.-]*\d{3,4}", text))
    phones = [re.sub(r"\s+", " ", phone).strip() for phone in phones if len(re.sub(r"\D", "", phone)) >= 7][:12]
    whatsapp_links = [link for link in all_links if "wa.me/" in link or "api.whatsapp.com" in link]
    whatsapp = None
    if whatsapp_links:
        number = re.search(r"(?:wa\.me/|phone=)(\+?\d+)", whatsapp_links[0])
        whatsapp = number.group(1) if number else whatsapp_links[0]
    contacts = _unique(re.findall(r"(?:gerente|director(?:a)?|responsable|jefe|encargad[oa])(?:\s+(?:comercial|de compras|de mantenimiento|de operaciones))?\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.-]+){1,3})", text, re.I))[:8]
    social = {}
    for network in ["linkedin", "facebook", "instagram", "youtube"]:
        match = next((link for link in all_links if network + ".com" in link.lower()), None)
        if match:
            social[network] = match

    sector_scores = {sector: sum(searchable.count(term) for term in terms) for sector, terms in SECTORS.items()}
    sector = max(sector_scores, key=sector_scores.get)
    if not sector_scores[sector]:
        sector = "Por validar"
    products = []
    for terms, matches in PRODUCT_RULES:
        if any(term in searchable for term in terms):
            products.extend(matches)
    products = _unique(products)

    score, reasons = 0, []
    operational = ["planta", "fábrica", "fabrica", "depósito", "deposito", "galpón", "galpon", "muelle", "hangar", "frigorífico", "frigorifico", "centro de distribución", "logística", "industrial"]
    if any(term in searchable for term in operational):
        score += 35; reasons.append("Infraestructura operativa compatible con puertas automáticas")
    if products:
        score += min(28, 7 * len(products)); reasons.append("Aplicaciones concretas del portafolio identificadas")
    if any(term in searchable for term in ["expansión", "ampliación", "nueva planta", "construcción", "proyecto", "crecimiento"]):
        score += 15; reasons.append("Indicio de obra, expansión o necesidad técnica")
    if emails or phones or whatsapp:
        score += 12; reasons.append("Canales de contacto comercial encontrados")
    if contacts:
        score += 6; reasons.append("Posible responsable identificado")
    if sector in {"Frigorífico y cadena de frío", "Logística y distribución", "Industria y manufactura", "Aeronáutico", "Alimentos y bebidas", "Agronegocio"}:
        score += 10; reasons.append("Sector con alta afinidad para el portafolio")
    score = min(100, score)
    level = "MUY ALTO" if score >= 85 else "ALTO" if score >= 68 else "MEDIO" if score >= 45 else "BAJO"
    services = ["Visita técnica y relevamiento"] if score >= 45 else ["Validación comercial inicial"]
    if products:
        services.extend(["Proyecto y suministro a medida", "Instalación y puesta en marcha"])
    if any(term in searchable for term in ["mantenimiento", "operación", "planta", "fábrica", "frigorífico"]):
        services.extend(["Mantenimiento preventivo y correctivo", "Repuestos multimarca y retrofit"])

    analysis = WebsiteAnalysis(
        tenant_id=current_tenant().id,
        url=normalized, company_name=_best_company_name(titles, parsed.hostname), sector=sector,
        address=_extract_address(text), phones=phones, whatsapp=whatsapp, emails=emails, contacts=contacts,
        social_links=social, company_size=_estimate_size(text), potential_score=score, potential_level=level,
        products=products, services=_unique(services), reasons=reasons, pages_analyzed=len(documents),
        summary=(" ".join(text.split())[:700] or "No se encontró texto visible en el sitio."),
    )
    db.session.add(analysis)
    db.session.commit()
    return analysis
