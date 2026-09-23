"""Regras compartilhadas pela interface, pelo lote e pelo relatório."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from qgis_plugin_microcredito.domain.enums import Verdict
from qgis_plugin_microcredito.domain.normalize import normalize_car

INCONCLUSIVE = Verdict.INCONCLUSIVE.value
CLEAR = Verdict.CLEAR.value
REVIEW = Verdict.REVIEW.value


def aggregate(results: Iterable[object]) -> str:
    values = list(results)
    if REVIEW in values:
        return REVIEW
    if not values or any(value != CLEAR for value in values):
        return INCONCLUSIVE
    return CLEAR


def available(source: Mapping[str, Any] | None, count_field: str) -> bool:
    source = source or {}
    try:
        return (
            int(source.get(count_field) or 0) > 0
            and bool(source.get("sha256"))
            and int(source.get("linhas_rejeitadas") or 0) == 0
            and date.fromisoformat(str(source.get("validade_ate") or ""))
            >= date.today()
        )
    except (ValueError, TypeError):
        return False


def evaluate_lists(
    mma: Sequence[Mapping[str, Any]],
    labor: Sequence[object],
    evidence: Mapping[str, Any],
    documents: Sequence[object],
) -> dict[str, str]:
    mma_result = INCONCLUSIVE
    if available(evidence.get("mma_fonte") or {}, "linhas_validas"):
        states: list[str] = []
        for item in mma:
            status = str(item.get("status_imovel") or "").strip().upper()
            criterion = str(item.get("dentro_criterio") or "").strip().lower()
            if status in {"SU", "CA"} or criterion in {"sim", "s", "yes"}:
                states.append(REVIEW)
            elif status == "AT" and criterion in {"nao", "não", "n", "no"}:
                states.append(CLEAR)
            else:
                states.append(INCONCLUSIVE)
        mma_result = aggregate(states) if states else CLEAR
    labor_result = INCONCLUSIVE
    if documents and available(evidence.get("mte_fonte") or {}, "total_registros"):
        labor_result = REVIEW if labor else CLEAR
    return {"mma_mcr": mma_result, "mte": labor_result}


def list_message(result: object, source: str) -> str:
    if result == REVIEW:
        return f"Ocorrência na consulta {source}. Encaminhar para revisão."
    if result == CLEAR:
        return (
            f"Nenhuma ocorrência localizada na publicação {source} consultada. "
            "Isso não comprova regularidade integral."
        )
    return (
        f"Consulta {source} inconclusiva: confira a disponibilidade e a validade "
        "da publicação, os dados informados e os valores retornados."
    )


def compatible_operation(operation: Mapping[str, Any] | None, car: object) -> bool:
    if not operation or not normalize_car(car):
        return False
    return normalize_car(
        operation.get("car_normalizado") or operation.get("car_original")
    ) == normalize_car(car)


def unique_operation(
    operations: Sequence[Mapping[str, Any]], car: object
) -> dict[str, Any] | None:
    candidates = {
        (str(item.get("ref_bacen") or ""), str(item.get("nu_ordem") or "")): dict(item)
        for item in operations
        if compatible_operation(item, car)
    }
    if len(candidates) > 1:
        raise ValueError(
            "Há várias operações para este CAR. Sem polígono SICAR, selecione uma "
            "operação comprovadamente associada na consulta individual."
        )
    return next(iter(candidates.values()), None)
