"""User flows: open the real analysis, read it and record a technical decision."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from time import monotonic, sleep

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
)

from database.schema import initialize
from database.session import connect
from plugin import plugin
from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)

CAR = "MT-5100102-00000000000000000000000000000001"
JUSTIFICATION = "Documentos de teste conferidos pelo tecnico responsavel."


def button_named(window: QDialog, text: str) -> QPushButton:
    buttons = [b for b in window.findChildren(QPushButton) if b.text() == text]
    assert len(buttons) == 1, text
    return buttons[0]


@pytest.fixture
def analysis_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[plugin.SearchWindow]:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(plugin, "QSettings", lambda *_a, **_kw: settings)

    class Iface:
        @staticmethod
        def mainWindow() -> None:
            return None

    paths = default_local_data_paths()
    paths.car.mkdir(parents=True)
    connection = connect(paths.database)
    initialize(connection)
    connection.close()
    (paths.car / "MT_perimetros.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"cod_imovel": CAR, "num_area": 123},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [-50, -10],
                                    [-49.99, -10],
                                    [-49.99, -10.01],
                                    [-50, -10.01],
                                    [-50, -10],
                                ]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    paths.environmental.mkdir()
    for name in (
        "embargos",
        "terras_indigenas",
        "territorios_quilombolas",
        "unidades_conservacao",
        "florestas_publicas",
        "desmatamento_pos_2020",
    ):
        (paths.environmental / f"{name}.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [[-70, -5], [-69, -5], [-69, -6], [-70, -5]]
                                ],
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    messages: list[str] = []
    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(
            QMessageBox,
            kind,
            lambda _parent, title, text, *_a, **_kw: messages.append(
                f"{title}: {text}"
            ),
        )
    window = plugin.SearchWindow(Iface())
    window.car.setText(CAR)
    window.owner_document.setText("12345678901")
    window.show()
    QApplication.processEvents()
    yield window
    window.close()
    window.deleteLater()
    QApplication.processEvents()
    assert not messages, messages


def interact_with_pre_analysis(window: plugin.SearchWindow, interaction) -> float:
    """Drive the modal by real widgets while the public button runs its flow."""
    failures: list[Exception] = []
    visited = []
    started = monotonic()
    timer = QTimer(window)
    watchdog = QTimer(window)
    watchdog.setSingleShot(True)
    timed_out = False

    def fail_on_timeout() -> None:
        nonlocal timed_out
        timed_out = True
        failures.append(
            AssertionError(
                "A pre-analise nao ficou pronta para interacao em 15 segundos."
            )
        )
        modal = QApplication.activeModalWidget()
        if isinstance(modal, QDialog):
            modal.reject()

    def visit() -> None:
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QDialog):
            return
        if timed_out:
            dialog.reject()
            return
        if not dialog.findChild(QComboBox, "technicalDecisionCombo"):
            return
        timer.stop()
        visited.append(dialog)
        try:
            interaction(dialog)
        except Exception as exc:
            failures.append(exc)
        finally:
            if dialog.isVisible():
                dialog.reject()

    watchdog.timeout.connect(fail_on_timeout)
    watchdog.start(15000)
    timer.timeout.connect(visit)
    timer.start(10)
    try:
        button_named(window, "Pré-análise das regras").click()
    finally:
        timer.stop()
        timer.deleteLater()
        watchdog.stop()
        watchdog.deleteLater()
    if failures:
        raise failures[0]
    assert visited, "A janela de pre-analise nao abriu."
    return monotonic() - started


def test_technical_decision_is_ready_for_editing_without_a_busy_cursor(
    analysis_window: plugin.SearchWindow,
) -> None:
    def record(dialog: QDialog) -> None:
        assert QApplication.overrideCursor() is None, (
            "O cruzamento terminou, mas a decisao continua com cursor de espera."
        )
        decision = dialog.findChild(QComboBox, "technicalDecisionCombo")
        justification = dialog.findChild(
            QPlainTextEdit, "technicalDecisionJustification"
        )
        decision.setCurrentIndex(decision.findData("encaminhar"))
        justification.setPlainText(JUSTIFICATION)
        button_named(dialog, "Registrar decisão técnica").click()
        assert not dialog.isVisible()

    interact_with_pre_analysis(analysis_window, record)

    def reread(dialog: QDialog) -> None:
        assert (
            dialog.findChild(QComboBox, "technicalDecisionCombo").currentData()
            == "encaminhar"
        )
        assert (
            dialog.findChild(
                QPlainTextEdit, "technicalDecisionJustification"
            ).toPlainText()
            == JUSTIFICATION
        )
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, reread)


def test_reopening_an_unchanged_pre_analysis_avoids_slow_source_reads(
    analysis_window: plugin.SearchWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Model latency at the filesystem boundary, without replacing any product code.
    original_open = Path.open
    environmental = default_local_data_paths().environmental

    def slow_storage(path: Path, mode="r", *args, **kwargs):
        if path.parent == environmental and mode == "rb":
            sleep(0.15)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", slow_storage)

    def close(dialog: QDialog) -> None:
        button_named(dialog, "Fechar sem alterar").click()

    first = interact_with_pre_analysis(analysis_window, close)
    reopened = interact_with_pre_analysis(analysis_window, close)
    assert first >= 0.85, "A fronteira de armazenamento lento nao foi exercitada."
    assert reopened < first / 3, (first, reopened)


def test_changed_owner_requires_a_new_technical_decision(
    analysis_window: plugin.SearchWindow,
) -> None:
    def record(dialog: QDialog) -> None:
        decision = dialog.findChild(QComboBox, "technicalDecisionCombo")
        decision.setCurrentIndex(decision.findData("encaminhar"))
        dialog.findChild(QPlainTextEdit, "technicalDecisionJustification").setPlainText(
            JUSTIFICATION
        )
        button_named(dialog, "Registrar decisão técnica").click()

    interact_with_pre_analysis(analysis_window, record)
    analysis_window.owner_document.setText("98765432100")

    def verify_new_consultation(dialog: QDialog) -> None:
        assert (
            dialog.findChild(QComboBox, "technicalDecisionCombo").currentData()
            == "pendente"
        )
        assert not dialog.findChild(
            QPlainTextEdit, "technicalDecisionJustification"
        ).toPlainText()
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, verify_new_consultation)


def test_changed_environmental_source_is_reflected_before_recording_again(
    analysis_window: plugin.SearchWindow,
) -> None:
    from qgis.PyQt.QtWidgets import QTableWidget

    def close(dialog: QDialog) -> None:
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, close)
    paths = default_local_data_paths()
    payload = json.loads((paths.car / "MT_perimetros.geojson").read_text("utf-8"))
    (paths.environmental / "embargos.geojson").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    def verify_occurrence(dialog: QDialog) -> None:
        table = dialog.findChild(QTableWidget, "preAnalysisTable")
        rows = [
            row
            for row in range(table.rowCount())
            if table.item(row, 0).text().startswith("Embargos ambientais")
        ]
        assert len(rows) == 1
        assert "Possível impedimento" in table.item(rows[0], 1).text()
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, verify_occurrence)


@pytest.mark.parametrize(
    "change", ["unchanged", "environmental", "midnight", "geometry_in_picker"]
)
def test_report_reuses_only_a_still_current_recorded_analysis(
    analysis_window: plugin.SearchWindow,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from qgis.core import QgsRasterLayer
    from qgis.PyQt.QtWidgets import QFileDialog

    from plugin import map_output
    from qgis_plugin_microcredito.domain import policy

    paths = default_local_data_paths()
    if change == "midnight":
        connection = connect(paths.database)
        connection.execute(
            "INSERT INTO importacao "
            "(id,tipo,arquivo,sha256,total_linhas,linhas_validas,escopo,ativo,validade_ate) "
            "VALUES (1,'mma_mcr','synthetic.csv',?,1,1,'nacional',1,?)",
            ("a" * 64, date.today().isoformat()),
        )
        connection.execute(
            "INSERT INTO mma_mcr (importacao_id,car_original,car_normalizado) "
            "VALUES (1,'MT-OUTRO-IMOVEL-SINTETICO','MTOUTROIMOVELSINTETICO')"
        )
        connection.commit()
        connection.close()

    def record(dialog: QDialog) -> None:
        decision = dialog.findChild(QComboBox, "technicalDecisionCombo")
        decision.setCurrentIndex(decision.findData("encaminhar"))
        dialog.findChild(QPlainTextEdit, "technicalDecisionJustification").setPlainText(
            JUSTIFICATION
        )
        button_named(dialog, "Registrar decisão técnica").click()

    interact_with_pre_analysis(analysis_window, record)
    if change == "environmental":
        payload = json.loads((paths.car / "MT_perimetros.geojson").read_text("utf-8"))
        (paths.environmental / "embargos.geojson").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    source_reads = []
    original_open = Path.open
    environmental = default_local_data_paths().environmental

    def observe_storage(path: Path, mode="r", *args, **kwargs):
        if path.parent == environmental and mode == "rb":
            source_reads.append(path.name)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe_storage)
    destination = tmp_path / "report"

    class Tomorrow(date):
        @classmethod
        def today(cls):
            return date.today() + timedelta(days=1)

    def select_destination(*_a, **_kw):
        if change == "midnight":
            monkeypatch.setattr(plugin, "date", Tomorrow)
            monkeypatch.setattr(policy, "date", Tomorrow)
        if change == "geometry_in_picker":
            for generated in (paths.root / "resultados").glob("*.geojson"):
                generated.unlink()
        return str(destination)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", select_destination)
    # Model unavailable satellite tiles at the external GIS provider boundary.
    # Rendering, territorial layers, PDF generation and audit writing stay real.
    monkeypatch.setattr(map_output, "QgsRasterLayer", lambda *_a: QgsRasterLayer())
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda _p, title, *_a: messages.append(title)
    )
    button_named(analysis_window, "Gerar relatório final").click()
    assert messages == ["Relatório criado"]
    assert len(list(destination.rglob("*.pdf"))) == 1
    audits = list(destination.rglob("relatorio.json"))
    assert len(audits) == 1
    audit = json.loads(audits[0].read_text("utf-8"))
    if change in {"unchanged", "geometry_in_picker"}:
        assert audit["decisao_tecnica"]["codigo"] == "encaminhar"
        assert audit["decisao_tecnica"]["justificativa"] == JUSTIFICATION
        assert (
            audit["decisao_tecnica"]["pre_analise_sha256"]
            == audit["pre_analise"]["sha256"]
        )
        if change == "unchanged":
            assert not source_reads, (
                "O relatorio releu integralmente fontes ja analisadas sem alteracao.",
                source_reads,
            )
        assert list(destination.rglob("evidencia_*.png")), (
            "O mapa do CAR deve acompanhar o relatorio."
        )

    else:
        assert source_reads, "A mudanca exige recalcular a consulta."
        assert audit["decisao_tecnica"]["codigo"] == "pendente"
