"""Public consultation actions refuse an unverified or changing base edition."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox, QPushButton

from database.schema import initialize
from database.session import connect
from plugin import batch_window, car_document_window, plugin
from qgis_plugin_microcredito.infrastructure.updates import (
    UpdateError,
    ensure_not_updating,
)


class Iface:
    @staticmethod
    def mainWindow():
        return None


@pytest.mark.parametrize(
    ("kind", "label"),
    [
        ("search", "Buscar operações"),
        ("search", "Buscar CAR e MMA/MCR"),
        ("search", "Localizar CAR pelo ponto"),
        ("search", "Carregar no mapa"),
        ("search", "Gerar relatório final"),
        ("search", "Pré-análise das regras"),
        ("search", "Prévia do relatório"),
        ("document", "Buscar vínculos no Sicor"),
        ("batch", "Processar lote e gerar PDF"),
    ],
)
def test_actual_button_click_keeps_original_qt_slot_contract(tmp_path, kind, label):
    local = tmp_path / "local"
    root = local / "Cactvs" / "BasesPlugin"
    connection = connect(root / "car_microcredito.db")
    initialize(connection)
    connection.close()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    errors = []
    with (
        patch.dict(os.environ, {"LOCALAPPDATA": str(local)}),
        patch.object(plugin, "QSettings", lambda *_args: settings),
        patch.object(batch_window, "QSettings", lambda *_args: settings),
        patch.object(car_document_window, "QSettings", lambda *_args: settings),
        patch.object(
            sys, "excepthook", lambda _kind, error, _trace: errors.append(str(error))
        ),
        patch.object(QMessageBox, "information"),
        patch.object(QMessageBox, "warning"),
        patch.object(QMessageBox, "critical"),
    ):
        if kind == "document":
            window = car_document_window.CarDocumentWindow(Iface(), plugin._load_core)
        elif kind == "batch":
            window = batch_window.BatchWindow(Iface(), plugin._load_core)
        else:
            window = plugin.SearchWindow(Iface())
        try:
            button = next(
                button
                for button in window.findChildren(QPushButton)
                if button.text() == label
            )
            assert button.isEnabled()
            button.click()
            assert not errors, errors
            ensure_not_updating(root)
        finally:
            window.close()


@pytest.mark.parametrize(
    ("window_kind", "action", "arguments"),
    [
        ("search", "search", ()),
        ("search", "search_mma", ()),
        ("search", "search_car_by_point", ()),
        ("search", "load_selected_plots", ()),
        ("search", "analyze_selected", ("final",)),
        ("search", "analyze_selected", ("report_preview",)),
        ("search", "analyze_selected", ("pre_analysis",)),
        ("document", "search", ()),
        ("batch", "process_batch", ()),
    ],
)
def test_consultation_is_blocked_when_external_update_needs_verification(
    tmp_path: Path,
    window_kind: str,
    action: str,
    arguments: tuple[str, ...],
) -> None:
    local = tmp_path / "local"
    marker = (
        local
        / "Cactvs"
        / "BasesPlugin"
        / ".atualizacoes"
        / "external-update-pending.json"
    )
    marker.parent.mkdir(parents=True)
    marker.write_text('{"job_id": "interrompido"}', encoding="utf-8")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    with (
        patch.dict(os.environ, {"LOCALAPPDATA": str(local)}),
        patch.object(plugin, "QSettings", lambda *_args: settings),
        patch.object(batch_window, "QSettings", lambda *_args: settings),
        patch.object(car_document_window, "QSettings", lambda *_args: settings),
    ):
        if window_kind == "batch":
            window = batch_window.BatchWindow(Iface(), plugin._load_core)
        elif window_kind == "document":
            window = car_document_window.CarDocumentWindow(Iface(), plugin._load_core)
        else:
            window = plugin.SearchWindow(Iface())
        try:
            with (
                patch.object(QMessageBox, "information"),
                patch.object(QMessageBox, "critical") as critical,
                patch.object(QMessageBox, "warning") as warning,
            ):
                getattr(window, action)(*arguments)

            assert warning.called
            assert "verificação" in warning.call_args.args[2]
            assert not critical.called
            assert marker.is_file()
            assert not (marker.parent.parent / "car_microcredito.db").exists()
        finally:
            window.close()


def test_real_consultation_excludes_updates_even_during_qt_events(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local"
    root = local / "Cactvs" / "BasesPlugin"
    connection = connect(root / "car_microcredito.db")
    initialize(connection)
    connection.close()
    observed: list[str] = []

    def attempt_update() -> None:
        try:
            ensure_not_updating(root)
        except UpdateError:
            observed.append("blocked")
        else:
            observed.append("unsafe")

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    with (
        patch.dict(os.environ, {"LOCALAPPDATA": str(local)}),
        patch.object(plugin, "QSettings", lambda *_args: settings),
    ):
        window = plugin.SearchWindow(Iface())
        window.document.setText("12345678901")
        try:
            QTimer.singleShot(0, attempt_update)
            with patch.object(QMessageBox, "critical") as critical:
                window.search()

            assert not critical.called, critical.call_args
            assert observed == ["blocked"]
            ensure_not_updating(root)
        finally:
            window.close()


def test_report_keeps_lease_after_database_query_until_user_cancels(
    tmp_path: Path,
) -> None:
    local = tmp_path / "local"
    root = local / "Cactvs" / "BasesPlugin"
    connection = connect(root / "car_microcredito.db")
    initialize(connection)
    connection.close()
    observed: list[str] = []

    def cancel_destination(*_args: object) -> str:
        try:
            ensure_not_updating(root)
        except UpdateError:
            observed.append("blocked")
        else:
            observed.append("unsafe")
        return ""

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    with (
        patch.dict(os.environ, {"LOCALAPPDATA": str(local)}),
        patch.object(plugin, "QSettings", lambda *_args: settings),
    ):
        window = plugin.SearchWindow(Iface())
        window.car.setText("MT-5100102-00000000000000000000000000000001")
        window.owner_document.setText("12345678901")
        try:
            with (
                patch.object(QFileDialog, "getExistingDirectory", cancel_destination),
                patch.object(QMessageBox, "information"),
                patch.object(QMessageBox, "critical") as critical,
            ):
                window.analyze_selected("final")

            assert not critical.called, critical.call_args
            assert observed == ["blocked"]
            ensure_not_updating(root)
        finally:
            window.close()
