import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..extensions import db
from ..models import (
    Company, Evidence, OpportunityEvidence, OpportunityScore, Product, ProductMatch, ScoreFactor,
    Signal, Source, SourceDocument,
)
from .entity_resolution import normalize_domain, normalize_name


DEFAULT_WEIGHTS = {
    "ICP_FIT": 0.15, "INTENT": 0.20, "TIMING": 0.20, "PROJECT_VALUE": 0.10,
    "PRODUCT_FIT": 0.15, "GEOGRAPHIC_FIT": 0.05, "DATA_CONFIDENCE": 0.07,
    "SIGNAL_RECENCY": 0.05, "COMMERCIAL_HISTORY": 0.03,
}

FACTOR_KEYS = {
    "ICP_FIT": "icpFit", "INTENT": "intent", "TIMING": "timing", "PROJECT_VALUE": "projectValueFit",
    "PRODUCT_FIT": "productFit", "GEOGRAPHIC_FIT": "geographicFit", "DATA_CONFIDENCE": "dataConfidence",
    "SIGNAL_RECENCY": "signalRecency", "COMMERCIAL_HISTORY": "commercialHistory",
}

DEFAULT_FRESHNESS_CURVE = ((0, 100), (30, 85), (90, 60), (180, 35), (365, 20))

BUYING_WINDOW_BY_EVENT = {
    "LAND_ACQUISITION": 96, "ENVIRONMENTAL_LICENSE": 95, "FINANCING_APPROVED": 94,
    "PROJECT_ANNOUNCEMENT": 92, "NEW_INVESTMENT": 90, "NEW_FACTORY": 90,
    "EXPANSION": 88, "CONSTRUCTION_START": 86, "CONSTRUCTION": 82,
    "WAREHOUSE_PROJECT": 86, "NEW_WAREHOUSE": 86, "NEW_NAVE": 86,
    "NEW_LOGISTICS_CENTER": 86, "COLD_CHAIN_PROJECT": 88,
    "TENDER": 78, "EQUIPMENT_IMPORT": 72, "HIRING_SURGE": 70,
    "OPENING": 35, "INAUGURATION": 25, "ACCOUNT_RESEARCH": 30, "OTHER": 45,
}

LIFECYCLE_BY_EVENT = {
    "LAND_ACQUISITION": "PROJECT_SIGNAL", "ENVIRONMENTAL_LICENSE": "PROJECT_SIGNAL",
    "FINANCING_APPROVED": "PROJECT_SIGNAL", "PROJECT_ANNOUNCEMENT": "PROJECT_SIGNAL",
    "NEW_INVESTMENT": "BUYING_WINDOW", "NEW_FACTORY": "BUYING_WINDOW", "EXPANSION": "BUYING_WINDOW",
    "CONSTRUCTION_START": "BUYING_WINDOW", "CONSTRUCTION": "BUYING_WINDOW",
    "WAREHOUSE_PROJECT": "BUYING_WINDOW", "NEW_WAREHOUSE": "BUYING_WINDOW", "NEW_NAVE": "BUYING_WINDOW",
    "NEW_LOGISTICS_CENTER": "BUYING_WINDOW",
    "COLD_CHAIN_PROJECT": "BUYING_WINDOW", "TENDER": "SALES_READY",
    "EQUIPMENT_IMPORT": "SALES_READY", "HIRING_SURGE": "MONITORING",
    "OPENING": "LATE_SIGNAL", "INAUGURATION": "LATE_SIGNAL",
}

BASE_DEAL_RANGES = {
    "NEW_LOGISTICS_CENTER": (30000, 180000), "WAREHOUSE_PROJECT": (20000, 120000),
    "NEW_WAREHOUSE": (20000, 120000), "NEW_NAVE": (20000, 120000),
    "COLD_CHAIN_PROJECT": (25000, 160000), "NEW_FACTORY": (25000, 150000),
    "EXPANSION": (15000, 100000), "CONSTRUCTION_START": (18000, 120000),
    "CONSTRUCTION": (15000, 100000), "TENDER": (10000, 90000),
    "EQUIPMENT_IMPORT": (12000, 80000), "ACCOUNT_RESEARCH": (5000, 40000),
    "OTHER": (5000, 35000),
}


def clamp(value, default=50):
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def canonical_url(url):
    if not url:
        return "https://unknown.invalid/evidence"
    parsed = urlparse(url if "://" in url else f"https://{url}")
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parsed.query) if not key.lower().startswith("utm_")))
    return urlunparse((parsed.scheme.lower() or "https", (parsed.netloc or "").lower(), parsed.path or "/", "", query, ""))


def as_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def freshness_score(occurred_at, now=None, curve=None):
    occurred = as_datetime(occurred_at)
    if not occurred:
        return 50
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    age_days = max(0, (reference - occurred).days)
    points = curve or DEFAULT_FRESHNESS_CURVE
    for max_days, score in points:
        if age_days <= max_days:
            return score
    return max(5, round(points[-1][1] * 365 / max(age_days, 365)))


def infer_buying_window(event_type, explicit=None):
    return clamp(explicit, BUYING_WINDOW_BY_EVENT.get((event_type or "OTHER").upper(), 45))


def infer_lifecycle(event_type, buying_window=None):
    event = (event_type or "OTHER").upper()
    if event in LIFECYCLE_BY_EVENT:
        return LIFECYCLE_BY_EVENT[event]
    window = infer_buying_window(event, buying_window)
    if window >= 80:
        return "BUYING_WINDOW"
    if window >= 60:
        return "PROJECT_SIGNAL"
    if window >= 40:
        return "MONITORING"
    return "DISCOVERED"


def estimate_deal_range(event_type, products=None, investment_amount=None, area_m2=None):
    low, high = BASE_DEAL_RANGES.get((event_type or "OTHER").upper(), BASE_DEAL_RANGES["OTHER"])
    product_count = max(1, len(products or []))
    multiplier = min(2.2, 0.85 + product_count * 0.18)
    try:
        investment = float(investment_amount or 0)
    except (TypeError, ValueError):
        investment = 0
    try:
        area = float(area_m2 or 0)
    except (TypeError, ValueError):
        area = 0
    if investment >= 10_000_000:
        multiplier += 0.55
    elif investment >= 2_000_000:
        multiplier += 0.25
    if area >= 20_000:
        multiplier += 0.45
    elif area >= 5_000:
        multiplier += 0.20
    return round(low * multiplier, 2), round(high * multiplier, 2)


def accessibility_score(company):
    score = 0
    score += 22 if company.whatsapp else 0
    score += 18 if company.phone_business or company.phone else 0
    score += 20 if company.email_business or company.email else 0
    score += 12 if company.linkedin_url else 0
    contacts = list(getattr(company, "contacts", []) or [])
    if contacts:
        score += 12
        score += min(16, max((contact.influence_score or 0) for contact in contacts) // 6)
    return min(100, score)


def build_why_now(event_type, company_name, project_name, buying_window, momentum=0):
    event = (event_type or "OTHER").upper()
    phase = {
        "LAND_ACQUISITION": "la adquisición de terreno indica una fase temprana de implantación",
        "ENVIRONMENTAL_LICENSE": "la licencia ambiental suele anteceder la ejecución física del proyecto",
        "FINANCING_APPROVED": "el financiamiento aprobado reduce la incertidumbre de ejecución",
        "NEW_INVESTMENT": "la inversión anunciada abre una ventana temprana para especificación técnica",
        "NEW_FACTORY": "la nueva planta probablemente requerirá accesos industriales y automatización",
        "EXPANSION": "la expansión puede generar nuevos accesos, retrofit y aumento de capacidad",
        "CONSTRUCTION_START": "el inicio de obra acerca la definición de cerramientos, accesos y áreas de carga",
        "NEW_LOGISTICS_CENTER": "un centro logístico suele concentrar demanda de puertas, niveladores y abrigos de muelle",
        "COLD_CHAIN_PROJECT": "la cadena de frío requiere separación térmica y accesos de alta frecuencia",
        "TENDER": "la licitación indica una necesidad formal y un proceso de compra activo",
        "EQUIPMENT_IMPORT": "la llegada de equipos sugiere una implantación próxima a la fase operativa",
        "HIRING_SURGE": "la contratación simultánea puede anticipar expansión o inicio de operación",
    }.get(event, "existe una señal reciente compatible con una necesidad industrial")
    momentum_text = f" El momentum de la cuenta es {momentum}/100." if momentum else ""
    return f"Contactar ahora porque {phase}. Buying window estimado: {buying_window}/100 para {company_name} — {project_name}.{momentum_text}"


def next_best_action_for(opportunity):
    company = opportunity.project.company
    stage = opportunity.buying_stage
    if not company.whatsapp and not (company.phone_business or company.phone) and not (company.email_business or company.email):
        return "Investigar contacto de Ingeniería, Mantenimiento, Operaciones, Logística o Compras antes de abordar la cuenta."
    if opportunity.buying_window_score >= 85:
        return "Contactar hoy al responsable técnico, confirmar la etapa de obra y preguntar cuándo se definirán accesos, puertas y áreas de carga."
    if stage in {"RFQ", "PROCUREMENT", "NEGOTIATION"}:
        return "Priorizar llamada comercial y solicitar alcance técnico, medidas, cantidades, cronograma y criterio de adjudicación."
    if opportunity.momentum_score >= 65:
        return "Realizar contacto consultivo esta semana y validar cronograma, responsables y posibles aplicaciones del portafolio."
    return "Mantener en watchlist, enriquecer decisores y revisar nuevas señales antes del próximo contacto."


def record_evidence(tenant, company, project, data):
    source_name = (data.get("sourceName") or data.get("source") or "Fuente pública").strip()
    raw_url = data.get("sourceUrl") or data.get("website")
    if not raw_url:
        seed = "|".join((data.get("company") or "unknown", data.get("project") or "unknown", data.get("evidence") or "unknown"))
        raw_url = f"https://evidence.local/{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"
    url = canonical_url(raw_url)
    domain = normalize_domain(url)
    source = Source.query.filter_by(tenant_id=tenant.id, name=source_name, domain=domain).first()
    if not source:
        source = Source(
            tenant_id=tenant.id, name=source_name, domain=domain, base_url=f"https://{domain}" if domain else None,
            source_type=data.get("sourceType") or "PUBLIC_WEB", reliability=clamp(data.get("sourceReliability"), 60),
        )
        db.session.add(source)
        db.session.flush()
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    document = SourceDocument.query.filter_by(tenant_id=tenant.id, url_hash=url_hash).first()
    evidence_text = (data.get("evidence") or data.get("summary") or "Evidencia pendiente de validación").strip()
    if not document:
        document = SourceDocument(
            tenant_id=tenant.id, source_id=source.id, url=url, canonical_url=url, url_hash=url_hash,
            content_hash=hashlib.sha256(evidence_text.encode("utf-8")).hexdigest(),
            title=(data.get("sourceTitle") or data.get("project") or project.name)[:700], excerpt=evidence_text,
            published_at=as_datetime(data.get("publishedAt")), confidence=clamp(data.get("dataConfidence"), source.reliability),
            document_metadata={"collector": data.get("collector"), "causality": data.get("causality") or []},
        )
        db.session.add(document)
        db.session.flush()
    fingerprint_raw = "|".join((str(project.id), data.get("event") or data.get("signalType") or "OTHER", url_hash, evidence_text[:300]))
    fingerprint = hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()
    signal = Signal.query.filter_by(tenant_id=tenant.id, fingerprint=fingerprint).first()
    if not signal:
        event_type = data.get("event") or data.get("signalType") or "OTHER"
        window = infer_buying_window(event_type, data.get("buyingWindow"))
        signal = Signal(
            tenant_id=tenant.id, company_id=company.id, project_id=project.id, source_document_id=document.id,
            signal_type=event_type,
            title=(data.get("sourceTitle") or project.name)[:700], summary=evidence_text,
            city=project.city, department=project.department, country=project.country,
            confidence=clamp(data.get("dataConfidence"), document.confidence),
            freshness=clamp(data.get("signalRecency"), 100), relevance=clamp(data.get("relevance"), 70),
            impact_score=clamp(data.get("impactScore"), data.get("intent") or 60),
            buying_window_score=window, lifecycle_stage=infer_lifecycle(event_type, window),
            causality=data.get("causality") or [], product_hypothesis=data.get("products") or [],
            fingerprint=fingerprint, occurred_at=as_datetime(data.get("occurredAt")) or as_datetime(data.get("publishedAt")),
        )
        db.session.add(signal)
        db.session.flush()
    evidence = Evidence.query.filter_by(signal_id=signal.id, source_document_id=document.id, claim=evidence_text).first()
    if not evidence:
        classification = (data.get("evidenceClassification") or "FACT").upper()
        if classification not in {"FACT", "INFERENCE", "PREDICTION"}:
            classification = "INFERENCE"
        evidence = Evidence(
            tenant_id=tenant.id, project_id=project.id, signal_id=signal.id, source_document_id=document.id,
            claim=evidence_text, excerpt=evidence_text, classification=classification,
            confidence=clamp(data.get("dataConfidence"), signal.confidence),
        )
        db.session.add(evidence)
        db.session.flush()
    company.last_signal_at = signal.detected_at
    return signal, evidence



def company_completeness(company):
    checks = {
        "website": bool(company.website),
        "phone": bool(company.phone_business or company.phone),
        "email": bool(company.email_business or company.email),
        "whatsapp": bool(company.whatsapp),
        "location": bool(company.city or company.address),
        "sector": bool(company.sector),
        "identity": int(company.identity_confidence or 0) >= 65,
        "legalName": bool(company.legal_name),
        "ruc": bool(company.ruc or company.registration_id),
        "decisionMaker": bool(company.contacts),
    }
    weights = {"website": 10, "phone": 10, "email": 12, "whatsapp": 8, "location": 10, "sector": 10, "identity": 8, "legalName": 8, "ruc": 10, "decisionMaker": 14}
    score = sum(weights[key] for key, present in checks.items() if present)
    missing = [key for key, present in checks.items() if not present]
    return min(100, score), missing


def lead_readiness(opportunity):
    company = opportunity.project.company
    completeness, missing = company_completeness(company)
    contact_ready = bool(opportunity.contact_verified or company.contacts)
    readiness = round(
        (opportunity.score or 0) * .25 +
        (opportunity.buying_window_score or 0) * .20 +
        (opportunity.confidence_score or 0) * .15 +
        completeness * .20 +
        (100 if contact_ready else opportunity.accessibility_score or 0) * .15 +
        (100 if opportunity.next_best_action else 0) * .05
    )
    blockers = list(missing)
    if (opportunity.confidence_score or 0) < 60: blockers.append("confidence")
    if (opportunity.score or 0) < 65: blockers.append("commercialFit")
    if not contact_ready: blockers.append("decisionMaker")
    sales_ready = readiness >= 70 and (opportunity.score or 0) >= 65 and (opportunity.confidence_score or 0) >= 55 and contact_ready
    company.data_completeness_score = completeness
    company.research_status = "READY" if completeness >= 80 and contact_ready else "PENDING"
    opportunity.lead_readiness_score = min(100, readiness)
    opportunity.sales_ready = bool(sales_ready)
    return opportunity.lead_readiness_score, sorted(set(blockers))


def score_opportunity(tenant, opportunity, data):
    configured = (tenant.settings or {}).get("scoring_weights") or DEFAULT_WEIGHTS
    total_weight = sum(float(configured.get(code, 0)) for code in DEFAULT_WEIGHTS) or 1
    legacy = clamp(data.get("score"), 50)
    values = {code: clamp(data.get(FACTOR_KEYS[code]), legacy) for code in DEFAULT_WEIGHTS}
    event_type = opportunity.event_type
    buying_window = infer_buying_window(event_type, data.get("buyingWindow") or data.get("timing"))
    values["TIMING"] = buying_window
    if data.get("signalRecency") is None and (data.get("occurredAt") or data.get("publishedAt")):
        values["SIGNAL_RECENCY"] = freshness_score(data.get("occurredAt") or data.get("publishedAt"))
    total = round(sum(values[code] * float(configured.get(code, 0)) for code in DEFAULT_WEIGHTS) / total_weight)
    if values["DATA_CONFIDENCE"] < 50:
        total = min(total, 74)
    model_version = (tenant.settings or {}).get("scoring_model_version", "radar-v2")
    OpportunityScore.query.filter_by(tenant_id=tenant.id, opportunity_id=opportunity.id, is_current=True).update({"is_current": False})
    evaluation = OpportunityScore(
        tenant_id=tenant.id, opportunity_id=opportunity.id, total_score=total,
        model_version=model_version, is_current=True,
    )
    db.session.add(evaluation)
    db.session.flush()
    explanations = data.get("scoreExplanations") or {}
    for code, value in values.items():
        weight = float(configured.get(code, 0)) / total_weight
        db.session.add(ScoreFactor(
            score_id=evaluation.id, factor_code=code, raw_value=Decimal(value), weight=Decimal(str(weight)),
            points=Decimal(str(round(value * weight, 3))),
            explanation=explanations.get(code) or f"{code.replace('_', ' ').title()}: {value}/100 según evidencia disponible.",
        ))
    company = opportunity.project.company
    opportunity.score = total
    opportunity.level = "HOT" if total >= 90 else "HIGH" if total >= 75 else "MEDIUM" if total >= 55 else "LOW" if total >= 30 else "VERY_LOW"
    opportunity.icp_fit_score = values["ICP_FIT"]
    opportunity.intent_score = values["INTENT"]
    opportunity.data_confidence = values["DATA_CONFIDENCE"]
    opportunity.confidence_score = values["DATA_CONFIDENCE"]
    opportunity.buying_window_score = buying_window
    opportunity.accessibility_score = accessibility_score(company)
    opportunity.momentum_score = clamp(data.get("momentum"), max(0, min(100, values["INTENT"] - 10 + values["SIGNAL_RECENCY"] // 5)))
    opportunity.lifecycle_stage = infer_lifecycle(event_type, buying_window)
    low, high = estimate_deal_range(event_type, opportunity.products, opportunity.project.investment_amount, opportunity.project.area_m2)
    if float(opportunity.potential_deal_value or 0) > 0:
        midpoint = float(opportunity.potential_deal_value)
        low, high = min(low, midpoint * 0.75), max(high, midpoint * 1.35)
    opportunity.deal_value_min = Decimal(str(round(low, 2)))
    opportunity.deal_value_max = Decimal(str(round(high, 2)))
    opportunity.why_now = build_why_now(event_type, company.name, opportunity.project.name, buying_window, opportunity.momentum_score)
    opportunity.score_version = model_version
    opportunity.expected_revenue = Decimal(str(opportunity.potential_deal_value or opportunity.estimated_value or ((low + high) / 2))) * Decimal(opportunity.probability or 0) / Decimal(100)
    opportunity.project.buying_window_score = buying_window
    opportunity.project.demand_probability = max(values["PRODUCT_FIT"], values["INTENT"])
    opportunity.project.momentum_score = opportunity.momentum_score
    opportunity.project.lifecycle_stage = opportunity.lifecycle_stage
    opportunity.project.estimated_deal_min = opportunity.deal_value_min
    opportunity.project.estimated_deal_max = opportunity.deal_value_max
    opportunity.project.stage_confidence = values["DATA_CONFIDENCE"]
    company.account_fit_score = values["ICP_FIT"]
    company.accessibility_score = opportunity.accessibility_score
    company.momentum_score = max(company.momentum_score or 0, opportunity.momentum_score)
    company.watch_status = "HOT" if total >= 90 else "WARM" if total >= 70 else "WATCH"
    opportunity.next_best_action = next_best_action_for(opportunity)
    company.last_enriched_at = datetime.now(timezone.utc)
    lead_readiness(opportunity)
    return evaluation


def link_evidence_and_products(tenant, opportunity, evidence, product_names, product_fit=70):
    if not OpportunityEvidence.query.filter_by(opportunity_id=opportunity.id, evidence_id=evidence.id).first():
        db.session.add(OpportunityEvidence(opportunity_id=opportunity.id, evidence_id=evidence.id))
    for name in product_names or []:
        normalized = normalize_name(name)
        product = Product.query.filter_by(tenant_id=tenant.id, normalized_name=normalized).first()
        if not product:
            product = Product(tenant_id=tenant.id, name=name, normalized_name=normalized, category="SIN CLASIFICAR")
            db.session.add(product)
            db.session.flush()
        match = ProductMatch.query.filter_by(opportunity_id=opportunity.id, product_id=product.id).first()
        if not match:
            db.session.add(ProductMatch(
                opportunity_id=opportunity.id, product_id=product.id, evidence_id=evidence.id,
                fit_score=clamp(product_fit, 70), confidence=evidence.confidence,
                rationale=f"Coincidencia estimada a partir de la señal {evidence.signal.signal_type}; requiere validación comercial.",
            ))
