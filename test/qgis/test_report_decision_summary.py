"""A recorded human decision is the primary result in the delivered PDF."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from pypdf import PdfReader
from qgis.core import QgsRasterLayer
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox
from test_consultation_decision import record_in_modal
from test_pre_analysis_window import analysis_window as analysis_window
from test_pre_analysis_window import button_named, interact_with_pre_analysis

from plugin import map_output, plugin
from plugin.report import write_report
from qgis_plugin_microcredito.application.pre_analysis import build_pre_analysis
from qgis_plugin_microcredito.domain.policy import aggregate, evaluate_lists


def test_final_pdf_shows_the_registered_decision_before_the_automatic_result(
    analysis_window: plugin.SearchWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interact_with_pre_analysis(analysis_window, record_in_modal)
    destination = tmp_path / "final-report"
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *_a, **_kw: str(destination)
    )
    # External satellite may be unavailable; report, vector map and audit stay real.
    monkeypatch.setattr(map_output, "QgsRasterLayer", lambda *_a: QgsRasterLayer())
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, title, *_a: messages.append(title)
    )
    button_named(analysis_window, "Gerar relatório final").click()
    assert messages == ["Relatório criado"]
    files = list(destination.rglob("*.pdf"))
    assert len(files) == 1
    first_page = " ".join(PdfReader(str(files[0])).pages[0].extract_text().split())
    summary = first_page.split("Entendimento das regras e conclusão preliminar")[0]
    assert "Decisão técnica registrada" in summary
    assert "Encaminhar para análise especializada" in summary
    assert summary.index("Decisão técnica registrada") < summary.index(
        "Resultado automático da pré-análise"
    )


def prepared_analysis() -> dict[str, object]:
    analysis = {
        "car": "MT-0000000-00000000000000000000000000000000",
        "documentos_proprietario_possuidor": ["12345678901"],
        "documentos_consultados_mte": ["12345678901"],
        "ambiental": {"resultado_geral": "inconclusivo", "camadas": []},
        "demonstracao": True,
    }
    outcomes = evaluate_lists([], [], analysis, ["12345678901"])
    analysis["resultado_fontes"] = outcomes
    analysis["resultado_geral"] = aggregate(["inconclusivo", *outcomes.values()])
    analysis["pre_analise"] = build_pre_analysis(analysis)
    return analysis


@pytest.mark.parametrize(
    ("code", "label"),
    [
        ("contratar", "Contratar"),
        ("contratar_condicionado", "Contratar com condicionantes"),
        ("nao_contratar", "Não contratar"),
        ("encaminhar", "Encaminhar para análise especializada"),
    ],
)
def test_pdf_summary_uses_the_known_recorded_decision(
    tmp_path: Path, code: str, label: str
) -> None:
    analysis = prepared_analysis()
    analysis["decisao_tecnica"] = {
        "codigo": code,
        "rotulo": label,
        "justificativa": "Fundamento sintetico conferido para este ensaio.",
        "registrada_em": "2026-11-19T10:00:00-03:00",
        "pre_analise_sha256": analysis["pre_analise"]["sha256"],
    }
    pdf, _audit = write_report(analysis, tmp_path / "decision.pdf")
    first_page = " ".join(PdfReader(str(pdf)).pages[0].extract_text().split())
    summary = first_page.split("Entendimento das regras e conclusão preliminar")[0]
    assert f"Decisão técnica registrada {label}" in summary
    assert "Resultado automático da pré-análise: Verificação inconclusiva" in summary


@pytest.mark.parametrize("case", ["missing", "pending", "stale", "unknown"])
def test_pdf_without_a_valid_human_decision_keeps_the_automatic_summary(
    tmp_path: Path, case: str
) -> None:
    analysis = prepared_analysis()
    if case != "missing":
        analysis["decisao_tecnica"] = {
            "codigo": {
                "pending": "pendente",
                "stale": "contratar",
                "unknown": "unknown",
            }[case],
            "rotulo": "DECISAO QUE NAO DEVE SER O RESULTADO PRINCIPAL",
            "pre_analise_sha256": (
                "0" * 64 if case == "stale" else analysis["pre_analise"]["sha256"]
            ),
        }
    pdf, _audit = write_report(analysis, tmp_path / "fallback.pdf")
    first_page = " ".join(PdfReader(str(pdf)).pages[0].extract_text().split())
    summary = first_page.split("Entendimento das regras e conclusão preliminar")[0]
    assert "Resumo da pré-análise Verificação inconclusiva" in summary
    assert "Decisão técnica registrada" not in summary
    assert "DECISAO QUE NAO DEVE" not in summary
