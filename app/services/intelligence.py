import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..extensions import db
from ..models import (
    Evidence, OpportunityEvidence, OpportunityScore, Product, ProductMatch, ScoreFactor,
    Signal, Source, SourceDocument,
)
from .entity_resolution import normalize_domain, normalize_name


DEFAULT_WEIGHTS = {
    "ICP_FIT": 0.18, "INTENT": 0.22, "TIMING": 0.12, "PROJECT_VALUE": 0.10,
    "PRODUCT_FIT": 0.14, "GEOGRAPHIC_FIT": 0.08, "DATA_CONFIDENCE": 0.08,
    "SIGNAL_RECENCY": 0.05, "COMMERCIAL_HISTORY": 0.03,
}

FACTOR_KEYS = {
    "ICP_FIT": "icpFit", "INTENT": "intent", "TIMING": "timing", "PROJECT_VALUE": "projectValueFit",
    "PRODUCT_FIT": "productFit", "GEOGRAPHIC_FIT": "geographicFit", "DATA_CONFIDENCE": "dataConfidence",
    "SIGNAL_RECENCY": "signalRecency", "COMMERCIAL_HISTORY": "commercialHistory",
}

DEFAULT_FRESHNESS_CURVE = ((0, 100), (30, 85), (90, 60), (180, 35), (365, 20))


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
        )
        db.session.add(document)
        db.session.flush()
    fingerprint_raw = "|".join((str(project.id), data.get("event") or data.get("signalType") or "OTHER", url_hash, evidence_text[:300]))
    fingerprint = hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()
    signal = Signal.query.filter_by(tenant_id=tenant.id, fingerprint=fingerprint).first()
    if not signal:
        signal = Signal(
            tenant_id=tenant.id, company_id=company.id, project_id=project.id, source_document_id=document.id,
            signal_type=data.get("event") or data.get("signalType") or "OTHER",
            title=(data.get("sourceTitle") or project.name)[:700], summary=evidence_text,
            city=project.city, department=project.department, country=project.country,
            confidence=clamp(data.get("dataConfidence"), document.confidence),
            freshness=clamp(data.get("signalRecency"), 100), relevance=clamp(data.get("relevance"), 70),
            fingerprint=fingerprint, occurred_at=as_datetime(data.get("occurredAt")),
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
    return signal, evidence


def score_opportunity(tenant, opportunity, data):
    configured = (tenant.settings or {}).get("scoring_weights") or DEFAULT_WEIGHTS
    total_weight = sum(float(configured.get(code, 0)) for code in DEFAULT_WEIGHTS) or 1
    legacy = clamp(data.get("score"), 50)
    values = {code: clamp(data.get(FACTOR_KEYS[code]), legacy) for code in DEFAULT_WEIGHTS}
    if data.get("signalRecency") is None and (data.get("occurredAt") or data.get("publishedAt")):
        values["SIGNAL_RECENCY"] = freshness_score(data.get("occurredAt") or data.get("publishedAt"))
    total = round(sum(values[code] * float(configured.get(code, 0)) for code in DEFAULT_WEIGHTS) / total_weight)
    if values["DATA_CONFIDENCE"] < 50:
        total = min(total, 74)
    model_version = (tenant.settings or {}).get("scoring_model_version", "phase1-v1")
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
    opportunity.score = total
    opportunity.level = "HOT" if total >= 90 else "HIGH" if total >= 75 else "MEDIUM" if total >= 55 else "LOW" if total >= 30 else "VERY_LOW"
    opportunity.icp_fit_score = values["ICP_FIT"]
    opportunity.intent_score = values["INTENT"]
    opportunity.data_confidence = values["DATA_CONFIDENCE"]
    opportunity.score_version = model_version
    opportunity.expected_revenue = Decimal(str(opportunity.potential_deal_value or opportunity.estimated_value or 0)) * Decimal(opportunity.probability or 0) / Decimal(100)
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
