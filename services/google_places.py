import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .company_search import search_companies

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.types",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.businessStatus",
    "places.rating",
    "places.userRatingCount",
    "places.googleMapsUri",
    "nextPageToken",
])

EXPANSIONS = {
    "industria": [
        "industria", "fabrica", "planta industrial", "manufactura", "maquila", "parque industrial",
        "metalurgica", "metalmecanica", "acero", "aluminio", "plasticos", "envases", "embalajes",
        "carton", "papel", "madera", "muebles", "textil", "confecciones", "calzados", "quimica",
        "farmaceutica", "laboratorio", "alimentos", "bebidas", "lacteos", "molino", "panificadora",
        "agroindustria", "frigorifico", "procesadora", "deposito", "almacen", "centro logistico",
        "centro de distribucion", "galpon industrial", "taller industrial", "importadora mayorista",
    ],
    "logistica": [
        "centro logistico", "centro de distribucion", "deposito", "almacen", "transportadora",
        "operador logistico", "terminal de cargas", "logistica", "cross docking", "distribuidora",
        "importadora", "mayorista", "courier", "carga internacional", "puerto seco",
    ],
    "frigorifico": [
        "frigorifico", "camara frigorifica", "cadena de frio", "planta procesadora de carne",
        "industria carnica", "matadero", "alimentos congelados", "deposito refrigerado", "lacteos",
        "helados", "pescados", "aves", "chacinados", "camara fria",
    ],
    "agro": [
        "agroindustria", "silo", "acopio de granos", "cooperativa agricola", "procesadora de granos",
        "semillas", "fertilizantes", "alimentos balanceados", "molino", "aceitera", "yerbatera",
        "arrocera", "secadero", "cerealera", "agropecuaria", "insumos agricolas",
    ],
    "construccion": [
        "constructora", "ingenieria industrial", "estructuras metalicas", "tinglados", "galpones",
        "parque industrial", "desarrolladora industrial", "arquitectura industrial", "hormigon",
        "prefabricados", "materiales de construccion", "montajes industriales",
    ],
    "retail": [
        "supermercado", "hipermercado", "shopping", "centro comercial", "mayorista", "distribuidora",
        "home center", "ferreteria industrial", "concesionaria", "estacion de servicio",
    ],
    "aeronautica": [
        "hangar", "aeropuerto", "aviacion", "mantenimiento aeronautico", "aeroclub", "terminal aerea",
    ],
}

REGION_LOCATIONS = {
    "alto parana": [
        "Ciudad del Este", "Hernandarias", "Minga Guazu", "Presidente Franco", "Santa Rita",
        "Naranjal", "Santa Rosa del Monday", "San Alberto", "Juan Leon Mallorquin", "Itakyry",
    ],
    "central": [
        "Asuncion", "San Lorenzo", "Luque", "Mariano Roque Alonso", "Fernando de la Mora",
        "Capiata", "Lambare", "Limpio", "Villa Elisa", "Nemby", "Ypane", "Villeta",
    ],
    "itapua": ["Encarnacion", "Cambyreta", "Hohenau", "Obligado", "Bella Vista", "Capitan Miranda", "Fram"],
    "caaguazu": ["Caaguazu", "Coronel Oviedo", "J. Eulogio Estigarribia", "Doctor Juan Manuel Frutos"],
    "presidente hayes": ["Villa Hayes", "Benjamin Aceval", "Nanawa", "Jose Falcon"],
    "amambay": ["Pedro Juan Caballero", "Capitan Bado", "Bella Vista Norte"],
    "concepcion": ["Concepcion", "Horqueta", "Yby Yau"],
    "paraguari": ["Paraguari", "Carapegua", "Yaguaron", "Quiindy"],
    "cordillera": ["Caacupe", "Tobati", "Eusebio Ayala", "San Bernardino"],
    "san pedro": ["San Pedro de Ycuamandiyu", "Santa Rosa del Aguaray", "San Estanislao", "Guayaibi"],
}

PARAGUAY_INDUSTRIAL_CENTERS = [
    "Ciudad del Este", "Hernandarias", "Minga Guazu", "Santa Rita", "Asuncion", "San Lorenzo",
    "Mariano Roque Alonso", "Luque", "Capiata", "Villeta", "Encarnacion", "Hohenau",
    "Coronel Oviedo", "Caaguazu", "Villa Hayes", "Pedro Juan Caballero", "Concepcion",
]

DEPTH_CONFIG = {
    "quick": {"terms": 5, "pages": 1, "jobs": 5},
    "deep": {"terms": 14, "pages": 2, "jobs": 24},
    "territorial": {"terms": 28, "pages": 2, "jobs": 64},
}


def _normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", value.lower()).strip()


def _terms(query, industry, depth):
    base = _normalize(query)
    key = _normalize(industry)
    options = []
    for candidate in [base, key]:
        if candidate:
            options.append(candidate)
            options.extend(EXPANSIONS.get(candidate, []))
            for expansion_key, values in EXPANSIONS.items():
                if candidate in expansion_key or expansion_key in candidate:
                    options.extend(values)
    if not options:
        options = EXPANSIONS["industria"][:]
    if base and any(word in base for word in ("industr", "fabr", "planta", "manufact", "empresa")):
        options.extend(EXPANSIONS["industria"])
    seen, deduped = set(), []
    for item in options:
        norm = _normalize(item)
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(item)
    return deduped[:DEPTH_CONFIG.get(depth, DEPTH_CONFIG["deep"])["terms"]]


def _locations(city, region, depth):
    if city:
        # In territorial mode search both the requested city and nearby/department poles.
        rows = [city]
        if depth == "territorial" and region:
            rows.extend(REGION_LOCATIONS.get(_normalize(region), []))
    elif region:
        rows = REGION_LOCATIONS.get(_normalize(region), [region]) if depth == "territorial" else [region]
    else:
        rows = PARAGUAY_INDUSTRIAL_CENTERS if depth == "territorial" else ["Paraguay"]
    seen, output = set(), []
    for row in rows:
        key = _normalize(row)
        if key and key not in seen:
            seen.add(key)
            output.append(row)
    return output


def _jobs(terms, locations, depth):
    config = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["deep"])
    jobs = []
    # First guarantee broad semantic coverage in the main locality.
    primary = locations[0] if locations else "Paraguay"
    for term in terms:
        jobs.append((term, primary))
    # Then spread the strongest terms across other poles to beat ranking saturation.
    strong_terms = terms[: min(12, len(terms))]
    for location in locations[1:]:
        for term in strong_terms:
            jobs.append((term, location))
    return jobs[:config["jobs"]]


def _post_places(api_key, payload):
    body = json.dumps(payload).encode("utf-8")
    request = Request(TEXT_SEARCH_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    })
    try:
        with urlopen(request, timeout=14) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Google Places respondió {exc.code}: {detail[:300]}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("No se pudo conectar con Google Places") from exc


def _format_place(place, matched_term, matched_location):
    display = place.get("displayName") or {}
    primary_type = place.get("primaryTypeDisplayName") or {}
    location = place.get("location") or {}
    phone = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber")
    website = place.get("websiteUri")
    reviews = place.get("userRatingCount") or 0
    rating = place.get("rating") or 0
    contact_score = (45 if phone else 0) + (40 if website else 0) + (15 if reviews else 0)
    commercial_score = min(100, 40 + (18 if website else 0) + (16 if phone else 0) + min(16, reviews // 20) + min(10, int(rating * 2)))
    return {
        "placeId": place.get("id"),
        "sourceId": f"gplace:{place.get('id')}" if place.get("id") else None,
        "company": display.get("text") or "Empresa sin nombre",
        "address": place.get("formattedAddress"),
        "lat": location.get("latitude"),
        "lng": location.get("longitude"),
        "types": place.get("types") or [],
        "primaryType": primary_type.get("text") or place.get("primaryType"),
        "website": website,
        "phone": phone,
        "rating": place.get("rating"),
        "reviews": reviews,
        "mapsUrl": place.get("googleMapsUri"),
        "businessStatus": place.get("businessStatus"),
        "matchedTerm": matched_term,
        "matchedTerms": [matched_term],
        "matchedLocation": matched_location,
        "source": "Google Places",
        "contactScore": contact_score,
        "commercialScore": commercial_score,
    }


def _format_osm(row):
    source_id = row.get("sourceId") or "osm:" + _normalize(row.get("company"))
    return {
        "placeId": source_id,
        "sourceId": source_id,
        "company": row.get("company"),
        "address": row.get("address"),
        "lat": row.get("latitude"),
        "lng": row.get("longitude"),
        "types": [row.get("sector")] if row.get("sector") else [],
        "primaryType": row.get("sector") or "Empresa",
        "website": row.get("website"),
        "phone": row.get("phone"),
        "email": row.get("email"),
        "rating": None,
        "reviews": 0,
        "mapsUrl": None,
        "businessStatus": None,
        "matchedTerm": "fuente geográfica complementaria",
        "matchedTerms": ["fuente geográfica complementaria"],
        "matchedLocation": row.get("city") or row.get("region"),
        "source": "OpenStreetMap",
        "contactScore": (40 if row.get("phone") else 0) + (35 if row.get("website") else 0) + (25 if row.get("email") else 0),
        "commercialScore": row.get("score") or 45,
    }


def _dedupe_key(row):
    name = re.sub(r"[^a-z0-9]+", "", _normalize(row.get("company")))
    address = re.sub(r"[^a-z0-9]+", "", _normalize(row.get("address")))[:60]
    return f"{name}|{address}" if address else name


def search_places(query="", city="", region="", industry="", depth="deep"):
    depth = depth if depth in DEPTH_CONFIG else "deep"
    api_key = os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    terms = _terms(query, industry, depth)
    locations = _locations(city, region, depth)
    jobs = _jobs(terms, locations, depth)
    page_limit = DEPTH_CONFIG[depth]["pages"]
    max_calls = max(1, int(os.getenv("GOOGLE_PLACES_MAX_CALLS", "120")))

    found, errors, calls = {}, [], 0
    providers = []

    if api_key:
        providers.append("Google Places")

        def search_job(term, locality):
            rows, local_errors, local_calls = [], [], 0
            page_token = None
            for _page in range(page_limit):
                payload = {
                    "textQuery": f"{term} en {locality}, Paraguay",
                    "languageCode": "es",
                    "regionCode": "PY",
                    "pageSize": 20,
                }
                if page_token:
                    payload["pageToken"] = page_token
                try:
                    data = _post_places(api_key, payload)
                    local_calls += 1
                except RuntimeError as exc:
                    local_errors.append(str(exc))
                    break
                rows.extend(_format_place(place, term, locality) for place in data.get("places", []))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
            return rows, local_calls, local_errors

        # Cap the number of jobs so a territorial scan cannot explode billing.
        allowed_jobs = jobs[: max(1, max_calls // page_limit)]
        workers = min(8, max(1, len(allowed_jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(search_job, term, locality) for term, locality in allowed_jobs]
            for future in as_completed(futures):
                rows, local_calls, local_errors = future.result()
                calls += local_calls
                errors.extend(local_errors)
                for row in rows:
                    pid = row.get("placeId")
                    if not pid:
                        continue
                    if pid in found:
                        existing = found[pid]
                        term = row.get("matchedTerm")
                        if term and term not in existing["matchedTerms"]:
                            existing["matchedTerms"].append(term)
                        existing["commercialScore"] = max(existing.get("commercialScore") or 0, row.get("commercialScore") or 0)
                    else:
                        found[pid] = row

    # Complementary public geographic discovery. One bounded search keeps this useful without hammering OSM.
    try:
        osm_rows = search_companies(query=query, city=city, region=region, industry=industry or "manufactura")
        if osm_rows:
            providers.append("OpenStreetMap")
        google_keys = {_dedupe_key(row) for row in found.values()}
        for raw in osm_rows:
            row = _format_osm(raw)
            key = _dedupe_key(row)
            if not key or key in google_keys:
                continue
            found[row["placeId"]] = row
    except Exception as exc:
        errors.append(f"Fuente geográfica complementaria: {str(exc)[:160]}")

    if not found and not api_key:
        raise ValueError("No se encontraron empresas con la fuente pública. Para máxima cobertura, configure GOOGLE_PLACES_API_KEY.")

    results = list(found.values())
    results.sort(
        key=lambda row: (
            row.get("commercialScore") or 0,
            row.get("contactScore") or 0,
            bool(row.get("website")),
            bool(row.get("phone")),
            row.get("reviews") or 0,
            row.get("rating") or 0,
        ),
        reverse=True,
    )
    return {
        "results": results,
        "count": len(results),
        "queries": terms,
        "locations": locations,
        "jobs": len(jobs),
        "calls": calls,
        "depth": depth,
        "providers": providers,
        "googleEnabled": bool(api_key),
        "errors": errors[:5],
    }
