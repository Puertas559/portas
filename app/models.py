from datetime import datetime, timezone
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
    discovered_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    project = db.relationship("Project", back_populates="opportunities")
    timeline = db.relationship("TimelineEvent", back_populates="opportunity", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "company": self.project.company.name, "sector": self.project.company.sector or "No informado",
            "origin": self.project.company.origin_country or "No informado", "project": self.project.name,
            "city": self.project.city, "department": self.project.department, "stage": self.project.stage or "No informado",
            "investment": self.project.investment or "No divulgado", "event": self.event_type, "score": self.score,
            "level": self.level, "status": self.status, "products": self.products or [], "evidence": self.evidence,
            "sourceName": self.source_name, "sourceUrl": self.source_url,
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
