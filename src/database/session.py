"""SQLite connection factory with the same readonly contract as version 0.8."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from database.schema import SCHEMA_VERSION


def connect(path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    db_path = Path(path)
    if readonly:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            connection.close()
            raise ValueError(
                "Banco incompatível com a versão 0.8. Faça a migração administrativa "
                "em uma cópia antes de consultar."
            )
        return connection
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
