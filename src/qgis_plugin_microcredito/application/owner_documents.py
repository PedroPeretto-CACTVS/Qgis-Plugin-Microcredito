"""Regras para comprovar os documentos de proprietário ou possuidor."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from qgis_plugin_microcredito.domain.normalize import normalize_document

OWNER_LINK_TYPES = frozenset(
    {
        "documento_na_propriedade",
        "proprietario_possuidor_informado_manualmente",
    }
)

OWNER_REQUIRED_MESSAGE = (
    "Informe o CPF/CNPJ completo do proprietário/possuidor. "
    "Um mutuário associado à operação não comprova esse vínculo."
)


def _unique_documents(values: Iterable[object]) -> list[str]:
    documents: list[str] = []
    seen: set[str] = set()
    for value in values:
        document = normalize_document(value)
        if document and document not in seen:
            seen.add(document)
            documents.append(document)
    return documents


def require_owner_documents(
    associated_documents: Iterable[Mapping[str, object]],
) -> list[str]:
    """Retorna documentos completos com vínculo de proprietário/possuidor."""
    documents = _unique_documents(
        item.get("documento_normalizado")
        for item in associated_documents
        if str(item.get("tipo_vinculo") or "") in OWNER_LINK_TYPES
    )
    if not documents:
        raise ValueError(OWNER_REQUIRED_MESSAGE)
    return documents


def validate_report_owner_documents(values: Iterable[object]) -> list[str]:
    """Impede a geração de relatório sem documento completo do responsável."""
    documents = _unique_documents(values)
    if not documents:
        raise ValueError(OWNER_REQUIRED_MESSAGE)
    return documents
