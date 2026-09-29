"""Add the official INCRA fiscal-module catalog."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from qgis_plugin_microcredito.domain.fiscal_modules import (
    SOURCE_DATE,
    SOURCE_RULE,
    SOURCE_URL,
    fiscal_module_rows,
)

revision: str = "002_incra_fiscal_modules"
down_revision: str | None = "001_schema_v3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        """CREATE TABLE IF NOT EXISTS incra_modulo_fiscal (
               codigo_municipio TEXT PRIMARY KEY
                   CHECK (length(codigo_municipio) = 7),
               modulo_fiscal_ha INTEGER NOT NULL
                   CHECK (modulo_fiscal_ha > 0),
               norma_fonte TEXT NOT NULL,
               fonte_url TEXT NOT NULL,
               data_referencia TEXT NOT NULL
           )"""
    )
    bind.exec_driver_sql(
        """INSERT INTO incra_modulo_fiscal
           (codigo_municipio, modulo_fiscal_ha, norma_fonte, fonte_url,
            data_referencia)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(codigo_municipio) DO UPDATE SET
               modulo_fiscal_ha = excluded.modulo_fiscal_ha,
               norma_fonte = excluded.norma_fonte,
               fonte_url = excluded.fonte_url,
               data_referencia = excluded.data_referencia""",
        [
            (code, hectares, SOURCE_RULE, SOURCE_URL, SOURCE_DATE)
            for code, hectares in fiscal_module_rows()
        ],
    )
    bind.exec_driver_sql("PRAGMA user_version = 4")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS incra_modulo_fiscal")
    op.execute("PRAGMA user_version = 3")
