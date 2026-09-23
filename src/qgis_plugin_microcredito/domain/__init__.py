"""Pure domain types and rules."""

from qgis_plugin_microcredito.domain.enums import ImportType, LinkType, Verdict
from qgis_plugin_microcredito.domain.normalize import (
    is_masked_document,
    normalize_car,
    normalize_document,
    normalize_header,
    only_digits,
)
from qgis_plugin_microcredito.domain.policy import (
    CLEAR,
    INCONCLUSIVE,
    REVIEW,
    aggregate,
    available,
    compatible_operation,
    evaluate_lists,
    list_message,
    unique_operation,
)

__all__ = [
    "CLEAR",
    "INCONCLUSIVE",
    "REVIEW",
    "ImportType",
    "LinkType",
    "Verdict",
    "aggregate",
    "available",
    "compatible_operation",
    "evaluate_lists",
    "is_masked_document",
    "list_message",
    "normalize_car",
    "normalize_document",
    "normalize_header",
    "only_digits",
    "unique_operation",
]
