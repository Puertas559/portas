import html
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError, URLError

from ..extensions import db
from ..models import WebsiteAnalysis
from ..tenant import current_tenant

USER_AGENT = os.getenv("RADAR_USER_AGENT", "PuertasBrasilRevenueRadar/2.1")


class SiteAnalysisError(Exception):
    def __init__(self, category, title, message, action, code=None, technical=None, alternatives=None, status=502):
        super().__init__(message)
        self.category = category
        self.title = title
        self.message = message
        self.action = action
        self.code = code or category
        self.technical = technical or {}
        self.alternatives = alternatives or []
        self.status = status

    def to_dict(self):
        return {
            "category": self.category, "title": self.title, "message": self.message,
            "action": self.action, "code": self.code, "technical": self.technical,
            "alternatives": self.alternatives,
        }


def _domain_stem(host):
    host = (host or "").lower().removeprefix("www.")
    parts = host.split(".")
    return parts[0] if parts else host


def _candidate_urls(value):
    raw = (value or "").strip()
    if not raw:
        return []
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not host:
        return []
    bare = host.removeprefix("www.")
    hosts = [host, bare, "www." + bare]
    if bare.endswith(".com.py"):
        hosts += [bare[:-3], "www." + bare[:-3]]
    elif bare.endswith(".com"):
        hosts += [bare + ".py", "www." + bare + ".py"]
    elif "." in bare and not bare.endswith(".py"):
        hosts += [bare + ".py", "www." + bare + ".py"]
    out=[]
    for h in hosts:
        for scheme in ("https", "http"):
            candidate=f"{scheme}://{h}{parsed.path or '/'}"
            if parsed.query:
                candidate += "?" + parsed.query
            if candidate not in out:
                out.append(candidate)
    return out[:12]


def _probe_url(candidate, timeout=5):
    started=time.monotonic()
    try:
        normalized=_normalize_url(candidate)
        raw, final_url, content_type=_fetch_resource(normalized, accepted=("html","xhtml","text"), timeout=timeout)
        elapsed=round((time.monotonic()-started)*1000)
        title=""
        try:
            parser=PageParser(); parser.feed(raw[:250000]); title=parser.title.strip()
        except Exception:
            pass
        return {"ok": True, "url": normalized, "finalUrl": final_url, "title": title[:160], "responseMs": elapsed, "contentType": content_type}
    except Exception as exc:
        return {"ok": False, "url": candidate, "error": str(exc)[:180]}


def discover_alternative_sites(value, timeout=4):
    alternatives=[]
    original_host=None
    try:
        raw=(value or "").strip()
        parsed=urlparse(raw if raw.startswith(("http://","https://")) else "https://"+raw)
        original_host=parsed.hostname
    except Exception:
        pass
    stem=_domain_stem(original_host)
    seen=set()
    for candidate in _candidate_urls(value):
        result=_probe_url(candidate, timeout=timeout)
        if not result.get("ok"):
            continue
        final=result.get("finalUrl") or result.get("url")
        final_host=urlparse(final).hostname or ""
        key=final.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        same_stem=bool(stem and stem in _domain_stem(final_host))
        confidence=92 if final_host == original_host else 84 if same_stem else 68
        reason="Mismo dominio con una variante accesible" if final_host == original_host else ("Dominio con nombre coincidente y respuesta válida" if same_stem else "Redirección válida detectada desde una variante del dominio")
        alternatives.append({
            "url": final, "host": final_host, "title": result.get("title"),
            "confidence": confidence, "reason": reason, "verified": True,
            "responseMs": result.get("responseMs"),
        })
    alternatives.sort(key=lambda x: (-x["confidence"], x.get("responseMs") or 99999))
    return alternatives[:6]


def classify_site_error(value, exc, stage="conexión inicial"):
    technical={"requestedUrl": value, "stage": stage, "exception": exc.__class__.__name__}
    alternatives=[]
    try:
        alternatives=discover_alternative_sites(value, timeout=3)
    except Exception:
        alternatives=[]
    if isinstance(exc, SiteAnalysisError):
        if alternatives and not exc.alternatives:
            exc.alternatives=alternatives
        return exc
    if isinstance(exc, HTTPError):
        technical["httpStatus"]=exc.code
        if exc.code in (401,403):
            return SiteAnalysisError("ACCESS_BLOCKED","Acceso bloqueado por el sitio",f"El servidor respondió con HTTP {exc.code} y rechazó la consulta automática.","Abra el sitio en el navegador. Si funciona, registre los datos disponibles manualmente o pruebe uno de los sitios alternativos detectados.",f"HTTP_{exc.code}",technical,alternatives,502)
        if exc.code == 404:
            return SiteAnalysisError("NOT_FOUND","Página o sitio no encontrado","El servidor respondió HTTP 404. La dirección puede haber cambiado o la página ya no existe.","Revise la dirección o pruebe un sitio alternativo relacionado.","HTTP_404",technical,alternatives,404)
        if exc.code >= 500:
            return SiteAnalysisError("REMOTE_SERVER_ERROR","El servidor de la empresa está con problemas",f"El sitio respondió HTTP {exc.code}.","Intente nuevamente más tarde o use un sitio alternativo verificado.",f"HTTP_{exc.code}",technical,alternatives,502)
        return SiteAnalysisError("HTTP_ERROR","El sitio respondió con un error",f"El servidor devolvió HTTP {exc.code}.","Revise el sitio en el navegador y vuelva a intentar.",f"HTTP_{exc.code}",technical,alternatives,502)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return SiteAnalysisError("TIMEOUT","Tiempo de espera agotado","El sitio tardó demasiado en responder y el radar interrumpió la consulta para no bloquear su trabajo.","Verifique si el sitio abre normalmente o intente nuevamente en unos minutos.","TIMEOUT",technical,alternatives,504)
    if isinstance(exc, ssl.SSLError):
        return SiteAnalysisError("SSL_ERROR","Problema de seguridad HTTPS","No fue posible establecer una conexión HTTPS válida con el sitio.","Abra el sitio en el navegador o pruebe una variante HTTP/HTTPS sugerida.","SSL_ERROR",technical,alternatives,502)
    if isinstance(exc, URLError):
        reason=getattr(exc,"reason",None)
        if isinstance(reason, socket.gaierror):
            return SiteAnalysisError("DNS_ERROR","Dominio no localizado","No fue posible localizar el dominio en Internet. Puede estar escrito incorrectamente, haber cambiado o estar fuera de servicio.","Revise el dominio o pruebe una de las alternativas detectadas.","DNS_ERROR",technical,alternatives,404)
        return SiteAnalysisError("CONNECTION_ERROR","No fue posible conectar con el sitio",f"La conexión con el servidor falló: {str(reason or exc)[:160]}.","Compruebe si el sitio abre en el navegador y vuelva a intentar.","CONNECTION_ERROR",technical,alternatives,502)
    if isinstance(exc, ValueError):
        msg=str(exc)
        category="INVALID_URL" if "válida" in msg.lower() else "SITE_VALIDATION_ERROR"
        title="Dirección web no válida" if category=="INVALID_URL" else "No fue posible validar el sitio"
        action="Corrija la dirección e intente nuevamente." if category=="INVALID_URL" else "Revise la dirección o pruebe uno de los sitios alternativos detectados."
        return SiteAnalysisError(category,title,msg,action,category,technical,alternatives,400)
    return SiteAnalysisError("UNKNOWN_ERROR","No fue posible completar el análisis","Ocurrió un problema técnico no esperado durante el análisis del sitio.","Intente nuevamente. Si se repite, abra los detalles técnicos y registre el código del error.","ANALYZER_ERROR",technical,alternatives,502)
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
        self.site_names = []
        self.canonical = None
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
        if tag == "link" and "canonical" in (attrs.get("rel") or "").lower() and attrs.get("href"):
            self.canonical = attrs.get("href")
        if tag == "meta" and attrs.get("content"):
            key = (attrs.get("name") or attrs.get("property") or "").lower()
            if key in {"description", "og:description", "og:title", "twitter:description", "twitter:title"}:
                self.meta.append(attrs.get("content"))
            if key in {"og:site_name", "application-name", "apple-mobile-web-app-title"}:
                self.site_names.append(attrs.get("content"))

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
    if not parsed.hostname or parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise SiteAnalysisError("INVALID_URL", "Dirección web no válida", "La dirección ingresada no tiene un dominio web válido.", "Corrija la dirección e intente nuevamente. Ejemplo: https://empresa.com.py", "INVALID_URL", {"requestedUrl": value, "stage": "validación de la dirección"}, status=400)
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise SiteAnalysisError("INVALID_URL", "Dirección web no válida", "El puerto indicado no es válido.", "Utilice un sitio HTTP o HTTPS público.", status=400) from exc
    if port not in {80, 443}:
        raise SiteAnalysisError("PORT_NOT_ALLOWED", "Puerto no permitido", "El analizador solo puede acceder a sitios web públicos en los puertos 80 y 443.", "Utilice la dirección pública normal del sitio.", status=400)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise SiteAnalysisError("DNS_ERROR", "Dominio no localizado", "No fue posible localizar el dominio en Internet. Puede estar escrito incorrectamente, haber cambiado o estar fuera de servicio.", "Revise el dominio o utilice la búsqueda de sitios relacionados.", "DNS_ERROR", {"requestedUrl": value, "host": parsed.hostname, "stage": "resolución DNS"}, status=404) from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise SiteAnalysisError("PRIVATE_ADDRESS", "Dirección no permitida", "El dominio apunta a una dirección privada o no pública y no puede ser analizado por seguridad.", "Utilice el sitio web público de la empresa.", "PRIVATE_ADDRESS", {"requestedUrl": value, "host": parsed.hostname}, status=400)
    return parsed._replace(fragment="").geturl()


class _PublicRedirectHandler(HTTPRedirectHandler):
    """Revalidate every redirect before urllib follows it."""

    def __init__(self, max_redirects=5):
        super().__init__()
        self.redirects = 0
        self.max_redirects = max_redirects

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirects += 1
        if self.redirects > self.max_redirects:
            raise SiteAnalysisError("TOO_MANY_REDIRECTS", "Demasiadas redirecciones", "El sitio superó el límite seguro de redirecciones.", "Utilice la dirección final del sitio.", status=422)
        safe_url = _normalize_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, safe_url)


def _fetch_resource(url, accepted=("html", "xml", "text"), timeout=20):
    safe_url = _normalize_url(url)
    request = Request(safe_url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,text/plain;q=0.9,*/*;q=0.1",
    })
    with build_opener(_PublicRedirectHandler()).open(request, timeout=timeout) as response:
        final_url = _normalize_url(response.geturl())
        content_type = response.headers.get("Content-Type", "").lower()
        if accepted and not any(kind in content_type for kind in accepted):
            raise ValueError("El recurso no contiene contenido analizable")
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read(MAX_BYTES).decode(charset, errors="replace"), final_url, content_type


def _fetch_page(url, timeout=20):
    raw, final_url, content_type = _fetch_resource(url, accepted=("html", "xhtml"), timeout=timeout)
    return raw, final_url, content_type


def _unique(values):
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _best_company_name(titles, host, structured_names=None, site_names=None):
    generic={
        "inicio","home","contacto","contact","contato","nosotros","quienes somos","quiénes somos",
        "nuestra historia","historia","about us","empresa","productos","servicios","sucursales","ubicaciones",
        "trabaja con nosotros","blog","noticias","news","bienvenidos","bienvenido"
    }
    def clean(value):
        value=re.sub(r"\s+"," ",str(value or "")).strip(" -|–—•·:")
        value=re.sub(r"^(?:contacto|contact|inicio|home|nuestra historia|historia|nosotros|quienes somos|quiénes somos)\s*[-|–—•·:]+\s*","",value,flags=re.I)
        return value.strip(" -|–—•·:")
    # Organization/LocalBusiness JSON-LD is the strongest public signal.
    for candidate in structured_names or []:
        candidate=clean(candidate)
        if 2 < len(candidate) < 120 and candidate.casefold() not in generic:
            return candidate
    # og:site_name / application-name usually represents the brand, independently of the page path.
    for candidate in site_names or []:
        candidate=clean(candidate)
        if 2 < len(candidate) < 120 and candidate.casefold() not in generic:
            return candidate
    stem=host.removeprefix("www.").split(".")[0].replace("-","").replace("_","").casefold()
    candidates=[]
    for title in titles:
        parts=[clean(x) for x in re.split(r"[|–—•·]",title) if clean(x)]
        for idx,candidate in enumerate(parts):
            low=candidate.casefold()
            if not (2 < len(candidate) < 100) or low in generic:
                continue
            compact=re.sub(r"[^a-z0-9]","",low)
            score=10
            if stem and (stem in compact or compact in stem): score+=45
            if idx==len(parts)-1: score+=10  # brand is commonly the title suffix
            if any(word in low for word in ("contacto","historia","producto","servicio","sucursal","inicio")): score-=25
            candidates.append((score,candidate))
    if candidates:
        candidates.sort(key=lambda x:(-x[0],len(x[1])))
        return candidates[0][1]
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
        if value.get("legalName"):
            bucket["legal_names"].append(str(value["legalName"]))
        if value.get("foundingDate"):
            bucket["founding_dates"].append(str(value["foundingDate"]))
        founder = value.get("founder") or value.get("founders")
        if founder:
            items = founder if isinstance(founder, list) else [founder]
            for item in items:
                if isinstance(item, dict) and item.get("name"):
                    bucket["founders"].append(str(item["name"]))
                elif isinstance(item, str):
                    bucket["founders"].append(item)
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
    bucket = {"names": [], "legal_names": [], "email": [], "telephone": [], "addresses": [], "employees": [], "founding_dates": [], "founders": []}
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



def _extract_ruc(text):
    patterns = [
        r"(?:RUC|Registro\s+Único\s+de\s+Contribuyentes|Registro\s+Unico\s+de\s+Contribuyentes)\s*(?:N[°ºo.]?\s*)?[:#\-]?\s*(\d{5,10}(?:\s*[-–]\s*\d)?)",
        r"\b(\d{7,9}-\d)\b",
    ]
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, re.I)
        if match:
            value = re.sub(r"\s+", "", match.group(1)).replace("–", "-")
            return value, (94 if index == 0 else 72)
    return None, 0


def _extract_legal_name(text, structured_legal=None, fallback=None):
    for candidate in structured_legal or []:
        candidate = re.sub(r"\s+", " ", str(candidate)).strip()
        if 3 < len(candidate) < 180:
            return candidate, 94
    patterns = [
        r"(?:raz[oó]n\s+social|denominaci[oó]n\s+social|nombre\s+legal)\s*[:\-]?\s*([^\n|]{3,180})",
        r"\b([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 .,&'\-]{2,130}\s+(?:S\.A\.E\.C\.A\.|S\.A\.E\.|S\.A\.|S\.R\.L\.|S\.A\.S\.|LTDA\.?|SOCIEDAD\s+AN[ÓO]NIMA))\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip(" .,-")
            if 3 < len(value) < 180:
                return value, 84
    return (fallback, 55) if fallback else (None, 0)


def _extract_founded_year(text, structured_dates=None):
    for value in structured_dates or []:
        match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", str(value))
        if match:
            return int(match.group(1)), 92
    patterns = [
        r"(?:fundad[ao]|fundaci[oó]n|desde|establecid[ao]|iniciamos\s+(?:en|nuestras\s+actividades\s+en))\s*(?:en\s*)?(18\d{2}|19\d{2}|20\d{2})",
        r"(?:desde\s+el\s+año|desde\s+el\s+ano)\s+(18\d{2}|19\d{2}|20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1)), 78
    return None, 0


def _extract_owners(text, structured_founders=None):
    results = [(re.sub(r"\s+", " ", str(v)).strip(), 88, "Fundador informado en datos estructurados") for v in (structured_founders or []) if v]
    patterns = [
        (r"(?:fundador(?:a)?|propietario(?:a)?|dueñ[oa]|accionista\s+principal|socio\s+fundador)\s*[:\-–]?\s*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.'-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ.'-]+){1,4})", 74),
    ]
    for pattern, confidence in patterns:
        for match in re.finditer(pattern, text, re.I):
            results.append((re.sub(r"\s+", " ", match.group(1)).strip(), confidence, "Mención societaria o fundacional en el sitio"))
    unique=[]; seen=set()
    for name, confidence, reason in results:
        key=name.casefold()
        if key in seen or len(name) < 4:
            continue
        seen.add(key); unique.append({"name": name, "confidence": confidence, "reason": reason})
    return unique[:10]


def _extract_operation_plants(documents):
    terms=("planta", "fábrica", "fabrica", "centro de distribución", "centro de distribucion", "sucursal", "unidad", "complejo industrial", "depósito", "deposito", "frigorífico", "frigorifico")
    rows=[]
    for document in documents:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", document):
            clean=re.sub(r"\s+", " ", sentence).strip()
            low=clean.lower()
            if 25 <= len(clean) <= 260 and any(t in low for t in terms) and any(k in low for k in ("ubic", "km", "ruta", "ciudad", "paraguay", "departamento", "dirección", "direccion", "opera", "contamos", "nuestra")):
                rows.append(clean)
    return _unique(rows)[:12]


def _extract_key_activities(text, sector):
    lower=text.lower(); rows=[]
    lexicon={
        "fabricación": ["fabricamos", "fabricación", "fabricacion", "manufactura", "producción", "produccion"],
        "logística y distribución": ["logística", "logistica", "distribución", "distribucion", "centro de distribución", "depósito", "deposito"],
        "procesamiento de alimentos": ["procesamiento", "alimentos", "frigorífico", "frigorifico", "lácteos", "lacteos", "bebidas"],
        "agronegocio": ["granos", "semillas", "fertilizantes", "acopio", "agroindustrial", "agricultura"],
        "construcción e ingeniería": ["constructora", "ingeniería", "ingenieria", "obra", "estructura metálica", "estructura metalica"],
        "comercio y distribución": ["supermercado", "retail", "importación", "importacion", "comercialización", "comercializacion"],
    }
    for label, terms in lexicon.items():
        if any(term in lower for term in terms):
            rows.append(label)
    if sector and sector != "Por validar":
        rows.insert(0, sector)
    return _unique(rows)[:10]


def _extract_location_from_address(address):
    if not address:
        return None, None
    text=address.lower()
    departments={
        "Alto Paraná": ["ciudad del este", "hernandarias", "minga guazú", "minga guazu", "presidente franco", "santa rita", "san alberto", "naranjal"],
        "Central": ["san lorenzo", "luque", "capiatá", "capiata", "mariano roque alonso", "fernando de la mora", "lambaré", "lambare", "limpio", "villa elisa"],
        "Asunción": ["asunción", "asuncion"],
        "Itapúa": ["encarnación", "encarnacion", "hohenau", "obligado", "bella vista"],
        "Caaguazú": ["caaguazú", "caaguazu", "coronel oviedo"],
        "Canindeyú": ["salto del guairá", "salto del guaira", "katueté", "katuete"],
    }
    for department, cities in departments.items():
        for city in cities:
            if city in text:
                return city.title(), department
    return None, None


def _build_enrichment(text, documents, structured, company_name, sector, address, social, products, normalized, host):
    ruc, ruc_conf = _extract_ruc(text)
    legal, legal_conf = _extract_legal_name(text, structured.get("legal_names"), company_name)
    year, year_conf = _extract_founded_year(text, structured.get("founding_dates"))
    owners = _extract_owners(text, structured.get("founders"))
    plants = _extract_operation_plants(documents)
    activities = _extract_key_activities(text, sector)
    city, department = _extract_location_from_address(address)
    field_confidence = {
        "legalName": legal_conf, "ruc": ruc_conf, "foundedYear": year_conf,
        "address": 86 if address else 0, "sector": 82 if sector and sector != "Por validar" else 0,
        "companySize": 65, "owners": max([x["confidence"] for x in owners], default=0),
        "operationPlants": 72 if plants else 0, "keyActivities": 76 if activities else 0,
        "website": 95, "socialLinks": 88 if social else 0,
    }
    review_required=[key for key,val in field_confidence.items() if val and val < 80]
    return {
        "legalName": legal, "ruc": ruc, "foundedYear": year,
        "owners": owners, "operationPlants": plants, "keyActivities": activities,
        "city": city, "department": department, "address": address,
        "products": products or [], "socialLinks": social or {},
        "officialWebsite": normalized, "domain": host,
        "fieldConfidence": field_confidence, "reviewRequired": review_required,
        "sourceUrl": normalized,
    }

def normalize_website_url(url):
    return _normalize_url(url)


def analyze_website(url, max_pages=MAX_PAGES, use_sitemap=True, request_timeout=20, analysis=None, status="COMPLETED"):
    requested_url = url
    try:
        normalized = _normalize_url(url)
    except Exception as exc:
        raise classify_site_error(url, exc, "validación de la dirección") from exc
    parsed = urlparse(normalized)
    host = parsed.hostname
    queue = [(1000, normalized)]
    if use_sitemap:
        for candidate in _sitemap_urls(normalized, host, timeout=min(request_timeout, 8)):
            queue.append((_link_priority(candidate), candidate))
    seen, queued, documents, titles, site_names, all_links, raw_pages, meta_text = set(), {normalized}, [], [], [], [], [], []
    canonical_urls, redirects, fetch_errors = [], [], []

    while queue and len(documents) < max_pages:
        queue.sort(key=lambda item: item[0], reverse=True)
        _, current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        try:
            raw, final_url, _ = _fetch_page(current, timeout=request_timeout)
        except Exception as exc:
            fetch_errors.append({"url": current, "error": str(exc)[:160], "type": exc.__class__.__name__})
            if not documents:
                raise classify_site_error(requested_url, exc, "descarga de la página principal") from exc
            continue
        if urlparse(final_url).hostname != urlparse(current).hostname:
            redirects.append(final_url)
        if not _same_host(final_url, host):
            if not documents and current == normalized:
                # A redirección corporativa a otro dominio puede ser el sitio oficial vigente.
                normalized = final_url
                host = urlparse(final_url).hostname
                queued.add(final_url)
            else:
                continue
        parser = PageParser()
        parser.feed(raw)
        if parser.canonical:
            canonical_urls.append(urljoin(final_url, parser.canonical))
        visible = "\n".join(parser.text)
        if visible.strip():
            documents.append(visible)
            raw_pages.append(raw)
        if parser.title.strip():
            titles.append(parser.title.strip())
        meta_text.extend(parser.meta)
        site_names.extend(parser.site_names)
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
    structured = {"names": [], "legal_names": [], "email": [], "telephone": [], "addresses": [], "employees": [], "founding_dates": [], "founders": []}
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

    alternative_sites = []
    for alt in _unique(redirects + canonical_urls):
        alt_host = urlparse(alt).hostname or ""
        if alt_host and alt_host != host:
            alternative_sites.append({"url": alt, "host": alt_host, "confidence": 90 if _domain_stem(alt_host) == _domain_stem(host) else 76, "reason": "Redirección o URL canónica detectada por el sitio", "verified": True})
    enrichment = _build_enrichment(text, documents, structured, analysis.company_name if analysis and analysis.company_name else _best_company_name(titles, host, structured["names"], site_names), sector, _extract_address(text, structured["addresses"]), social, products, normalized, host)
    diagnostics = {
        "requestedUrl": requested_url, "resolvedUrl": normalized, "host": host,
        "pagesAnalyzed": len(documents), "urlsAttempted": len(seen), "fetchErrors": fetch_errors[:12],
        "enrichment": enrichment,
    }
    if analysis is None:
        analysis = WebsiteAnalysis(tenant_id=current_tenant().id, url=normalized)
    analysis.url = normalized
    analysis.company_name = _best_company_name(titles, host, structured["names"], site_names)
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
    analysis.alternative_sites = alternative_sites
    analysis.diagnostics = diagnostics
    db.session.add(analysis)
    db.session.commit()
    return analysis
