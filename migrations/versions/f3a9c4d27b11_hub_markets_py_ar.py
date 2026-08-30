"""isolate HUB Event Intelligence by market PY/AR

Revision ID: f3a9c4d27b11
Revises: ed24b6c19f01
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a9c4d27b11"
down_revision = "ed24b6c19f01"
branch_labels = None
depends_on = None

TABLES = ("hub_event_sources", "hub_events", "hub_event_accounts", "hub_event_actions")


def _has_column(inspector, table, column):
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for table in TABLES:
        if table in existing and not _has_column(inspector, table, "market_code"):
            op.add_column(table, sa.Column("market_code", sa.String(length=2), nullable=False, server_default="PY"))
            op.create_index(f"ix_{table}_market_code", table, ["market_code"])

    # Existing HUB data belongs to Paraguay.
    for table in TABLES:
        if table in existing:
            op.execute(sa.text(f"UPDATE {table} SET market_code='PY' WHERE market_code IS NULL OR market_code=''"))

    if "hub_event_sources" in existing:
        names = {u.get("name") for u in sa.inspect(bind).get_unique_constraints("hub_event_sources")}
        if "uq_hub_source_url" in names:
            op.drop_constraint("uq_hub_source_url", "hub_event_sources", type_="unique")
        names = {u.get("name") for u in sa.inspect(bind).get_unique_constraints("hub_event_sources")}
        if "uq_hub_source_market_url" not in names:
            op.create_unique_constraint("uq_hub_source_market_url", "hub_event_sources", ["tenant_id", "market_code", "url"])

    if "hub_events" in existing:
        names = {u.get("name") for u in sa.inspect(bind).get_unique_constraints("hub_events")}
        if "uq_hub_event_key" in names:
            op.drop_constraint("uq_hub_event_key", "hub_events", type_="unique")
        names = {u.get("name") for u in sa.inspect(bind).get_unique_constraints("hub_events")}
        if "uq_hub_event_market_key" not in names:
            op.create_unique_constraint("uq_hub_event_market_key", "hub_events", ["tenant_id", "market_code", "normalized_key"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    if "hub_event_sources" in existing:
        try: op.drop_constraint("uq_hub_source_market_url", "hub_event_sources", type_="unique")
        except Exception: pass
        try: op.create_unique_constraint("uq_hub_source_url", "hub_event_sources", ["tenant_id", "url"])
        except Exception: pass
    if "hub_events" in existing:
        try: op.drop_constraint("uq_hub_event_market_key", "hub_events", type_="unique")
        except Exception: pass
        try: op.create_unique_constraint("uq_hub_event_key", "hub_events", ["tenant_id", "normalized_key"])
        except Exception: pass
    for table in reversed(TABLES):
        if table in existing and _has_column(sa.inspect(bind), table, "market_code"):
            try: op.drop_index(f"ix_{table}_market_code", table_name=table)
            except Exception: pass
            op.drop_column(table, "market_code")
