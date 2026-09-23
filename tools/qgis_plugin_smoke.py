"""Valida um plugin extraído usando o interpretador Python do QGIS."""

from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
from pathlib import Path


def smoke(plugin_root: Path) -> dict[str, object]:
    root = plugin_root.resolve()
    if not (root / "metadata.txt").is_file() or not (root / "lib").is_dir():
        raise ValueError("Informe a raiz de um plugin QGIS extraído.")

    sys.path.insert(0, str(root.parent))
    package = importlib.import_module(root.name)
    instance = package.classFactory(None)
    importlib.import_module(f"{root.name}.plugin")
    importlib.import_module(f"{root.name}.update_window")

    sys.path.insert(0, str(root / "lib"))
    importlib.import_module("qgis_plugin_microcredito.infrastructure.updates")
    from database.schema import SCHEMA_VERSION, initialize

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        initialize(connection)
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        mte_table = int(
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'mte_publicacao'"
            ).fetchone()[0]
        )
    finally:
        connection.close()

    if version != SCHEMA_VERSION or mte_table != 1:
        raise RuntimeError("O esquema SQLite do plugin não foi inicializado.")
    return {
        "plugin": root.name,
        "class_factory": type(instance).__name__,
        "schema_version": version,
        "status": "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(smoke(args.plugin_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
