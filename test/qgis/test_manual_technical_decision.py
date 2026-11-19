"""Technicians can register their own assessment without automatic pre-analysis."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtWidgets import QApplication, QComboBox, QLabel, QPlainTextEdit
from test_pre_analysis_window import JUSTIFICATION, button_named
from test_pre_analysis_window import analysis_window as analysis_window

from plugin import plugin


def test_registering_manual_decision_does_not_require_automatic_pre_analysis(
    analysis_window: plugin.SearchWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    combo = analysis_window.findChild(QComboBox, "consultationDecisionCombo")
    assert combo.isEnabled(), "A avaliacao manual depende da pre-analise automatica."
    reads: list[str] = []
    original_open = Path.open

    def observe_storage(path: Path, mode="r", *args, **kwargs):
        if path.parent in (
            analysis_window.local_paths.car,
            analysis_window.local_paths.environmental,
        ):
            reads.append(path.name)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe_storage)
    combo.setCurrentIndex(combo.findData("contratar"))
    analysis_window.findChild(
        QPlainTextEdit, "consultationDecisionJustification"
    ).setPlainText(JUSTIFICATION)
    button_named(analysis_window, "Registrar decisão").click()
    result = analysis_window.findChild(QLabel, "consultationDecisionResult")
    assert result.text() == "Decisão técnica registrada: Contratar"
    assert "manual" in analysis_window.decision_panel.notice.text().lower()
    assert (
        "não executada"
        in analysis_window.findChild(QLabel, "consultationAutomaticResult").text()
    )
    assert QApplication.activeModalWidget() is None
    assert not reads, "O registro manual consultou as fontes automaticas."
    assert not list((analysis_window.local_paths.root / "resultados").glob("*.geojson"))


def test_report_preserves_a_manual_decision_recorded_without_pre_analysis(
    analysis_window: plugin.SearchWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from pypdf import PdfReader
    from qgis.core import QgsRasterLayer
    from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

    from plugin import map_output

    combo = analysis_window.findChild(QComboBox, "consultationDecisionCombo")
    combo.setCurrentIndex(combo.findData("contratar"))
    analysis_window.findChild(
        QPlainTextEdit, "consultationDecisionJustification"
    ).setPlainText(JUSTIFICATION)
    button_named(analysis_window, "Registrar decisão").click()
    destination = tmp_path / "manual-report"
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *_a, **_kw: str(destination)
    )
    monkeypatch.setattr(map_output, "QgsRasterLayer", lambda *_a: QgsRasterLayer())
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, title, *_a: messages.append(title)
    )
    button_named(analysis_window, "Gerar relatório final").click()
    assert messages == ["Relatório criado"]
    audits = list(destination.rglob("relatorio.json"))
    assert len(audits) == 1
    payload = json.loads(audits[0].read_text("utf-8"))
    decision = payload["decisao_tecnica"]
    assert decision["codigo"] == "contratar", (
        "O relatorio descartou a avaliacao manual."
    )
    assert decision["origem"] == "analise_manual"
    assert "pre_analise_sha256" not in decision, (
        "Foi atribuido um aceite de analise nao revisada."
    )
    pdf = list(destination.rglob("*.pdf"))
    assert len(pdf) == 1
    first_page = " ".join(PdfReader(str(pdf[0])).pages[0].extract_text().split())
    summary = first_page.split("Entendimento das regras e conclusão preliminar")[0]
    assert "Decisão técnica registrada Contratar" in summary
    assert "Avaliação manual do técnico" in summary
    assert "Resultado automático da pré-análise" in summary


@pytest.mark.parametrize("case", ["missing_context", "wrong_car", "wrong_context"])
def test_report_does_not_accept_an_unbound_manual_marker(
    tmp_path: Path, case: str
) -> None:
    import json

    from pypdf import PdfReader
    from test_report_decision_summary import prepared_analysis

    from plugin.report import write_report

    analysis = prepared_analysis()
    analysis["contexto_decisao_manual_sha256"] = "a" * 64
    analysis["decisao_tecnica"] = {
        "codigo": "contratar",
        "rotulo": "Contratar",
        "origem": "analise_manual",
        "car": analysis["car"],
        "contexto_manual_sha256": "a" * 64,
        "pre_analise_sha256": analysis["pre_analise"]["sha256"],
    }
    if case == "missing_context":
        analysis.pop("contexto_decisao_manual_sha256")
    elif case == "wrong_car":
        analysis["decisao_tecnica"]["car"] = "MS-OUTRO-CAR-SINTETICO"
    else:
        analysis["decisao_tecnica"]["contexto_manual_sha256"] = "b" * 64
    pdf, audit = write_report(analysis, tmp_path / "invalid.pdf")
    payload = json.loads(audit.read_text("utf-8"))
    assert payload["decisao_tecnica"]["codigo"] == "pendente"
    first_page = " ".join(PdfReader(str(pdf)).pages[0].extract_text().split())
    summary = first_page.split("Entendimento das regras e conclusão preliminar")[0]
    assert "Decisão técnica registrada" not in summary


def test_manual_recording_still_requires_a_justification(
    analysis_window: plugin.SearchWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qgis.PyQt.QtWidgets import QMessageBox

    combo = analysis_window.findChild(QComboBox, "consultationDecisionCombo")
    combo.setCurrentIndex(combo.findData("contratar"))
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, title, *_a: messages.append(title)
    )
    button_named(analysis_window, "Registrar decisão").click()
    assert messages == ["Justificativa necessária"]
    assert (
        analysis_window.findChild(QLabel, "consultationDecisionResult").text()
        == "Pré-análise pendente"
    )
