"""phase 1 revenue intelligence foundation

Revision ID: 7a91f3c2d640
Revises: 5c8d21a09f42
"""
from alembic import op
import sqlalchemy as sa
import hashlib
from urllib.parse import urlparse


revision = "7a91f3c2d640"
down_revision = "5c8d21a09f42"
branch_labels = None
depends_on = None


def _index(table, name, columns, unique=False):
    op.create_index(name, table, columns, unique=unique)


def _backfill_intelligence():
    connection = op.get_bind()
    rows = connection.execute(sa.text("""
        SELECT o.id AS opportunity_id, o.tenant_id, o.event_type, o.score, o.evidence,
               o.source_name, o.source_url, o.discovered_at, p.id AS project_id,
               p.name AS project_name, p.city, p.department, p.country, c.id AS company_id
        FROM opportunities o
        JOIN projects p ON p.id=o.project_id
        JOIN companies c ON c.id=p.company_id
    """)).mappings().all()
    weights = {
        "ICP_FIT": 0.18, "INTENT": 0.22, "TIMING": 0.12, "PROJECT_VALUE": 0.10,
        "PRODUCT_FIT": 0.14, "GEOGRAPHIC_FIT": 0.08, "DATA_CONFIDENCE": 0.08,
        "SIGNAL_RECENCY": 0.05, "COMMERCIAL_HISTORY": 0.03,
    }
    for row in rows:
        source_name = row["source_name"] or "Fuente histórica"
        source_url = row["source_url"] or f"https://evidence.local/legacy/{row['opportunity_id']}"
        domain = (urlparse(source_url).hostname or "evidence.local").lower().removeprefix("www.")
        source_id = connection.execute(sa.text(
            "SELECT id FROM sources WHERE tenant_id=:tenant_id AND name=:name AND domain=:domain"
        ), {"tenant_id": row["tenant_id"], "name": source_name, "domain": domain}).scalar()
        if not source_id:
            result = connection.execute(sa.text("""
                INSERT INTO sources (tenant_id,name,source_type,base_url,domain,reliability,status,created_at,updated_at)
                VALUES (:tenant_id,:name,'LEGACY',:base_url,:domain,50,'ACTIVE',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            """), {"tenant_id": row["tenant_id"], "name": source_name, "base_url": f"https://{domain}", "domain": domain})
            source_id = result.lastrowid
            if not source_id:
                source_id = connection.execute(sa.text(
                    "SELECT id FROM sources WHERE tenant_id=:tenant_id AND name=:name AND domain=:domain"
                ), {"tenant_id": row["tenant_id"], "name": source_name, "domain": domain}).scalar()
        url_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
        document_id = connection.execute(sa.text(
            "SELECT id FROM source_documents WHERE tenant_id=:tenant_id AND url_hash=:url_hash"
        ), {"tenant_id": row["tenant_id"], "url_hash": url_hash}).scalar()
        if not document_id:
            result = connection.execute(sa.text("""
                INSERT INTO source_documents
                (tenant_id,source_id,url,canonical_url,url_hash,content_hash,title,excerpt,confidence,document_metadata,fetched_at)
                VALUES (:tenant_id,:source_id,:url,:url,:url_hash,:content_hash,:title,:excerpt,50,'{}',CURRENT_TIMESTAMP)
            """), {
                "tenant_id": row["tenant_id"], "source_id": source_id, "url": source_url, "url_hash": url_hash,
                "content_hash": hashlib.sha256((row["evidence"] or "").encode("utf-8")).hexdigest(),
                "title": row["project_name"], "excerpt": row["evidence"],
            })
            document_id = result.lastrowid
            if not document_id:
                document_id = connection.execute(sa.text(
                    "SELECT id FROM source_documents WHERE tenant_id=:tenant_id AND url_hash=:url_hash"
                ), {"tenant_id": row["tenant_id"], "url_hash": url_hash}).scalar()
        fingerprint = hashlib.sha256(f"legacy|{row['opportunity_id']}|{url_hash}".encode("utf-8")).hexdigest()
        result = connection.execute(sa.text("""
            INSERT INTO signals
            (tenant_id,company_id,project_id,source_document_id,signal_type,title,summary,city,department,country,
             confidence,freshness,relevance,fingerprint,status,detected_at,updated_at)
            VALUES (:tenant_id,:company_id,:project_id,:document_id,:signal_type,:title,:summary,:city,:department,:country,
                    50,100,70,:fingerprint,'MIGRATED',:detected_at,CURRENT_TIMESTAMP)
        """), {
            "tenant_id": row["tenant_id"], "company_id": row["company_id"], "project_id": row["project_id"],
            "document_id": document_id, "signal_type": row["event_type"], "title": row["project_name"],
            "summary": row["evidence"], "city": row["city"], "department": row["department"],
            "country": row["country"], "fingerprint": fingerprint, "detected_at": row["discovered_at"],
        })
        signal_id = result.lastrowid
        if not signal_id:
            signal_id = connection.execute(sa.text(
                "SELECT id FROM signals WHERE tenant_id=:tenant_id AND fingerprint=:fingerprint"
            ), {"tenant_id": row["tenant_id"], "fingerprint": fingerprint}).scalar()
        result = connection.execute(sa.text("""
            INSERT INTO evidences
            (tenant_id,project_id,signal_id,source_document_id,evidence_type,classification,claim,excerpt,confidence,created_at)
            VALUES (:tenant_id,:project_id,:signal_id,:document_id,'SOURCE_CLAIM','FACT',:claim,:claim,50,CURRENT_TIMESTAMP)
        """), {"tenant_id": row["tenant_id"], "project_id": row["project_id"], "signal_id": signal_id, "document_id": document_id, "claim": row["evidence"]})
        evidence_id = result.lastrowid
        if not evidence_id:
            evidence_id = connection.execute(sa.text("SELECT max(id) FROM evidences")).scalar()
        connection.execute(sa.text("""
            INSERT INTO opportunity_evidences (opportunity_id,evidence_id,relevance,created_at)
            VALUES (:opportunity_id,:evidence_id,100,CURRENT_TIMESTAMP)
        """), {"opportunity_id": row["opportunity_id"], "evidence_id": evidence_id})
        result = connection.execute(sa.text("""
            INSERT INTO opportunity_scores (tenant_id,opportunity_id,total_score,model_version,is_current,calculated_at)
            VALUES (:tenant_id,:opportunity_id,:score,'legacy-v1',true,CURRENT_TIMESTAMP)
        """), {"tenant_id": row["tenant_id"], "opportunity_id": row["opportunity_id"], "score": row["score"]})
        score_id = result.lastrowid
        if not score_id:
            score_id = connection.execute(sa.text("SELECT max(id) FROM opportunity_scores")).scalar()
        for code, weight in weights.items():
            connection.execute(sa.text("""
                INSERT INTO score_factors (score_id,factor_code,raw_value,weight,points,explanation)
                VALUES (:score_id,:code,:value,:weight,:points,:explanation)
            """), {
                "score_id": score_id, "code": code, "value": row["score"], "weight": weight,
                "points": round(row["score"] * weight, 3),
                "explanation": f"Valor histórico migrado; requiere recálculo con el modelo {code}.",
            })


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(220), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _index("tenants", "ix_tenants_slug", ["slug"], unique=True)
    _index("tenants", "ix_tenants_status", ["status"])
    tenants = sa.table(
        "tenants", sa.column("id", sa.Integer()), sa.column("name", sa.String()),
        sa.column("slug", sa.String()), sa.column("status", sa.String()), sa.column("settings", sa.JSON()),
    )
    op.bulk_insert(tenants, [{
        "id": 1, "name": "Puertas Brasil PY", "slug": "puertas-brasil-py", "status": "ACTIVE",
        "settings": {
            "brand_name": "Puertas Brasil PY", "default_country": "Paraguay",
            "scoring_model_version": "phase1-v1",
            "scoring_weights": {
                "ICP_FIT": 0.18, "INTENT": 0.22, "TIMING": 0.12, "PROJECT_VALUE": 0.10,
                "PRODUCT_FIT": 0.14, "GEOGRAPHIC_FIT": 0.08, "DATA_CONFIDENCE": 0.08,
                "SIGNAL_RECENCY": 0.05, "COMMERCIAL_HISTORY": 0.03,
            },
        },
    }])

    with op.batch_alter_table("companies") as batch:
        batch.drop_index("ix_companies_name")
        batch.create_index("ix_companies_name", ["name"], unique=False)
        batch.add_column(sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("canonical_name", sa.String(220), nullable=True))
        batch.add_column(sa.Column("normalized_name", sa.String(220), nullable=True))
        batch.add_column(sa.Column("domain", sa.String(255)))
        batch.add_column(sa.Column("city", sa.String(120)))
        batch.add_column(sa.Column("department", sa.String(120)))
        batch.add_column(sa.Column("country", sa.String(80), nullable=False, server_default="Paraguay"))
        batch.add_column(sa.Column("description", sa.Text()))
        batch.add_column(sa.Column("phone_business", sa.String(120)))
        batch.add_column(sa.Column("email_business", sa.String(240)))
        batch.add_column(sa.Column("registration_id", sa.String(120)))
        batch.add_column(sa.Column("identity_confidence", sa.Integer(), nullable=False, server_default="50"))
        batch.add_column(sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key("fk_companies_tenant", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_companies_tenant_id", ["tenant_id"])
        batch.create_index("ix_companies_normalized_name", ["normalized_name"])
        batch.create_index("ix_companies_domain", ["domain"])
        batch.create_index("ix_companies_country", ["country"])
        batch.create_index("ix_companies_registration_id", ["registration_id"])
        batch.create_index("ix_companies_status", ["status"])
    op.execute("UPDATE companies SET canonical_name=name, normalized_name=lower(trim(name)), country=coalesce(origin_country, 'Paraguay'), phone_business=phone, email_business=email")
    with op.batch_alter_table("companies") as batch:
        batch.alter_column("canonical_name", nullable=False)
        batch.alter_column("normalized_name", nullable=False)
        batch.create_check_constraint("ck_company_identity_confidence", "identity_confidence BETWEEN 0 AND 100")

    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("normalized_name", sa.String(300), nullable=True))
        batch.add_column(sa.Column("project_type", sa.String(100)))
        batch.add_column(sa.Column("country", sa.String(80), nullable=False, server_default="Paraguay"))
        batch.add_column(sa.Column("investment_amount", sa.Numeric(18, 2)))
        batch.add_column(sa.Column("investment_currency", sa.String(3), server_default="USD"))
        batch.add_column(sa.Column("area_m2", sa.Numeric(14, 2)))
        batch.add_column(sa.Column("description", sa.Text()))
        batch.add_column(sa.Column("announced_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"))
        batch.add_column(sa.Column("identity_key", sa.String(64)))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key("fk_projects_tenant", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_projects_tenant_id", ["tenant_id"])
        batch.create_index("ix_projects_normalized_name", ["normalized_name"])
        batch.create_index("ix_projects_project_type", ["project_type"])
        batch.create_index("ix_projects_country", ["country"])
        batch.create_index("ix_projects_status", ["status"])
        batch.create_index("ix_projects_identity_key", ["identity_key"])
    op.execute("UPDATE projects SET normalized_name=lower(trim(name)), tenant_id=(SELECT tenant_id FROM companies WHERE companies.id=projects.company_id)")
    with op.batch_alter_table("projects") as batch:
        batch.alter_column("normalized_name", nullable=False)
        batch.create_check_constraint("ck_project_investment_amount", "investment_amount IS NULL OR investment_amount >= 0")
        batch.create_check_constraint("ck_project_area_m2", "area_m2 IS NULL OR area_m2 >= 0")

    with op.batch_alter_table("opportunities") as batch:
        batch.add_column(sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("buying_stage", sa.String(40), nullable=False, server_default="UNKNOWN"))
        batch.add_column(sa.Column("icp_fit_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("intent_score", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("data_confidence", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("potential_deal_value", sa.Numeric(18, 2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("expected_revenue", sa.Numeric(18, 2), nullable=False, server_default="0"))
        batch.add_column(sa.Column("score_version", sa.String(60), nullable=False, server_default="legacy-v1"))
        batch.create_foreign_key("fk_opportunities_tenant", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_opportunities_tenant_id", ["tenant_id"])
        batch.create_index("ix_opportunities_buying_stage", ["buying_stage"])
    op.execute("UPDATE opportunities SET tenant_id=(SELECT tenant_id FROM projects WHERE projects.id=opportunities.project_id), icp_fit_score=score, intent_score=score, data_confidence=50, potential_deal_value=estimated_value, expected_revenue=estimated_value * probability / 100.0")
    with op.batch_alter_table("opportunities") as batch:
        batch.create_check_constraint("ck_opportunity_score", "score BETWEEN 0 AND 100")
        batch.create_check_constraint("ck_opportunity_probability", "probability BETWEEN 0 AND 100")
        batch.create_check_constraint("ck_opportunity_icp_fit", "icp_fit_score BETWEEN 0 AND 100")
        batch.create_check_constraint("ck_opportunity_intent", "intent_score BETWEEN 0 AND 100")
        batch.create_check_constraint("ck_opportunity_data_confidence", "data_confidence BETWEEN 0 AND 100")

    for table_name in ("prospect_signals", "collector_runs", "website_analyses"):
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(sa.Column("tenant_id", sa.Integer(), nullable=False, server_default="1"))
            batch.create_foreign_key(f"fk_{table_name}_tenant", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
            batch.create_index(f"ix_{table_name}_tenant_id", ["tenant_id"])
    with op.batch_alter_table("prospect_signals") as batch:
        batch.drop_index("ix_prospect_signals_fingerprint")
        batch.create_index("ix_prospect_signals_fingerprint", ["fingerprint"], unique=False)
        batch.create_unique_constraint("uq_prospect_signal_tenant_fingerprint", ["tenant_id", "fingerprint"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(500), nullable=False),
        sa.Column("role", sa.String(40), nullable=False, server_default="ADMIN"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "normalized_email", name="uq_users_tenant_email"),
    )
    for name, cols in (("ix_users_tenant_id", ["tenant_id"]), ("ix_users_role", ["role"]), ("ix_users_status", ["status"])):
        _index("users", name, cols)

    op.create_table(
        "company_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(220), nullable=False),
        sa.Column("normalized_alias", sa.String(220), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "normalized_alias", "company_id", name="uq_company_alias"),
    )
    for name, cols in (("ix_company_aliases_tenant_id", ["tenant_id"]), ("ix_company_aliases_company_id", ["company_id"]), ("ix_company_aliases_normalized_alias", ["normalized_alias"])):
        _index("company_aliases", name, cols)

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(220), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False, server_default="PUBLIC_WEB"),
        sa.Column("base_url", sa.String(1200)), sa.Column("domain", sa.String(255)),
        sa.Column("reliability", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", "domain", name="uq_source_identity"),
        sa.CheckConstraint("reliability BETWEEN 0 AND 100", name="ck_source_reliability"),
    )
    for name, cols in (("ix_sources_tenant_id", ["tenant_id"]), ("ix_sources_source_type", ["source_type"]), ("ix_sources_domain", ["domain"]), ("ix_sources_status", ["status"])):
        _index("sources", name, cols)

    op.create_table(
        "source_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(1600), nullable=False), sa.Column("canonical_url", sa.String(1600), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False), sa.Column("content_hash", sa.String(64)),
        sa.Column("title", sa.String(700)), sa.Column("excerpt", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("language", sa.String(10)), sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("document_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("tenant_id", "url_hash", name="uq_source_document_url"),
    )
    for name, cols in (("ix_source_documents_tenant_id", ["tenant_id"]), ("ix_source_documents_source_id", ["source_id"]), ("ix_source_documents_content_hash", ["content_hash"]), ("ix_source_documents_published_at", ["published_at"]), ("ix_source_documents_fetched_at", ["fetched_at"])):
        _index("source_documents", name, cols)

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="SET NULL")),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("source_documents.id", ondelete="SET NULL")),
        sa.Column("signal_type", sa.String(80), nullable=False), sa.Column("title", sa.String(700), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False), sa.Column("city", sa.String(120)), sa.Column("department", sa.String(120)),
        sa.Column("country", sa.String(80), nullable=False, server_default="Paraguay"),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("freshness", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("relevance", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="DETECTED"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "fingerprint", name="uq_signal_fingerprint"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_signal_confidence"),
        sa.CheckConstraint("freshness BETWEEN 0 AND 100", name="ck_signal_freshness"),
        sa.CheckConstraint("relevance BETWEEN 0 AND 100", name="ck_signal_relevance"),
    )
    for name, cols in (("ix_signals_tenant_id", ["tenant_id"]), ("ix_signals_company_id", ["company_id"]), ("ix_signals_project_id", ["project_id"]), ("ix_signals_source_document_id", ["source_document_id"]), ("ix_signals_signal_type", ["signal_type"]), ("ix_signals_country", ["country"]), ("ix_signals_confidence", ["confidence"]), ("ix_signals_status", ["status"]), ("ix_signals_detected_at", ["detected_at"]), ("ix_signals_occurred_at", ["occurred_at"])):
        _index("signals", name, cols)

    op.create_table(
        "evidences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id", ondelete="SET NULL")),
        sa.Column("source_document_id", sa.Integer(), sa.ForeignKey("source_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("evidence_type", sa.String(50), nullable=False, server_default="SOURCE_CLAIM"),
        sa.Column("classification", sa.String(20), nullable=False, server_default="FACT"),
        sa.Column("claim", sa.Text(), nullable=False), sa.Column("excerpt", sa.Text()),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_evidence_confidence"),
        sa.CheckConstraint("classification IN ('FACT','INFERENCE','PREDICTION')", name="ck_evidence_classification"),
    )
    for name, cols in (("ix_evidences_tenant_id", ["tenant_id"]), ("ix_evidences_project_id", ["project_id"]), ("ix_evidences_signal_id", ["signal_id"]), ("ix_evidences_source_document_id", ["source_document_id"]), ("ix_evidences_evidence_type", ["evidence_type"]), ("ix_evidences_classification", ["classification"])):
        _index("evidences", name, cols)

    op.create_table(
        "opportunity_evidences",
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidences.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("relevance", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "opportunity_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False), sa.Column("model_version", sa.String(60), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("total_score BETWEEN 0 AND 100", name="ck_opportunity_score_total"),
    )
    for name, cols in (("ix_opportunity_scores_tenant_id", ["tenant_id"]), ("ix_opportunity_scores_opportunity_id", ["opportunity_id"]), ("ix_opportunity_scores_total_score", ["total_score"]), ("ix_opportunity_scores_model_version", ["model_version"]), ("ix_opportunity_scores_is_current", ["is_current"]), ("ix_opportunity_scores_calculated_at", ["calculated_at"])):
        _index("opportunity_scores", name, cols)

    op.create_table(
        "score_factors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("score_id", sa.Integer(), sa.ForeignKey("opportunity_scores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("factor_code", sa.String(60), nullable=False), sa.Column("raw_value", sa.Numeric(8, 3), nullable=False),
        sa.Column("weight", sa.Numeric(8, 5), nullable=False), sa.Column("points", sa.Numeric(8, 3), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.UniqueConstraint("score_id", "factor_code", name="uq_score_factor"),
    )
    _index("score_factors", "ix_score_factors_score_id", ["score_id"])
    _index("score_factors", "ix_score_factors_factor_code", ["factor_code"])

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(220), nullable=False), sa.Column("normalized_name", sa.String(220), nullable=False),
        sa.Column("category", sa.String(120)), sa.Column("status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "normalized_name", name="uq_product_name"),
    )
    for name, cols in (("ix_products_tenant_id", ["tenant_id"]), ("ix_products_normalized_name", ["normalized_name"]), ("ix_products_category", ["category"]), ("ix_products_status", ["status"])):
        _index("products", name, cols)

    op.create_table(
        "product_matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("opportunity_id", sa.Integer(), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidences.id", ondelete="SET NULL")),
        sa.Column("fit_score", sa.Integer(), nullable=False), sa.Column("confidence", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("opportunity_id", "product_id", name="uq_opportunity_product"),
        sa.CheckConstraint("fit_score BETWEEN 0 AND 100", name="ck_product_match_fit"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_product_match_confidence"),
    )
    for name, cols in (("ix_product_matches_opportunity_id", ["opportunity_id"]), ("ix_product_matches_product_id", ["product_id"]), ("ix_product_matches_evidence_id", ["evidence_id"])):
        _index("product_matches", name, cols)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(100), nullable=False), sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(80)), sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for name, cols in (("ix_audit_logs_tenant_id", ["tenant_id"]), ("ix_audit_logs_user_id", ["user_id"]), ("ix_audit_logs_action", ["action"]), ("ix_audit_logs_entity_type", ["entity_type"]), ("ix_audit_logs_created_at", ["created_at"])):
        _index("audit_logs", name, cols)
    _backfill_intelligence()


def downgrade():
    for table in ("audit_logs", "product_matches", "products", "score_factors", "opportunity_scores", "opportunity_evidences", "evidences", "signals", "source_documents", "sources", "company_aliases", "users"):
        op.drop_table(table)
    for table_name in ("website_analyses", "collector_runs", "prospect_signals"):
        with op.batch_alter_table(table_name) as batch:
            if table_name == "prospect_signals":
                batch.drop_constraint("uq_prospect_signal_tenant_fingerprint", type_="unique")
                batch.drop_index("ix_prospect_signals_fingerprint")
                batch.create_index("ix_prospect_signals_fingerprint", ["fingerprint"], unique=True)
            batch.drop_index(f"ix_{table_name}_tenant_id")
            batch.drop_constraint(f"fk_{table_name}_tenant", type_="foreignkey")
            batch.drop_column("tenant_id")
    with op.batch_alter_table("opportunities") as batch:
        for constraint in ("ck_opportunity_score", "ck_opportunity_probability", "ck_opportunity_icp_fit", "ck_opportunity_intent", "ck_opportunity_data_confidence"):
            batch.drop_constraint(constraint, type_="check")
        batch.drop_index("ix_opportunities_buying_stage")
        batch.drop_index("ix_opportunities_tenant_id")
        batch.drop_constraint("fk_opportunities_tenant", type_="foreignkey")
        for column in ("score_version", "expected_revenue", "potential_deal_value", "data_confidence", "intent_score", "icp_fit_score", "buying_stage", "tenant_id"):
            batch.drop_column(column)
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("ck_project_investment_amount", type_="check")
        batch.drop_constraint("ck_project_area_m2", type_="check")
        for index in ("ix_projects_identity_key", "ix_projects_status", "ix_projects_country", "ix_projects_project_type", "ix_projects_normalized_name", "ix_projects_tenant_id"):
            batch.drop_index(index)
        batch.drop_constraint("fk_projects_tenant", type_="foreignkey")
        for column in ("deleted_at", "identity_key", "status", "started_at", "announced_at", "description", "area_m2", "investment_currency", "investment_amount", "country", "project_type", "normalized_name", "tenant_id"):
            batch.drop_column(column)
    with op.batch_alter_table("companies") as batch:
        batch.drop_constraint("ck_company_identity_confidence", type_="check")
        for index in ("ix_companies_status", "ix_companies_registration_id", "ix_companies_country", "ix_companies_domain", "ix_companies_normalized_name", "ix_companies_tenant_id"):
            batch.drop_index(index)
        batch.drop_constraint("fk_companies_tenant", type_="foreignkey")
        for column in ("deleted_at", "status", "identity_confidence", "registration_id", "email_business", "phone_business", "description", "country", "department", "city", "domain", "normalized_name", "canonical_name", "tenant_id"):
            batch.drop_column(column)
        batch.drop_index("ix_companies_name")
        batch.create_index("ix_companies_name", ["name"], unique=True)
    op.drop_table("tenants")
