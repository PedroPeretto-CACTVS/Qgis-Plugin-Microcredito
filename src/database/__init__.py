"""Persistence helpers for the CAR Microcrédito SQLite database.

``Base`` remains available for administrative ORM consumers, but is loaded
only on demand so the QGIS runtime does not require SQLAlchemy.
"""

from typing import TYPE_CHECKING, Any

from database.schema import SCHEMA_VERSION, configure_import, initialize
from database.session import connect

if TYPE_CHECKING:
    from database.models import Base


def __getattr__(name: str) -> Any:
    if name == "Base":
        from database.models import Base

        return Base
    raise AttributeError(name)


__all__ = ["Base", "SCHEMA_VERSION", "configure_import", "connect", "initialize"]
