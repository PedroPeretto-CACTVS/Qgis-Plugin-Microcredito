"""Validate the distinct bindings of manual and pre-analysis decisions."""

from __future__ import annotations

from qgis_plugin_microcredito.application.pre_analysis import TECHNICAL_DECISIONS
from qgis_plugin_microcredito.domain.normalize import normalize_car


def has_current_technical_decision(analysis: dict[str, object]) -> bool:
    """Check consultation identity, without treating a manual record as engine review.

    Context digests are local provenance bindings, not authentication signatures.
    The UI supplies the current consultation context when producing a report.
    """
    decision = analysis.get("decisao_tecnica")
    if not isinstance(decision, dict):
        return False
    code = decision.get("codigo")
    if (
        not isinstance(code, str)
        or code == "pendente"
        or code not in dict(TECHNICAL_DECISIONS)
    ):
        return False
    if decision.get("origem") == "analise_manual":
        context = analysis.get("contexto_decisao_manual_sha256")
        car = normalize_car(analysis.get("car"))
        return bool(
            car
            and car == normalize_car(decision.get("car"))
            and isinstance(context, str)
            and len(context) == 64
            and set(context) <= set("0123456789abcdef")
            and decision.get("contexto_manual_sha256") == context
        )
    if decision.get("origem") not in (None, "", "pre_analise_automatica"):
        return False
    pre_analysis = analysis.get("pre_analise")
    return bool(
        isinstance(pre_analysis, dict)
        and pre_analysis.get("sha256")
        and decision.get("pre_analise_sha256") == pre_analysis.get("sha256")
    )
