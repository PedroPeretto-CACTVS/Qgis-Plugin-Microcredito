from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from database.repositories import (
    find_by_car as _find_by_car,
)
from database.repositories import (
    find_by_document as _find_by_document,
)
from database.repositories import (
    find_documents_by_car as _find_documents_by_car,
)
from database.repositories import (
    find_mma_mcr_by_car as _find_mma_mcr_by_car,
)
from database.repositories import (
    find_operation_context as _find_operation_context,
)
from database.repositories import (
    find_slave_labor_by_documents as _find_slave_labor_by_documents,
)
from database.repositories import list_imports as _list_imports


def find_by_document(
    connection: sqlite3.Connection, document: str
) -> list[dict[str, Any]]:
    return _find_by_document(connection, document)


def find_by_car(connection: sqlite3.Connection, car: str) -> list[dict[str, Any]]:
    return _find_by_car(connection, car)


def find_documents_by_car(
    connection: sqlite3.Connection, car: str
) -> list[dict[str, Any]]:
    return _find_documents_by_car(connection, car)


def find_slave_labor_by_documents(
    connection: sqlite3.Connection, documents: Iterable[str]
) -> list[dict[str, Any]]:
    return _find_slave_labor_by_documents(connection, documents)


def find_operation_context(
    connection: sqlite3.Connection, ref_bacen: str, nu_ordem: str
) -> dict[str, Any]:
    return _find_operation_context(connection, ref_bacen, nu_ordem)


def find_mma_mcr_by_car(
    connection: sqlite3.Connection, car: str
) -> list[dict[str, Any]]:
    return _find_mma_mcr_by_car(connection, car)


def list_imports(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _list_imports(connection)
