"""Validate the standalone database shared by publisher and copy installer."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from database.schema import SCHEMA_VERSION


def validate_prebuilt_database(database: Path) -> None:
    """Require the current schema, coherent relations and complete active loads."""
    with closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    ) as connection:
        if connection.execute("PRAGMA user_version").fetchone() != (SCHEMA_VERSION,):
            raise ValueError("Esquema do banco pré-montado incompatível.")
        if list(connection.execute("PRAGMA quick_check")) != [("ok",)]:
            raise ValueError("Banco pré-montado com erro de integridade.")
        if list(connection.execute("PRAGMA foreign_key_check")):
            raise ValueError("Banco pré-montado com vínculos inválidos.")
        imports = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT tipo, SUM(linhas_validas) FROM importacao WHERE ativo=1 GROUP BY tipo"
            )
        }
        required = {
            "mutuarios",
            "propriedades",
            "operacoes",
            "complementos",
            "glebas",
            "mma_mcr",
        }
        if set(imports) != required or any(count <= 0 for count in imports.values()):
            raise ValueError(
                "Banco pré-montado sem todas as cargas ativas obrigatórias."
            )
        if not connection.execute(
            "SELECT 1 FROM mte_publicacao WHERE total_registros > 0 LIMIT 1"
        ).fetchone():
            raise ValueError("Banco pré-montado sem publicação MTE válida.")
