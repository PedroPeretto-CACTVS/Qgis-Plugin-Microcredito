"""Create schema v3 tables, indexes, and active-import views."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from database.models import Base
from database.schema import ACTIVE_VIEW_TABLES, SCHEMA_VERSION

revision: str = "001_schema_v3"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)
    for table in ACTIVE_VIEW_TABLES:
        op.execute(
            f"""CREATE VIEW IF NOT EXISTS ativo_{table} AS
            SELECT t.* FROM {table} t JOIN importacao i ON i.id = t.importacao_id
            WHERE i.ativo = 1"""
        )
    op.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def downgrade() -> None:
    for table in ACTIVE_VIEW_TABLES:
        op.execute(f"DROP VIEW IF EXISTS ativo_{table}")
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
