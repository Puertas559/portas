import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "PuertasBrasilPY-CompanyFinder/1.0 (+https://puertasbrasil.com.py)"
SEARCH_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

INDUSTRIES = {
    "logistica": "centro logístico depósito transporte",
    "frigorifico": "frigorífico cámara fría alimentos",
    "manufactura": "industria fábrica manufactura",
    "alimentos": "industria de alimentos bebidas",
    "agro": "agroindustria silo cooperativa",
    "construccion": "constructora ingeniería industrial",
    "retail": "centro comercial supermercado",
    "aeronautica": "hangar aviación",
}

INDUSTRY_TERMS = {
    "logistica": ("logistic", "transport", "warehouse", "depósito", "deposito", "distribución", "distribucion"),
    "frigorifico": ("frigor", "cold", "slaughter", "meat", "carne", "lácte", "lacte"),
    "manufactura": ("industrial", "factory", "fábrica", "fabrica", "manufact", "metal", "production"),
    "alimentos": ("food", "alimento", "bebida", "drink", "brewery", "dairy", "molino"),
    "agro": ("agro", "grain", "silo", "seed", "semilla", "cooperativa", "fertiliz"),
    "construccion": ("construction", "construct", "ingenier", "architect", "building"),
    "retail": ("supermarket", "mall", "shopping", "retail", "hipermercado"),
    "aeronautica": ("aero", "aviation", "hangar", "aircraft"),
}


def _request_json(url, params=None, data=None):
    target = f"{url}?{urlencode(params)}" if params else url
    encoded = urlencode(data).encode("utf-8") if data else None
    request = Request(target, data=encoded, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=24) as response:
        return json.loads(response.read().decode("utf-8"))


def _nominatim_rows(place, limit=20):
    return _request_json(SEARCH_URL, {
        "q": place, "format": "jsonv2", "countrycodes": "py", "limit": limit,
        "addressdetails": 1, "extratags": 1, "namedetails": 1,
    })


def _from_nominatim(row, industry, city, region):
    extra = row.get("extratags") or {}
    address = row.get("address") or {}
    name = (row.get("namedetails") or {}).get("name") or row.get("name") or row.get("display_name", "").split(",")[0]
    website = extra.get("website") or extra.get("contact:website")
    phone = extra.get("phone") or extra.get("contact:phone")
    email = extra.get("email") or extra.get("contact:email")
    result_city = address.get("city") or address.get("town") or address.get("municipality") or city or "Por validar"
    result_region = address.get("state") or address.get("county") or region or "Por validar"
    score = 45 + (15 if website else 0) + (10 if phone else 0) + (10 if email else 0)
    return {
        "sourceId": f"osm-{row.get('osm_type')}-{row.get('osm_id')}", "company": name,
        "sector": industry or row.get("type") or "Por validar", "city": result_city,
        "region": result_region, "address": row.get("display_name"), "latitude": row.get("lat"),
        "longitude": row.get("lon"), "website": website, "phone": phone, "email": email,
        "linkedin": extra.get("contact:linkedin"), "score": min(score, 90), "source": "OpenStreetMap",
    }


def _overpass_rows(city, region, industry, query):
    places = _nominatim_rows(", ".join(value for value in (city, region, "Paraguay") if value), limit=1)
    if not places or not places[0].get("boundingbox"):
        return []
    south, north, west, east = places[0]["boundingbox"]
    bbox = f"{south},{west},{north},{east}"
    overpass = f'''[out:json][timeout:20];(
      nwr["name"]["industrial"]({bbox});
      nwr["name"]["office"~"company|logistics|construction"]({bbox});
      nwr["name"]["building"~"industrial|warehouse"]({bbox});
      nwr["name"]["craft"]({bbox});
      nwr["name"]["shop"~"wholesale|supermarket|hardware"]({bbox});
    );out center tags 100;'''
    payload = _request_json(OVERPASS_URL, data={"data": overpass})
    terms = tuple(term.lower() for term in INDUSTRY_TERMS.get(industry, ()))
    wanted = (query or "").lower().strip()
    results = []
    for element in payload.get("elements", []):
        tags = element.get("tags") or {}
        haystack = " ".join(str(value).lower() for value in tags.values())
        if wanted and wanted not in haystack:
            continue
        if terms and not any(term in haystack for term in terms):
            continue
        name = tags.get("name")
        if not name:
            continue
        center = element.get("center") or element
        address = " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])).strip()
        address = ", ".join(filter(None, [address, city, region, "Paraguay"]))
        website = tags.get("contact:website") or tags.get("website")
        phone = tags.get("contact:phone") or tags.get("phone")
        email = tags.get("contact:email") or tags.get("email")
        score = 55 + (15 if website else 0) + (10 if phone else 0) + (10 if email else 0)
        results.append({
            "sourceId": f"osm-{element.get('type')}-{element.get('id')}", "company": name,
            "sector": industry or tags.get("industrial") or tags.get("office") or "Por validar",
            "city": city or tags.get("addr:city") or "Por validar", "region": region or "Por validar",
            "address": address, "latitude": center.get("lat"), "longitude": center.get("lon"),
            "website": website, "phone": phone, "email": email, "linkedin": tags.get("contact:linkedin"),
            "score": min(score, 90), "source": "OpenStreetMap",
        })
    return results


def search_companies(query="", city="", region="", industry=""):
    focus = (query or INDUSTRIES.get(industry, industry)).strip()
    if not focus:
        raise ValueError("Ingrese una empresa o seleccione un tipo de industria")
    place = ", ".join(part.strip() for part in (focus, city, region, "Paraguay") if part and part.strip())
    rows = _nominatim_rows(place)
    results = [_from_nominatim(row, industry, city, region) for row in rows]
    if city or region:
        try:
            results.extend(_overpass_rows(city, region, industry, query))
        except Exception:
            pass
    unique = {}
    for result in results:
        key = result["company"].strip().lower()
        if key and key not in unique:
            unique[key] = result
    return sorted(unique.values(), key=lambda item: item["score"], reverse=True)[:40]
