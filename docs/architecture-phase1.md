# Industrial Revenue Radar — Architecture Assessment and Phase 1

## Current assessment

The existing product is a Flask 3 application served by Gunicorn, with SQLAlchemy, Alembic/Flask-Migrate, PostgreSQL on Railway and `/data` for persistent files. It already delivers a useful vertical slice: public company search, automated prospecting, website qualification, opportunity scoring, CRM stages, sales tasks, visits and PDF proposals.

The original schema (`companies`, `projects`, `opportunities`, `timeline_events`) correctly established the commercial hierarchy, but source, evidence and score were flattened into columns on `opportunities`. Company resolution depended on an exact raw name and each discovery created a new project. That could duplicate the same company or project when independent sources reported it.

## What is preserved

- Every existing Alembic revision and its data.
- Existing URLs and JSON contracts used by the current frontend.
- The current CRM, tasks, visits, proposals, collector and website analyzer.
- Flask, SQLAlchemy, PostgreSQL, Gunicorn, Railway and `/data`.
- Legacy `evidence`, `source_name`, `source_url`, `score` and `level` columns during the transition.

## Phase 1 target architecture

The additive revision `7a91f3c2d640` introduces:

- `tenants`, `users`: workspace isolation and session authentication.
- `company_aliases`: alternate names resolved to a canonical company.
- expanded `companies`: canonical/normalized identity, domain, geography, business contacts, status and soft deletion.
- expanded `projects`: normalized identity, project type, geography, numeric investment, area and lifecycle dates.
- `sources`, `source_documents`: normalized provenance with URL/content hashes.
- `signals`: project/company events with confidence, freshness, relevance and a tenant-scoped fingerprint.
- `evidences`, `opportunity_evidences`: fact/inference/prediction claims and many-to-many opportunity evidence.
- `opportunity_scores`, `score_factors`: versioned and explainable scoring.
- `products`, `product_matches`: explicit product fit and rationale.
- `audit_logs`: security-sensitive activity foundation.

The application follows this traceable path:

`tenant → company → project → signal → source document → evidence → opportunity → score factors → product match → CRM timeline`

## Identity and deduplication

Company resolution does not use the raw name alone. It considers registration ID, domain, normalized name within country, aliases and a conservative similarity check constrained by geography. Project resolution uses company, normalized project name, city and project type to build a stable identity fingerprint.

Source documents use canonical URL hashes. Signals use a tenant-scoped fingerprint containing project, signal type, document and claim. A repeated discovery reuses the canonical company/project/source/document and does not create a second opportunity from the exact same evidence.

## Safe migration sequence

1. Create the default tenant without changing the original migration.
2. Add nullable identity columns and tenant foreign keys with safe defaults.
3. Backfill current companies, projects and opportunities.
4. Remove raw-name uniqueness and create non-unique normalized indexes.
5. Create source, signal, evidence, scoring and product tables.
6. Backfill every legacy opportunity into a source document, signal, evidence link and explainable legacy score.
7. Keep legacy fields available while the application writes the normalized structure.
8. Validate counts, foreign keys, tenant ownership and traceability before any later cleanup.

No destructive cleanup of the legacy columns is part of Phase 1.

## Authentication and permissions

Authentication is session-based and uses Werkzeug password hashes. Roles are `ADMIN`, `MANAGER`, `SALES` and `VIEWER`, with explicit permission checks. Authentication is deployed in compatibility mode and is enabled only after Railway receives `ADMIN_EMAIL`, `ADMIN_PASSWORD`, a strong `SECRET_KEY` and `AUTH_REQUIRED=true`.

## Technical risks and mitigations

- **False entity merges:** conservative matching, aliases and confidence; no unique constraint on normalized company name.
- **Duplicate projects:** stable project identity plus exact fallback matching.
- **Migration of live rows:** additive columns, deterministic backfill and preservation tests from the previous Alembic head.
- **Tenant data leakage:** core queries are filtered by the current tenant and covered by isolation tests.
- **Opaque scoring:** all nine components, weights, points, explanation and model version are stored.
- **AI hallucination:** evidence classification explicitly distinguishes `FACT`, `INFERENCE` and `PREDICTION`.
- **Authentication lockout:** authentication stays disabled until administrator variables are configured.
- **Long-running collection:** the current lightweight scheduler remains compatible; a real external job queue is a Phase 4 concern.

## Refactoring priorities after Phase 1

1. Split the large API module into company, project, signal, opportunity, CRM and analytics blueprints.
2. Move collection from in-process scheduling to a Railway worker/job queue.
3. Add contact, activity, outreach, pipeline-stage and deal entities in Phase 3.
4. Replace hardcoded UI strings with translation catalogs in the internationalization phase.
5. Introduce structured logging, source health and job observability before scaling ingestion.

## Phase 1 definition of done

- Existing behavior remains operational.
- Fresh and previous-head migrations upgrade successfully.
- Existing opportunities are backfilled into traceable evidence and scores.
- Entity/project/source deduplication has automated tests.
- Scoring is versioned and explainable.
- Authentication, role permission and tenant isolation are tested.
- The production deployment continues to use PostgreSQL and `/data`.
