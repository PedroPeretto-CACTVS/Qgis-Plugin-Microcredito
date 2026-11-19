"""The recorded human decision is visible and editable in the consultation."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QPlainTextEdit
from test_pre_analysis_window import (
    JUSTIFICATION,
    button_named,
    interact_with_pre_analysis,
)
from test_pre_analysis_window import analysis_window as analysis_window

from plugin import plugin


def record_in_modal(dialog: QDialog) -> None:
    combo = dialog.findChild(QComboBox, "technicalDecisionCombo")
    combo.setCurrentIndex(combo.findData("encaminhar"))
    dialog.findChild(QPlainTextEdit, "technicalDecisionJustification").setPlainText(
        JUSTIFICATION
    )
    button_named(dialog, "Registrar decisão técnica").click()


def test_recording_in_the_pre_analysis_updates_the_consultation_result(
    analysis_window: plugin.SearchWindow,
) -> None:
    interact_with_pre_analysis(analysis_window, record_in_modal)
    result = analysis_window.findChild(QLabel, "consultationDecisionResult")
    assert result is not None, "A consulta nao mostra a decisao registrada."
    assert (
        result.text()
        == "Decisão técnica registrada: Encaminhar para análise especializada"
    )
    assert (
        analysis_window.findChild(QComboBox, "consultationDecisionCombo").currentData()
        == "encaminhar"
    )
    assert (
        analysis_window.findChild(
            QPlainTextEdit, "consultationDecisionJustification"
        ).toPlainText()
        == JUSTIFICATION
    )


def test_recording_on_the_consultation_is_reused_by_the_pre_analysis(
    analysis_window: plugin.SearchWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    interact_with_pre_analysis(
        analysis_window,
        lambda dialog: button_named(dialog, "Fechar sem alterar").click(),
    )
    result = analysis_window.findChild(QLabel, "consultationDecisionResult")
    assert result.text().startswith("Pré-análise automática:")
    combo = analysis_window.findChild(QComboBox, "consultationDecisionCombo")
    combo.setCurrentIndex(combo.findData("contratar_condicionado"))
    analysis_window.findChild(
        QPlainTextEdit, "consultationDecisionJustification"
    ).setPlainText(JUSTIFICATION)
    assert result.text().startswith("Pré-análise automática:"), (
        "Rascunho nao e registro."
    )

    original_open = Path.open
    source_reads: list[str] = []

    def observe_storage(path: Path, mode="r", *args, **kwargs):
        if path.parent == analysis_window.local_paths.environmental and mode == "rb":
            source_reads.append(path.name)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe_storage)
    button_named(analysis_window, "Registrar decisão").click()
    assert result.text() == "Decisão técnica registrada: Contratar com condicionantes"

    def check_modal(dialog: QDialog) -> None:
        assert dialog.findChild(QComboBox, "technicalDecisionCombo").currentData() == (
            "contratar_condicionado"
        )
        assert (
            dialog.findChild(
                QPlainTextEdit, "technicalDecisionJustification"
            ).toPlainText()
            == JUSTIFICATION
        )
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, check_modal)
    assert not source_reads, "Registrar/reabrir a mesma analise refez os cruzamentos."


@pytest.mark.parametrize(
    "field", ["car", "owner_document", "document", "fund", "program"]
)
def test_changing_consultation_inputs_hides_the_previous_technical_decision(
    analysis_window: plugin.SearchWindow, field: str
) -> None:
    interact_with_pre_analysis(analysis_window, record_in_modal)
    result = analysis_window.findChild(QLabel, "consultationDecisionResult")
    assert result.text().startswith("Decisão técnica registrada:")
    control = getattr(analysis_window, field)
    if isinstance(control, QComboBox):
        control.setCurrentIndex((control.currentIndex() + 1) % control.count())
    else:
        control.setText(control.text() + "0")
    assert result.text() == "Pré-análise pendente", (
        "Decisao antiga aparece em nova consulta."
    )
    assert button_named(analysis_window, "Registrar decisão").isEnabled()


def test_returning_to_the_consultation_after_a_base_change_hides_the_old_decision(
    analysis_window: plugin.SearchWindow,
) -> None:
    interact_with_pre_analysis(analysis_window, record_in_modal)
    other = QDialog()
    try:
        other.show()
        other.activateWindow()
        QApplication.processEvents()
        assert not analysis_window.isActiveWindow()
        source = analysis_window.local_paths.environmental / "embargos.geojson"
        source.write_text(source.read_text("utf-8") + "\n", "utf-8")
        analysis_window.activateWindow()
        QApplication.processEvents()
        assert analysis_window.isActiveWindow()
        assert (
            analysis_window.findChild(QLabel, "consultationDecisionResult").text()
            == "Pré-análise pendente"
        )
        assert button_named(analysis_window, "Registrar decisão").isEnabled()
    finally:
        other.close()


def test_pending_returns_to_the_automatic_result_and_drafts_do_not_change_saved_result(
    analysis_window: plugin.SearchWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qgis.PyQt.QtWidgets import QMessageBox

    interact_with_pre_analysis(analysis_window, record_in_modal)
    result = analysis_window.findChild(QLabel, "consultationDecisionResult")
    saved = result.text()
    combo = analysis_window.findChild(QComboBox, "consultationDecisionCombo")
    justification = analysis_window.findChild(
        QPlainTextEdit, "consultationDecisionJustification"
    )
    combo.setCurrentIndex(combo.findData("nao_contratar"))
    justification.setPlainText("Curto")
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, _t, text: messages.append(text)
    )
    button_named(analysis_window, "Registrar decisão").click()
    assert messages and "15 caracteres" in messages[0]
    assert result.text() == saved
    combo.setCurrentIndex(combo.findData("pendente"))
    justification.clear()
    button_named(analysis_window, "Registrar decisão").click()
    assert result.text().startswith("Pré-análise automática:")


def test_reopened_pre_analysis_gives_the_recorded_decision_precedence(
    analysis_window: plugin.SearchWindow,
) -> None:
    interact_with_pre_analysis(analysis_window, record_in_modal)

    def check(dialog: QDialog) -> None:
        summary = dialog.findChild(QLabel, "preAnalysisRecordedDecision")
        assert summary is not None, (
            "O resumo da pre-analise omite a decisao ja registrada."
        )
        assert summary.text() == (
            "Decisão técnica registrada: Encaminhar para análise especializada"
        )
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, check)


def test_selecting_another_operation_of_the_same_car_clears_the_previous_decision(
    analysis_window: plugin.SearchWindow,
) -> None:
    from test_pre_analysis_window import CAR

    from database.session import connect

    connection = connect(analysis_window.local_paths.database)
    try:
        connection.execute(
            "INSERT INTO importacao (id,tipo,arquivo,sha256,total_linhas,linhas_validas,escopo,ativo) "
            "VALUES (1,'propriedades','synthetic.csv',?,2,2,'nacional',1)",
            ("a" * 64,),
        )
        for reference in ("operation-a", "operation-b"):
            connection.execute(
                "INSERT INTO sicor_propriedade (importacao_id,ref_bacen,nu_ordem,"
                "documento_original,documento_normalizado,car_original,car_normalizado) "
                "VALUES (1,?,'1',?,?,?,?)",
                (reference, "12345678901", "12345678901", CAR, CAR.replace("-", "")),
            )
        connection.commit()
    finally:
        connection.close()
    analysis_window.document.setText("12345678901")
    button_named(analysis_window, "Buscar operações").click()
    assert analysis_window.table.rowCount() == 2
    analysis_window.table.selectRow(0)
    interact_with_pre_analysis(analysis_window, record_in_modal)
    assert (
        analysis_window.findChild(QLabel, "consultationDecisionResult")
        .text()
        .startswith("Decisão técnica registrada:")
    )
    analysis_window.table.selectRow(1)
    assert analysis_window.car.text() == CAR
    assert analysis_window.findChild(QLabel, "consultationDecisionResult").text() == (
        "Pré-análise pendente"
    )


@pytest.mark.parametrize("change", ["midnight", "source", "geometry"])
def test_manual_registration_is_independent_of_a_stale_automatic_analysis(
    analysis_window: plugin.SearchWindow, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from datetime import date, timedelta

    from qgis.PyQt.QtWidgets import QMessageBox

    interact_with_pre_analysis(analysis_window, record_in_modal)
    combo = analysis_window.findChild(QComboBox, "consultationDecisionCombo")
    combo.setCurrentIndex(combo.findData("nao_contratar"))
    if change == "midnight":

        class Tomorrow(date):
            @classmethod
            def today(cls):
                return date.today() + timedelta(days=1)

        monkeypatch.setattr(plugin, "date", Tomorrow)
    elif change == "source":
        path = analysis_window.local_paths.environmental / "embargos.geojson"
        path.write_text(path.read_text("utf-8") + "\n", "utf-8")
    else:
        for generated in (analysis_window.local_paths.root / "resultados").glob(
            "*.geojson"
        ):
            generated.unlink()
    messages: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, title, _t: messages.append(title)
    )
    button_named(analysis_window, "Registrar decisão").click()
    assert messages == []
    assert analysis_window.findChild(QLabel, "consultationDecisionResult").text() == (
        "Decisão técnica registrada: Não contratar"
    )
    assert "manual" in analysis_window.decision_panel.notice.text().lower()
    assert analysis_window.findChild(QLabel, "consultationAutomaticResult").text() == (
        "Pré-análise automática não executada"
    )
    assert button_named(analysis_window, "Registrar decisão").isEnabled()


def test_inconclusive_automatic_analysis_can_receive_a_human_decision(
    analysis_window: plugin.SearchWindow,
) -> None:
    (analysis_window.local_paths.environmental / "embargos.geojson").unlink()
    interact_with_pre_analysis(
        analysis_window,
        lambda dialog: button_named(dialog, "Fechar sem alterar").click(),
    )
    combo = analysis_window.findChild(QComboBox, "consultationDecisionCombo")
    assert combo.isEnabled()
    combo.setCurrentIndex(combo.findData("encaminhar"))
    analysis_window.findChild(
        QPlainTextEdit, "consultationDecisionJustification"
    ).setPlainText(JUSTIFICATION)
    button_named(analysis_window, "Registrar decisão").click()
    assert analysis_window.findChild(QLabel, "consultationDecisionResult").text() == (
        "Decisão técnica registrada: Encaminhar para análise especializada"
    )
    automatic = analysis_window.findChild(QLabel, "consultationAutomaticResult")
    assert automatic.isVisible()
    assert automatic.text() == "Pré-análise automática: Verificação inconclusiva"


def test_a_new_day_requires_new_human_recording_even_with_the_same_automatic_result(
    analysis_window: plugin.SearchWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date, timedelta

    interact_with_pre_analysis(analysis_window, record_in_modal)

    class Tomorrow(date):
        @classmethod
        def today(cls):
            return date.today() + timedelta(days=1)

    monkeypatch.setattr(plugin, "date", Tomorrow)

    def check(dialog: QDialog) -> None:
        assert dialog.findChild(QComboBox, "technicalDecisionCombo").currentData() == (
            "pendente"
        ), "Uma nova consulta herdou a decisao tecnica do dia anterior."
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, check)
    assert (
        analysis_window.findChild(QLabel, "consultationDecisionResult")
        .text()
        .startswith("Pré-análise automática:")
    )
