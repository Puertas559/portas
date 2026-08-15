from datetime import datetime, timedelta, timezone
from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class Tenant(db.Model):
    __tablename__ = "tenants"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(220), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    settings = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    email = db.Column(db.String(320), nullable=False)
    normalized_email = db.Column(db.String(320), nullable=False)
    password_hash = db.Column(db.String(500), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="ADMIN", index=True)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    last_login_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    tenant = db.relationship("Tenant")
    __table_args__ = (db.UniqueConstraint("tenant_id", "normalized_email", name="uq_users_tenant_email"),)


class Company(db.Model):
    __tablename__ = "companies"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = db.Column(db.String(220), nullable=False, index=True)
    canonical_name = db.Column(db.String(220), nullable=False)
    normalized_name = db.Column(db.String(220), nullable=False, index=True)
    sector = db.Column(db.String(120))
    origin_country = db.Column(db.String(80))
    website = db.Column(db.String(500))
    domain = db.Column(db.String(255), index=True)
    city = db.Column(db.String(120))
    department = db.Column(db.String(120))
    country = db.Column(db.String(80), nullable=False, default="Paraguay", index=True)
    description = db.Column(db.Text)
    address = db.Column(db.Text)
    phone = db.Column(db.String(120))
    phone_business = db.Column(db.String(120))
    whatsapp = db.Column(db.String(120))
    email = db.Column(db.String(240))
    email_business = db.Column(db.String(240))
    linkedin_url = db.Column(db.String(700))
    registration_id = db.Column(db.String(120), index=True)
    identity_confidence = db.Column(db.Integer, nullable=False, default=50)
    company_size = db.Column(db.String(80))
    employee_estimate = db.Column(db.Integer)
    facility_profile = db.Column(db.JSON, nullable=False, default=dict)
    account_fit_score = db.Column(db.Integer, nullable=False, default=0)
    accessibility_score = db.Column(db.Integer, nullable=False, default=0)
    momentum_score = db.Column(db.Integer, nullable=False, default=0)
    watch_status = db.Column(db.String(30), nullable=False, default="WATCH", index=True)
    last_signal_at = db.Column(db.DateTime(timezone=True), index=True)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    deleted_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    projects = db.relationship("Project", back_populates="company", cascade="all, delete-orphan")
    aliases = db.relationship("CompanyAlias", back_populates="company", cascade="all, delete-orphan")
    contacts = db.relationship("Contact", back_populates="company", cascade="all, delete-orphan")
    tenant = db.relationship("Tenant")
    __table_args__ = (db.CheckConstraint("identity_confidence BETWEEN 0 AND 100", name="ck_company_identity_confidence"),)


class CompanyAlias(db.Model):
    __tablename__ = "company_aliases"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    alias = db.Column(db.String(220), nullable=False)
    normalized_alias = db.Column(db.String(220), nullable=False, index=True)
    confidence = db.Column(db.Integer, nullable=False, default=100)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    company = db.relationship("Company", back_populates="aliases")
    __table_args__ = (db.UniqueConstraint("tenant_id", "normalized_alias", "company_id", name="uq_company_alias"),)


class Contact(db.Model):
    __tablename__ = "contacts"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(220), nullable=False)
    role = db.Column(db.String(180))
    buying_role = db.Column(db.String(40), nullable=False, default="UNKNOWN", index=True)
    influence_score = db.Column(db.Integer, nullable=False, default=50)
    email = db.Column(db.String(320))
    phone = db.Column(db.String(120))
    whatsapp = db.Column(db.String(120))
    linkedin_url = db.Column(db.String(700))
    source_url = db.Column(db.String(1200))
    confidence = db.Column(db.Integer, nullable=False, default=50)
    verified_at = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    company = db.relationship("Company", back_populates="contacts")
    __table_args__ = (
        db.CheckConstraint("influence_score BETWEEN 0 AND 100", name="ck_contact_influence"),
        db.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_contact_confidence"),
    )


class Watchlist(db.Model):
    __tablename__ = "watchlists"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    priority = db.Column(db.Integer, nullable=False, default=50)
    reason = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    last_checked_at = db.Column(db.DateTime(timezone=True))
    next_check_at = db.Column(db.DateTime(timezone=True), index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    company = db.relationship("Company")
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "company_id", name="uq_watchlist_company"),
        db.CheckConstraint("priority BETWEEN 0 AND 100", name="ck_watchlist_priority"),
    )


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(300), nullable=False)
    normalized_name = db.Column(db.String(300), nullable=False, index=True)
    project_type = db.Column(db.String(100), index=True)
    city = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(120), nullable=False)
    country = db.Column(db.String(80), nullable=False, default="Paraguay", index=True)
    stage = db.Column(db.String(120))
    lifecycle_stage = db.Column(db.String(50), nullable=False, default="DISCOVERED", index=True)
    buying_window_score = db.Column(db.Integer, nullable=False, default=0)
    demand_probability = db.Column(db.Integer, nullable=False, default=0)
    momentum_score = db.Column(db.Integer, nullable=False, default=0)
    estimated_deal_min = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    estimated_deal_max = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    stage_confidence = db.Column(db.Integer, nullable=False, default=0)
    investment = db.Column(db.String(120))
    investment_amount = db.Column(db.Numeric(18, 2))
    investment_currency = db.Column(db.String(3), default="USD")
    area_m2 = db.Column(db.Numeric(14, 2))
    description = db.Column(db.Text)
    announced_at = db.Column(db.DateTime(timezone=True))
    started_at = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    identity_key = db.Column(db.String(64), index=True)
    deleted_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    company = db.relationship("Company", back_populates="projects")
    opportunities = db.relationship("Opportunity", back_populates="project", cascade="all, delete-orphan")
    signals = db.relationship("Signal", back_populates="project")
    evidences = db.relationship("Evidence", back_populates="project")
    tenant = db.relationship("Tenant")
    __table_args__ = (
        db.CheckConstraint("investment_amount IS NULL OR investment_amount >= 0", name="ck_project_investment_amount"),
        db.CheckConstraint("area_m2 IS NULL OR area_m2 >= 0", name="ck_project_area_m2"),
    )


class Opportunity(db.Model):
    __tablename__ = "opportunities"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True)
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
    owner_name = db.Column(db.String(160), nullable=False, default="Equipo comercial", index=True)
    estimated_value = db.Column(db.Float, nullable=False, default=0)
    probability = db.Column(db.Integer, nullable=False, default=20)
    buying_stage = db.Column(db.String(40), nullable=False, default="UNKNOWN", index=True)
    lifecycle_stage = db.Column(db.String(50), nullable=False, default="SALES_READY", index=True)
    buying_window_score = db.Column(db.Integer, nullable=False, default=0)
    accessibility_score = db.Column(db.Integer, nullable=False, default=0)
    momentum_score = db.Column(db.Integer, nullable=False, default=0)
    confidence_score = db.Column(db.Integer, nullable=False, default=0)
    why_now = db.Column(db.Text)
    next_best_action = db.Column(db.Text)
    deal_value_min = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    deal_value_max = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    icp_fit_score = db.Column(db.Integer, nullable=False, default=0)
    intent_score = db.Column(db.Integer, nullable=False, default=0)
    data_confidence = db.Column(db.Integer, nullable=False, default=0)
    potential_deal_value = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    expected_revenue = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    score_version = db.Column(db.String(60), nullable=False, default="legacy-v1")
    discovered_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    project = db.relationship("Project", back_populates="opportunities")
    timeline = db.relationship("TimelineEvent", back_populates="opportunity", cascade="all, delete-orphan")
    tasks = db.relationship("SalesTask", back_populates="opportunity", cascade="all, delete-orphan")
    visits = db.relationship("VisitRecord", back_populates="opportunity", cascade="all, delete-orphan")
    proposals = db.relationship("Proposal", back_populates="opportunity", cascade="all, delete-orphan")
    scores = db.relationship("OpportunityScore", back_populates="opportunity", cascade="all, delete-orphan")
    evidence_links = db.relationship("OpportunityEvidence", back_populates="opportunity", cascade="all, delete-orphan")
    product_matches = db.relationship("ProductMatch", back_populates="opportunity", cascade="all, delete-orphan")
    tenant = db.relationship("Tenant")
    __table_args__ = (
        db.CheckConstraint("score BETWEEN 0 AND 100", name="ck_opportunity_score"),
        db.CheckConstraint("probability BETWEEN 0 AND 100", name="ck_opportunity_probability"),
        db.CheckConstraint("icp_fit_score BETWEEN 0 AND 100", name="ck_opportunity_icp_fit"),
        db.CheckConstraint("intent_score BETWEEN 0 AND 100", name="ck_opportunity_intent"),
        db.CheckConstraint("data_confidence BETWEEN 0 AND 100", name="ck_opportunity_data_confidence"),
    )

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
            "owner": self.owner_name, "estimatedValue": self.estimated_value,
            "probability": self.probability,
            "buyingStage": self.buying_stage, "lifecycleStage": self.lifecycle_stage,
            "buyingWindow": self.buying_window_score, "accessibility": self.accessibility_score,
            "momentum": self.momentum_score, "confidenceScore": self.confidence_score,
            "whyNow": self.why_now, "nextBestAction": self.next_best_action,
            "dealValueMin": float(self.deal_value_min or 0), "dealValueMax": float(self.deal_value_max or 0),
            "icpFit": self.icp_fit_score,
            "intent": self.intent_score, "dataConfidence": self.data_confidence,
            "potentialDealValue": float(self.potential_deal_value or 0),
            "expectedRevenue": float(self.expected_revenue or 0), "scoreVersion": self.score_version,
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


class Source(db.Model):
    __tablename__ = "sources"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(220), nullable=False)
    source_type = db.Column(db.String(50), nullable=False, default="PUBLIC_WEB", index=True)
    base_url = db.Column(db.String(1200))
    domain = db.Column(db.String(255), index=True)
    reliability = db.Column(db.Integer, nullable=False, default=50)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    documents = db.relationship("SourceDocument", back_populates="source", cascade="all, delete-orphan")
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "name", "domain", name="uq_source_identity"),
        db.CheckConstraint("reliability BETWEEN 0 AND 100", name="ck_source_reliability"),
    )


class SourceDocument(db.Model):
    __tablename__ = "source_documents"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = db.Column(db.Integer, db.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True)
    url = db.Column(db.String(1600), nullable=False)
    canonical_url = db.Column(db.String(1600), nullable=False)
    url_hash = db.Column(db.String(64), nullable=False)
    content_hash = db.Column(db.String(64), index=True)
    title = db.Column(db.String(700))
    excerpt = db.Column(db.Text)
    published_at = db.Column(db.DateTime(timezone=True), index=True)
    fetched_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    language = db.Column(db.String(10))
    confidence = db.Column(db.Integer, nullable=False, default=50)
    document_metadata = db.Column(db.JSON, nullable=False, default=dict)
    source = db.relationship("Source", back_populates="documents")
    __table_args__ = (db.UniqueConstraint("tenant_id", "url_hash", name="uq_source_document_url"),)


class Signal(db.Model):
    __tablename__ = "signals"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    source_document_id = db.Column(db.Integer, db.ForeignKey("source_documents.id", ondelete="SET NULL"), index=True)
    signal_type = db.Column(db.String(80), nullable=False, index=True)
    title = db.Column(db.String(700), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    city = db.Column(db.String(120))
    department = db.Column(db.String(120))
    country = db.Column(db.String(80), nullable=False, default="Paraguay", index=True)
    confidence = db.Column(db.Integer, nullable=False, default=50, index=True)
    freshness = db.Column(db.Integer, nullable=False, default=100)
    relevance = db.Column(db.Integer, nullable=False, default=50)
    impact_score = db.Column(db.Integer, nullable=False, default=50)
    buying_window_score = db.Column(db.Integer, nullable=False, default=0)
    lifecycle_stage = db.Column(db.String(50), nullable=False, default="DISCOVERED", index=True)
    causality = db.Column(db.JSON, nullable=False, default=list)
    product_hypothesis = db.Column(db.JSON, nullable=False, default=list)
    fingerprint = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(40), nullable=False, default="DETECTED", index=True)
    detected_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    occurred_at = db.Column(db.DateTime(timezone=True), index=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    company = db.relationship("Company")
    project = db.relationship("Project", back_populates="signals")
    source_document = db.relationship("SourceDocument")
    evidences = db.relationship("Evidence", back_populates="signal")
    __table_args__ = (
        db.UniqueConstraint("tenant_id", "fingerprint", name="uq_signal_fingerprint"),
        db.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_signal_confidence"),
        db.CheckConstraint("freshness BETWEEN 0 AND 100", name="ck_signal_freshness"),
        db.CheckConstraint("relevance BETWEEN 0 AND 100", name="ck_signal_relevance"),
    )


class Evidence(db.Model):
    __tablename__ = "evidences"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    signal_id = db.Column(db.Integer, db.ForeignKey("signals.id", ondelete="SET NULL"), index=True)
    source_document_id = db.Column(db.Integer, db.ForeignKey("source_documents.id", ondelete="RESTRICT"), nullable=False, index=True)
    evidence_type = db.Column(db.String(50), nullable=False, default="SOURCE_CLAIM", index=True)
    classification = db.Column(db.String(20), nullable=False, default="FACT", index=True)
    claim = db.Column(db.Text, nullable=False)
    excerpt = db.Column(db.Text)
    confidence = db.Column(db.Integer, nullable=False, default=50)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    project = db.relationship("Project", back_populates="evidences")
    signal = db.relationship("Signal", back_populates="evidences")
    source_document = db.relationship("SourceDocument")
    opportunity_links = db.relationship("OpportunityEvidence", back_populates="evidence", cascade="all, delete-orphan")
    __table_args__ = (
        db.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_evidence_confidence"),
        db.CheckConstraint("classification IN ('FACT','INFERENCE','PREDICTION')", name="ck_evidence_classification"),
    )


class OpportunityEvidence(db.Model):
    __tablename__ = "opportunity_evidences"
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True)
    evidence_id = db.Column(db.Integer, db.ForeignKey("evidences.id", ondelete="CASCADE"), primary_key=True)
    relevance = db.Column(db.Integer, nullable=False, default=100)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    opportunity = db.relationship("Opportunity", back_populates="evidence_links")
    evidence = db.relationship("Evidence", back_populates="opportunity_links")


class OpportunityScore(db.Model):
    __tablename__ = "opportunity_scores"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    total_score = db.Column(db.Integer, nullable=False, index=True)
    model_version = db.Column(db.String(60), nullable=False, index=True)
    is_current = db.Column(db.Boolean, nullable=False, default=True, index=True)
    calculated_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    opportunity = db.relationship("Opportunity", back_populates="scores")
    factors = db.relationship("ScoreFactor", back_populates="score", cascade="all, delete-orphan")
    __table_args__ = (db.CheckConstraint("total_score BETWEEN 0 AND 100", name="ck_opportunity_score_total"),)


class ScoreFactor(db.Model):
    __tablename__ = "score_factors"
    id = db.Column(db.Integer, primary_key=True)
    score_id = db.Column(db.Integer, db.ForeignKey("opportunity_scores.id", ondelete="CASCADE"), nullable=False, index=True)
    factor_code = db.Column(db.String(60), nullable=False, index=True)
    raw_value = db.Column(db.Numeric(8, 3), nullable=False)
    weight = db.Column(db.Numeric(8, 5), nullable=False)
    points = db.Column(db.Numeric(8, 3), nullable=False)
    explanation = db.Column(db.Text, nullable=False)
    score = db.relationship("OpportunityScore", back_populates="factors")
    __table_args__ = (db.UniqueConstraint("score_id", "factor_code", name="uq_score_factor"),)


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(220), nullable=False)
    normalized_name = db.Column(db.String(220), nullable=False, index=True)
    category = db.Column(db.String(120), index=True)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("tenant_id", "normalized_name", name="uq_product_name"),)


class ProductMatch(db.Model):
    __tablename__ = "product_matches"
    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id = db.Column(db.Integer, db.ForeignKey("evidences.id", ondelete="SET NULL"), index=True)
    fit_score = db.Column(db.Integer, nullable=False)
    confidence = db.Column(db.Integer, nullable=False, default=50)
    rationale = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    opportunity = db.relationship("Opportunity", back_populates="product_matches")
    product = db.relationship("Product")
    evidence = db.relationship("Evidence")
    __table_args__ = (
        db.UniqueConstraint("opportunity_id", "product_id", name="uq_opportunity_product"),
        db.CheckConstraint("fit_score BETWEEN 0 AND 100", name="ck_product_match_fit"),
        db.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_product_match_confidence"),
    )


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=False, index=True)
    entity_id = db.Column(db.String(80))
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class SalesTask(db.Model):
    __tablename__ = "sales_tasks"
    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    channel = db.Column(db.String(40), nullable=False, default="GENERAL", index=True)
    due_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="PENDING", index=True)
    sequence_step = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True))
    opportunity = db.relationship("Opportunity", back_populates="tasks")

    def to_dict(self):
        return {"id": self.id, "opportunityId": self.opportunity_id, "company": self.opportunity.project.company.name,
                "title": self.title, "channel": self.channel, "status": self.status, "step": self.sequence_step,
                "dueAt": self.due_at.isoformat(), "owner": self.opportunity.owner_name}


class VisitRecord(db.Model):
    __tablename__ = "visit_records"
    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    visited_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    measurements = db.Column(db.Text)
    needs = db.Column(db.Text)
    notes = db.Column(db.Text)
    next_step = db.Column(db.Text)
    photos = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    opportunity = db.relationship("Opportunity", back_populates="visits")


class Proposal(db.Model):
    __tablename__ = "proposals"
    id = db.Column(db.Integer, primary_key=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    number = db.Column(db.String(60), unique=True, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    validity_days = db.Column(db.Integer, nullable=False, default=15)
    scope = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="DRAFT", index=True)
    pdf_filename = db.Column(db.String(300))
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    opportunity = db.relationship("Opportunity", back_populates="proposals")


class ProspectSignal(db.Model):
    __tablename__ = "prospect_signals"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    fingerprint = db.Column(db.String(64), nullable=False, index=True)
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
    buying_window_score = db.Column(db.Integer, nullable=False, default=0)
    lifecycle_stage = db.Column(db.String(50), nullable=False, default="DISCOVERED", index=True)
    momentum_delta = db.Column(db.Integer, nullable=False, default=0)
    demand_probability = db.Column(db.Integer, nullable=False, default=0)
    causality = db.Column(db.JSON, default=list, nullable=False)
    estimated_deal_min = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    estimated_deal_max = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    why_now = db.Column(db.Text)
    status = db.Column(db.String(40), nullable=False, default="PENDING_VALIDATION", index=True)
    opportunity_id = db.Column(db.Integer, db.ForeignKey("opportunities.id", ondelete="SET NULL"), index=True)
    discovered_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    opportunity = db.relationship("Opportunity")
    __table_args__ = (db.UniqueConstraint("tenant_id", "fingerprint", name="uq_prospect_signal_tenant_fingerprint"),)

    def to_dict(self):
        return {
            "id": self.id, "company": self.company_name, "title": self.title, "summary": self.summary,
            "sourceName": self.source_name, "sourceUrl": self.source_url, "sourceType": self.source_type,
            "reliability": self.source_reliability, "publishedAt": self.published_at.isoformat() if self.published_at else None,
            "city": self.city, "department": self.department, "event": self.event_type, "score": self.score,
            "level": self.level, "products": self.products or [], "reasons": self.reasons or [],
            "buyingWindow": self.buying_window_score, "lifecycleStage": self.lifecycle_stage,
            "momentumDelta": self.momentum_delta, "demandProbability": self.demand_probability,
            "causality": self.causality or [], "estimatedDealMin": float(self.estimated_deal_min or 0),
            "estimatedDealMax": float(self.estimated_deal_max or 0), "whyNow": self.why_now,
            "status": self.status, "opportunityId": self.opportunity_id,
            "discoveredAt": self.discovered_at.isoformat() if self.discovered_at else None,
        }


class CollectorRun(db.Model):
    __tablename__ = "collector_runs"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
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
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
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
