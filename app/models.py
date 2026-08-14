from datetime import datetime, timedelta, timezone
from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Company(db.Model):
    __tablename__ = "companies"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(220), unique=True, nullable=False, index=True)
    sector = db.Column(db.String(120))
    origin_country = db.Column(db.String(80))
    website = db.Column(db.String(500))
    address = db.Column(db.Text)
    phone = db.Column(db.String(120))
    whatsapp = db.Column(db.String(120))
    email = db.Column(db.String(240))
    linkedin_url = db.Column(db.String(700))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    projects = db.relationship("Project", back_populates="company", cascade="all, delete-orphan")


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(300), nullable=False)
    city = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(120), nullable=False)
    stage = db.Column(db.String(120))
    investment = db.Column(db.String(120))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    company = db.relationship("Company", back_populates="projects")
    opportunities = db.relationship("Opportunity", back_populates="project", cascade="all, delete-orphan")


class Opportunity(db.Model):
    __tablename__ = "opportunities"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = db.Column(db.String(80), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False, index=True)
    level = db.Column(db.String(20), nullable=False, index=True)
    status = db.Column(db.String(40), default="NOVO", nullable=False, index=True)
    products = db.Column(db.JSON, default=list, nullable=False)
    evidence = db.Column(db.Text, nullable=False)
    source_name = db.Column(db.String(220))
    source_url = db.Column(db.String(1000))
    contact_verified = db.Column(db.Boolean, nullable=False, default=False)
    next_action_at = db.Column(db.DateTime(timezone=True), default=lambda: utcnow() + timedelta(days=2), index=True)
    discovered_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    project = db.relationship("Project", back_populates="opportunities")
    timeline = db.relationship("TimelineEvent", back_populates="opportunity", cascade="all, delete-orphan")

    def to_dict(self):
        sector = self.project.company.sector or "No informado"
        pains = {
            "Frigorífico y cadena de frío": ["Pérdida térmica", "Higiene y condensación", "Paradas por mantenimiento"],
            "Logística y distribución": ["Demora en carga y descarga", "Seguridad de los muelles", "Alto flujo de vehículos"],
            "Industria y manufactura": ["Continuidad operativa", "Seguridad de accesos", "Desgaste de equipos"],
            "Alimentos y bebidas": ["Higiene operacional", "Separación de ambientes", "Velocidad de circulación"],
            "Agronegocio": ["Polvo y clima", "Grandes vanos", "Protección de equipos"],
        }.get(sector, ["Seguridad de accesos", "Continuidad operativa", "Mantenimiento preventivo"])
        return {
            "id": self.id, "company": self.project.company.name, "sector": sector,
            "origin": self.project.company.origin_country or "No informado", "project": self.project.name,
            "city": self.project.city, "department": self.project.department, "stage": self.project.stage or "No informado",
            "investment": self.project.investment or "No divulgado", "event": self.event_type, "score": self.score,
            "level": self.level, "status": self.status, "products": self.products or [], "evidence": self.evidence,
            "sourceName": self.source_name, "sourceUrl": self.source_url,
            "website": self.project.company.website, "address": self.project.company.address,
            "phone": self.project.company.phone, "whatsapp": self.project.company.whatsapp,
            "email": self.project.company.email, "linkedin": self.project.company.linkedin_url,
            "painPoints": pains, "contactVerified": self.contact_verified,
            "nextActionAt": self.next_action_at.isoformat() if self.next_action_at else None,
            "discoveredAt": self.discovered_at.isoformat() if self.discovered_at else None,
        }


class TimelineEvent(db.Model):
    __tablename__ = "timeline_events"
    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    occurred_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    opportunity = db.relationship("Opportunity", back_populates="timeline")


class ProspectSignal(db.Model):
    __tablename__ = "prospect_signals"
    id = db.Column(db.Integer, primary_key=True)
    fingerprint = db.Column(db.String(64), unique=True, nullable=False, index=True)
    company_name = db.Column(db.String(220), nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    source_name = db.Column(db.String(160), nullable=False, index=True)
    source_url = db.Column(db.String(1200), nullable=False)
    source_type = db.Column(db.String(40), nullable=False, default="NEWS")
    source_reliability = db.Column(db.Integer, nullable=False, default=50)
    published_at = db.Column(db.DateTime(timezone=True))
    city = db.Column(db.String(120))
    department = db.Column(db.String(120))
    event_type = db.Column(db.String(80), nullable=False)
    score = db.Column(db.Integer, nullable=False, index=True)
    level = db.Column(db.String(20), nullable=False, index=True)
    products = db.Column(db.JSON, default=list, nullable=False)
    reasons = db.Column(db.JSON, default=list, nullable=False)
    status = db.Column(db.String(40), nullable=False, default="PENDING_VALIDATION", index=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="SET NULL"), index=True)
    discovered_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    opportunity = db.relationship("Opportunity")

    def to_dict(self):
        return {
            "id": self.id, "company": self.company_name, "title": self.title, "summary": self.summary,
            "sourceName": self.source_name, "sourceUrl": self.source_url, "sourceType": self.source_type,
            "reliability": self.source_reliability, "publishedAt": self.published_at.isoformat() if self.published_at else None,
            "city": self.city, "department": self.department, "event": self.event_type, "score": self.score,
            "level": self.level, "products": self.products or [], "reasons": self.reasons or [],
            "status": self.status, "opportunityId": self.opportunity_id,
            "discoveredAt": self.discovered_at.isoformat() if self.discovered_at else None,
        }


class CollectorRun(db.Model):
    __tablename__ = "collector_runs"
    id = db.Column(db.Integer, primary_key=True)
    started_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    finished_at = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(30), nullable=False, default="RUNNING", index=True)
    sources_scanned = db.Column(db.Integer, nullable=False, default=0)
    items_scanned = db.Column(db.Integer, nullable=False, default=0)
    signals_created = db.Column(db.Integer, nullable=False, default=0)
    errors = db.Column(db.JSON, default=list, nullable=False)

    def to_dict(self):
        return {
            "id": self.id, "startedAt": self.started_at.isoformat() if self.started_at else None,
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None, "status": self.status,
            "sourcesScanned": self.sources_scanned, "itemsScanned": self.items_scanned,
            "signalsCreated": self.signals_created, "errors": self.errors or [],
        }


class WebsiteAnalysis(db.Model):
    __tablename__ = "website_analyses"
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(1200), nullable=False)
    company_name = db.Column(db.String(240), nullable=False, default="Empresa por validar")
    sector = db.Column(db.String(160), nullable=False, default="Por validar")
    address = db.Column(db.Text)
    phones = db.Column(db.JSON, default=list, nullable=False)
    whatsapp = db.Column(db.String(120))
    emails = db.Column(db.JSON, default=list, nullable=False)
    contacts = db.Column(db.JSON, default=list, nullable=False)
    social_links = db.Column(db.JSON, default=dict, nullable=False)
    company_size = db.Column(db.String(80), nullable=False, default="No determinado")
    potential_score = db.Column(db.Integer, nullable=False, default=0, index=True)
    potential_level = db.Column(db.String(30), nullable=False, default="BAJO", index=True)
    products = db.Column(db.JSON, default=list, nullable=False)
    services = db.Column(db.JSON, default=list, nullable=False)
    reasons = db.Column(db.JSON, default=list, nullable=False)
    pages_analyzed = db.Column(db.Integer, nullable=False, default=0)
    summary = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="COMPLETED", index=True)
    error = db.Column(db.Text)
    decision = db.Column(db.String(30), nullable=False, default="PENDING", index=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="SET NULL"), index=True)
    whatsapp_message = db.Column(db.Text)
    email_subject = db.Column(db.String(300))
    email_body = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    opportunity = db.relationship("Opportunity")

    def to_dict(self):
        return {
            "id": self.id, "url": self.url, "company": self.company_name, "sector": self.sector,
            "address": self.address, "phones": self.phones or [], "whatsapp": self.whatsapp,
            "emails": self.emails or [], "contacts": self.contacts or [], "socialLinks": self.social_links or {},
            "companySize": self.company_size, "score": self.potential_score, "level": self.potential_level,
            "products": self.products or [], "services": self.services or [], "reasons": self.reasons or [],
            "pagesAnalyzed": self.pages_analyzed, "summary": self.summary, "status": self.status,
            "error": self.error, "createdAt": self.created_at.isoformat() if self.created_at else None,
            "decision": self.decision, "opportunityId": self.opportunity_id,
            "whatsappMessage": self.whatsapp_message, "emailSubject": self.email_subject,
            "emailBody": self.email_body,
        }
