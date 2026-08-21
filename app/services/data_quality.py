"""Conservative data-quality routines for company deduplication.

Only strong exact identifiers are auto-merged. Fuzzy candidates remain separate so
we never join different companies merely because their names look similar.
"""
from collections import defaultdict
from datetime import datetime, timezone
import re

from ..extensions import db
from ..models import Company, CompanyActivity, CompanyAlias, Contact, Project, Signal, Watchlist
from .entity_resolution import normalize_domain, normalize_name

_GENERIC_NAMES = {
    "inicio", "home", "empresa", "contacto", "contacta con nosotros", "ofertas",
    "nuestra historia", "instagram", "bienvenidos", "por validar", "unknown",
}


def _digits(value):
    return re.sub(r"\D+", "", value or "")


def _clean_email(value):
    return (value or "").strip().casefold()


def _company_keys(company):
    keys = []
    ruc = _digits(company.ruc or company.registration_id)
    if len(ruc) >= 6:
        keys.append(("registration", ruc))
    domain = normalize_domain(company.domain or company.website)
    if domain:
        keys.append(("domain", domain))
    normalized = normalize_name(company.canonical_name or company.name)
    if len(normalized) >= 6 and normalized not in _GENERIC_NAMES and not normalized.startswith("inicio "):
        keys.append(("name", normalized))
    return keys


def _richness(company):
    scalar = [
        company.ruc, company.registration_id, company.domain, company.website, company.legal_name,
        company.sector, company.city, company.department, company.address, company.email_business,
        company.email, company.whatsapp, company.phone_business, company.phone, company.description,
    ]
    relations = len(company.contacts or []) + len(company.projects or []) + len(company.activities or [])
    return sum(bool(v) for v in scalar) * 5 + relations


def _merge_contact(master_company, contact):
    existing = Contact.query.filter_by(tenant_id=master_company.tenant_id, company_id=master_company.id, status="ACTIVE").all()
    email = _clean_email(contact.email)
    phone = _digits(contact.whatsapp or contact.phone)
    match = None
    for row in existing:
        if email and _clean_email(row.email) == email:
            match = row; break
        if phone and _digits(row.whatsapp or row.phone) == phone:
            match = row; break
    if not match:
        contact.company_id = master_company.id
        return contact
    for attr in ("name", "role", "email", "phone", "whatsapp", "linkedin_url", "source_url"):
        if not getattr(match, attr, None) and getattr(contact, attr, None):
            setattr(match, attr, getattr(contact, attr))
    match.confidence = max(match.confidence or 0, contact.confidence or 0)
    match.influence_score = max(match.influence_score or 0, contact.influence_score or 0)
    CompanyActivity.query.filter_by(tenant_id=master_company.tenant_id, contact_id=contact.id).update({"contact_id": match.id}, synchronize_session=False)
    db.session.delete(contact)
    return match


def merge_companies(master, duplicate):
    """Merge duplicate into master without deleting commercial history."""
    if master.id == duplicate.id or master.tenant_id != duplicate.tenant_id:
        return master

    scalar_fields = (
        "sector", "origin_country", "website", "domain", "city", "department", "country", "description",
        "address", "phone", "phone_business", "whatsapp", "email", "email_business", "linkedin_url",
        "registration_id", "legal_name", "ruc", "founded_year", "headquarters", "company_size",
        "employee_estimate", "commercial_notes",
    )
    for attr in scalar_fields:
        if not getattr(master, attr, None) and getattr(duplicate, attr, None):
            setattr(master, attr, getattr(duplicate, attr))
    for attr in ("owners", "operation_plants", "key_activities", "data_sources"):
        current = list(getattr(master, attr, None) or [])
        for item in list(getattr(duplicate, attr, None) or []):
            if item not in current:
                current.append(item)
        setattr(master, attr, current)
    for attr in ("identity_confidence", "account_fit_score", "accessibility_score", "momentum_score", "data_completeness_score"):
        setattr(master, attr, max(getattr(master, attr, 0) or 0, getattr(duplicate, attr, 0) or 0))

    # Preserve duplicate name as an alias before moving relationships.
    dup_norm = normalize_name(duplicate.name)
    if dup_norm and dup_norm != master.normalized_name and not CompanyAlias.query.filter_by(
        tenant_id=master.tenant_id, company_id=master.id, normalized_alias=dup_norm
    ).first():
        db.session.add(CompanyAlias(tenant_id=master.tenant_id, company_id=master.id, alias=duplicate.name, normalized_alias=dup_norm, confidence=100))

    for contact in list(Contact.query.filter_by(tenant_id=master.tenant_id, company_id=duplicate.id).all()):
        _merge_contact(master, contact)
    CompanyActivity.query.filter_by(tenant_id=master.tenant_id, company_id=duplicate.id).update({"company_id": master.id}, synchronize_session=False)
    Project.query.filter_by(tenant_id=master.tenant_id, company_id=duplicate.id).update({"company_id": master.id}, synchronize_session=False)
    Signal.query.filter_by(tenant_id=master.tenant_id, company_id=duplicate.id).update({"company_id": master.id}, synchronize_session=False)

    master_watch = Watchlist.query.filter_by(tenant_id=master.tenant_id, company_id=master.id).first()
    dup_watch = Watchlist.query.filter_by(tenant_id=master.tenant_id, company_id=duplicate.id).first()
    if dup_watch:
        if master_watch:
            master_watch.priority = max(master_watch.priority or 0, dup_watch.priority or 0)
            if not master_watch.reason and dup_watch.reason:
                master_watch.reason = dup_watch.reason
            db.session.delete(dup_watch)
        else:
            dup_watch.company_id = master.id

    # Move aliases individually to avoid unique collisions.
    for alias in list(CompanyAlias.query.filter_by(tenant_id=master.tenant_id, company_id=duplicate.id).all()):
        exists = CompanyAlias.query.filter_by(tenant_id=master.tenant_id, company_id=master.id, normalized_alias=alias.normalized_alias).first()
        if exists:
            db.session.delete(alias)
        else:
            alias.company_id = master.id

    duplicate.status = "ARCHIVED_DUPLICATE"
    duplicate.deleted_at = datetime.now(timezone.utc)
    duplicate.commercial_notes = ((duplicate.commercial_notes or "") + f"\nConsolidada en empresa #{master.id}: {master.name}").strip()
    return master


def consolidate_exact_duplicates(tenant_id):
    """Idempotent, conservative cleanup of already-existing duplicate companies."""
    companies = Company.query.filter(Company.tenant_id == tenant_id, Company.status == "ACTIVE").order_by(Company.id.asc()).all()
    parent = {c.id: c.id for c in companies}
    rows = {c.id: c for c in companies}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    seen = {}
    for company in companies:
        for key in _company_keys(company):
            other = seen.get(key)
            if other:
                union(other, company.id)
            else:
                seen[key] = company.id

    groups = defaultdict(list)
    for cid in parent:
        groups[find(cid)].append(rows[cid])

    merged = 0
    groups_merged = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        # Keep the richest record; tie-breaker keeps the oldest ID.
        master = sorted(group, key=lambda c: (-_richness(c), c.id))[0]
        did_merge = False
        for duplicate in group:
            if duplicate.id == master.id:
                continue
            merge_companies(master, duplicate)
            merged += 1
            did_merge = True
        if did_merge:
            groups_merged += 1
    if merged:
        db.session.commit()
    return {"mergedCompanies": merged, "groupsMerged": groups_merged, "activeCompanies": Company.query.filter_by(tenant_id=tenant_id, status="ACTIVE").count()}
