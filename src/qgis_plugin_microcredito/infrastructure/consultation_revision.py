"""Identify input changes for a short-lived, in-memory consultation snapshot.

This metadata revision is not an integrity certificate. Fresh consultations still
perform the existing source hashing and validation before a snapshot is stored.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def consultation_revision(data_root: Path) -> str:
    """Fingerprint the input file set, excluding generated outputs and locks.

    Call under the base read lease. An I/O failure must disable snapshot reuse.
    Nonempty journals and cadastral/environmental companion files participate.
    SQLite's SHM index/read marks and empty journals are not database contents.
    """
    root = data_root.resolve()
    files = set(root.glob("car_microcredito.db*"))
    for directory in (root / "car", root / "ambientais"):
        if directory.exists():
            files.update(path for path in directory.rglob("*") if path.is_file())
    states = {
        root / ".atualizacoes" / name
        for name in ("estado.json", "prebuilt-installed.json")
    }
    files.update(path for path in states if path.exists())
    entries = []
    for path in sorted(files):
        stat = path.stat()
        if path.name.endswith("-shm") or (
            path.name.endswith(("-wal", "-journal")) and stat.st_size == 0
        ):
            continue
        entries.append(
            (
                path.relative_to(root).as_posix(),
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
                stat.st_ctime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest() if path in states else "",
            )
        )
    return hashlib.sha256(json.dumps(entries).encode("utf-8")).hexdigest()
