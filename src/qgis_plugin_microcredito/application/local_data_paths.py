"""Stable, per-user storage shared by every plugin screen and installation."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalDataPaths:
    """Derive all data locations from one root, independent of plugin versions."""

    root: Path

    @property
    def database(self) -> Path:
        return self.root / "car_microcredito.db"

    @property
    def car(self) -> Path:
        return self.root / "car"

    @property
    def environmental(self) -> Path:
        return self.root / "ambientais"


def default_local_data_paths() -> LocalDataPaths:
    """Return the OS-local data directory without creating or modifying files."""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        parent = Path(local_app_data)
    elif sys.platform == "win32":
        parent = Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        parent = Path.home() / "Library" / "Application Support"
    else:
        parent = Path(
            os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        )
    return LocalDataPaths(parent / "Cactvs" / "BasesPlugin")
