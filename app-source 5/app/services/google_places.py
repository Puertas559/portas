import json
import os
import re
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
        "industria", "fabrica", "planta industrial", "manufactura", "maquila",
        "metalurgica", "plasticos", "embalajes", "alimentos", "bebidas",
        "agroindustria", "frigorifico", "procesadora", "deposito", "almacen",
        "centro logistico", "centro de distribucion", "parque industrial", "galpon industrial",
    ],
    "logistica": [
        "centro logistico", "centro de distribucion", "deposito", "almacen", "transportadora",
        "operador logistico", "terminal de cargas", "logistica", "cross docking",
    ],
    "frigorifico": [
        "frigorifico", "camara frigorifica", "cadena de frio", "planta procesadora de carne",
        "industria carnica", "matadero", "alimentos congelados", "deposito refrigerado",
    ],
    "agro": [
        "agroindustria", "silo", "acopio de granos", "cooperativa agricola", "procesadora de granos",
        "semillas", "fertilizantes", "alimentos balanceados", "molino", "aceitera",
    ],
    "construccion": [
        "constructora", "ingenieria industrial", "estructuras metalicas", "tinglados", "galpones",
        "parque industrial", "desarrolladora industrial", "arquitectura industrial",
    ],
    "retail": [
        "supermercado", "hipermercado", "shopping", "centro comercial", "mayorista", "distribuidora",
    ],
    "aeronautica": [
        "hangar", "aeropuerto", "aviacion", "mantenimiento aeronautico", "aeroclub",
    ],
}

DEPTH_LIMITS = {
    "quick": (4, 1),
    "deep": (10, 2),
    "territorial": (18, 3),
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
    if base and any(word in base for word in ("industr", "fabr", "planta", "manufact")):
        options.extend(EXPANSIONS["industria"])
    seen, deduped = set(), []
    for item in options:
        norm = _normalize(item)
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(item)
    max_queries, _ = DEPTH_LIMITS.get(depth, DEPTH_LIMITS["deep"])
    return deduped[:max_queries]


def _post_places(api_key, payload):
    body = json.dumps(payload).encode("utf-8")
    request = Request(TEXT_SEARCH_URL, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    })
    try:
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Google Places respondió {exc.code}: {detail[:300]}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError("No se pudo conectar con Google Places") from exc


def _format_place(place, matched_term):
    display = place.get("displayName") or {}
    primary_type = place.get("primaryTypeDisplayName") or {}
    location = place.get("location") or {}
    return {
        "placeId": place.get("id"),
        "company": display.get("text") or "Empresa sin nombre",
        "address": place.get("formattedAddress"),
        "lat": location.get("latitude"),
        "lng": location.get("longitude"),
        "types": place.get("types") or [],
        "primaryType": primary_type.get("text") or place.get("primaryType"),
        "website": place.get("websiteUri"),
        "phone": place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber"),
        "rating": place.get("rating"),
        "reviews": place.get("userRatingCount") or 0,
        "mapsUrl": place.get("googleMapsUri"),
        "businessStatus": place.get("businessStatus"),
        "matchedTerm": matched_term,
        "source": "Google Places",
    }


def search_places(query="", city="", region="", industry="", depth="deep"):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    api_key = os.getenv("GOOGLE_PLACES_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise ValueError("Configure GOOGLE_PLACES_API_KEY en Railway para activar la búsqueda territorial.")
    depth = depth if depth in DEPTH_LIMITS else "deep"
    terms = _terms(query, industry, depth)
    _, page_limit = DEPTH_LIMITS[depth]
    location = ", ".join(part for part in [city, region, "Paraguay"] if part) or "Paraguay"

    def search_term(term):
        rows, local_errors, calls = [], [], 0
        page_token = None
        for _page in range(page_limit):
            payload = {
                "textQuery": f"{term} en {location}",
                "languageCode": "es",
                "regionCode": "PY",
                "pageSize": 20,
            }
            if page_token:
                payload["pageToken"] = page_token
            try:
                data = _post_places(api_key, payload)
                calls += 1
            except RuntimeError as exc:
                local_errors.append(str(exc))
                break
            rows.extend(_format_place(place, term) for place in data.get("places", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return rows, calls, local_errors

    found, errors, calls = {}, [], 0
    workers = min(6, max(1, len(terms)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(search_term, term) for term in terms]
        for future in as_completed(futures):
            rows, local_calls, local_errors = future.result()
            calls += local_calls
            errors.extend(local_errors)
            for row in rows:
                pid = row.get("placeId")
                if pid and pid not in found:
                    found[pid] = row

    results = list(found.values())
    results.sort(key=lambda row: (bool(row.get("website")), row.get("reviews") or 0, row.get("rating") or 0), reverse=True)
    return {
        "results": results,
        "count": len(results),
        "queries": terms,
        "calls": calls,
        "depth": depth,
        "errors": errors[:3],
    }
