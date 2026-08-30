import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse

from ..extensions import db
from ..models import Company, CompanyAlias, Project


LEGAL_SUFFIXES = {"sa", "s", "a", "srl", "ltda", "eas", "inc", "corp", "company", "cia"}
PLACEHOLDER_NAMES = {"empresa por validar", "empresa desconocida", "unknown", "por validar", "no identificado"}


def normalize_name(value):
    value = unicodedata.normalize("NFKD", (value or "").casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    tokens = re.findall(r"[a-z0-9]+", value)
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_domain(value):
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    return hostname or None


def _candidate_company(tenant_id, normalized, domain, registration_id, country, city, ruc=None):
    base = Company.query.filter_by(tenant_id=tenant_id, status="ACTIVE")
    if ruc:
        match = base.filter_by(ruc=ruc).first()
        if match:
            return match, 100
    if registration_id:
        match = base.filter_by(registration_id=registration_id).first()
        if match:
            return match, 100
    if domain:
        match = base.filter_by(domain=domain).first()
        if match:
            return match, 98
    if normalized in PLACEHOLDER_NAMES:
        return None, 0
    match = base.filter_by(normalized_name=normalized, country=country).first()
    if match:
        return match, 94
    alias = CompanyAlias.query.filter_by(tenant_id=tenant_id, normalized_alias=normalized).first()
    if alias:
        return alias.company, alias.confidence
    if len(normalized) >= 6:
        candidates = base.filter_by(country=country).limit(100).all()
        for candidate in candidates:
            same_city = not city or not candidate.city or normalize_name(city) == normalize_name(candidate.city)
            similarity = SequenceMatcher(None, normalized, candidate.normalized_name).ratio()
            if same_city and similarity >= 0.94:
                return candidate, round(similarity * 90)
    return None, 0


def resolve_company(tenant_id, name, **fields):
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Falta el nombre de la empresa")
    normalized = normalize_name(clean_name)
    country = (fields.get("country") or fields.get("origin_country") or "Paraguay").strip()
    domain = normalize_domain(fields.get("website"))
    company, confidence = _candidate_company(
        tenant_id, normalized, domain, fields.get("registration_id"), country, fields.get("city"), fields.get("ruc"),
    )
    if not company:
        company = Company(
            tenant_id=tenant_id, name=clean_name, canonical_name=clean_name, normalized_name=normalized,
            country=country, domain=domain, identity_confidence=80 if domain else 60,
        )
        db.session.add(company)
        db.session.flush()
    elif normalize_name(company.name) != normalized:
        alias = CompanyAlias.query.filter_by(tenant_id=tenant_id, company_id=company.id, normalized_alias=normalized).first()
        if not alias:
            db.session.add(CompanyAlias(
                tenant_id=tenant_id, company_id=company.id, alias=clean_name,
                normalized_alias=normalized, confidence=confidence,
            ))
    mapping = {
        "sector": "sector", "origin_country": "origin_country", "website": "website", "city": "city",
        "department": "department", "description": "description", "address": "address", "phone": "phone",
        "phone_business": "phone_business", "whatsapp": "whatsapp", "email": "email",
        "email_business": "email_business", "linkedin_url": "linkedin_url", "registration_id": "registration_id",
        "ruc": "ruc", "legal_name": "legal_name",
    }
    for incoming, attribute in mapping.items():
        value = fields.get(incoming)
        if value and not getattr(company, attribute):
            setattr(company, attribute, value)
    company.domain = company.domain or domain
    company.phone_business = company.phone_business or company.phone
    company.email_business = company.email_business or company.email
    return company


def project_identity_key(company_id, name, city, project_type):
    raw = "|".join((str(company_id), normalize_name(name), normalize_name(city), normalize_name(project_type)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resolve_project(tenant_id, company, name, city="Por validar", department="Por validar", **fields):
    clean_name = (name or "Proyecto por validar").strip()
    project_type = (fields.get("project_type") or "UNKNOWN").strip()
    identity_key = project_identity_key(company.id, clean_name, city, project_type)
    project = Project.query.filter_by(tenant_id=tenant_id, identity_key=identity_key, status="ACTIVE").first()
    if not project:
        normalized = normalize_name(clean_name)
        candidates = Project.query.filter_by(
            tenant_id=tenant_id, company_id=company.id, normalized_name=normalized,
            city=city or "Por validar", status="ACTIVE",
        ).all()
        project = candidates[0] if len(candidates) == 1 else next((row for row in candidates if row.project_type == project_type), None)
    if not project:
        project = Project(
            tenant_id=tenant_id, company=company, name=clean_name, normalized_name=normalize_name(clean_name),
            project_type=project_type, city=city or "Por validar", department=department or "Por validar",
            country=fields.get("country") or company.country or "Paraguay", identity_key=identity_key,
        )
        db.session.add(project)
    elif project.project_type in {None, "UNKNOWN"} and project_type != "UNKNOWN":
        project.project_type = project_type
        project.identity_key = identity_key
    for key in ("stage", "investment", "investment_amount", "investment_currency", "area_m2", "description", "announced_at", "started_at"):
        value = fields.get(key)
        if value is not None and not getattr(project, key):
            setattr(project, key, value)
    return project
