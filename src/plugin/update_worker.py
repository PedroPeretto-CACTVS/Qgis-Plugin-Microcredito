"""Bootstrap the base-update worker without importing QGIS or Qt."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
BUNDLED = PLUGIN_ROOT / "lib"
SOURCE_ROOT = PLUGIN_ROOT.parent
LIBRARY_ROOT = BUNDLED if BUNDLED.is_dir() else SOURCE_ROOT
sys.path.insert(0, str(LIBRARY_ROOT))

from qgis_plugin_microcredito.infrastructure.update_process import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
