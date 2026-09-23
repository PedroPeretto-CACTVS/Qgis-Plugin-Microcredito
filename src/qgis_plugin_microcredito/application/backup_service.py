"""Cópia consistente para migração e distribuição, sem alterar a origem."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from database.schema import initialize
from database.session import connect


def snapshot_database(
    source: str | Path,
    destination: str | Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    source_path, destination_path = Path(source), Path(destination)
    if not source_path.is_file() or destination_path.exists():
        raise ValueError("A origem deve existir e o destino do backup deve ser novo.")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    origin = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(destination_path)
    try:

        def report(_status: int, remaining: int, total: int) -> None:
            if progress is not None:
                progress(total - remaining, total)

        origin.backup(target, pages=1024, progress=report if progress else None)
        if list(target.execute("PRAGMA quick_check")) != [("ok",)]:
            raise ValueError("A cópia não passou na verificação de integridade.")
    except Exception:
        target.close()
        destination_path.unlink(missing_ok=True)
        raise
    finally:
        target.close()
        origin.close()
    return destination_path


def migrate_copy(source: str | Path, destination: str | Path) -> Path:
    target = snapshot_database(source, destination)
    connection = connect(target)
    try:
        initialize(connection)
        if list(connection.execute("PRAGMA foreign_key_check")):
            raise ValueError(
                "A migração encontrou vínculos inválidos; não ativar esta cópia."
            )
    finally:
        connection.close()
    return target
