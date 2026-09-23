def classFactory(iface):  # type: ignore[no-untyped-def]
    from .plugin import CarMicrocreditoPlugin

    return CarMicrocreditoPlugin(iface)


import sys
from pathlib import Path

_bundled = Path(__file__).parent / "lib"
_core = _bundled if _bundled.is_dir() else Path(__file__).resolve().parents[2]
if str(_core) not in sys.path:
    sys.path.insert(0, str(_core))
