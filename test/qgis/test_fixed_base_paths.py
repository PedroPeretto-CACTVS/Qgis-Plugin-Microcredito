import os
import sqlite3
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QGroupBox, QLabel, QLineEdit, QMessageBox, QPushButton

from database.schema import initialize
from database.session import connect
from plugin import batch_window, car_document_window, plugin, update_window


class Iface:
    @staticmethod
    def mainWindow():
        return None


def _settings_factory(path: Path):
    def settings(*_args, **_kwargs):
        return QSettings(str(path), QSettings.IniFormat)

    return settings


def _window_context(tmp_path: Path):
    settings_path = tmp_path / "settings.ini"
    settings = _settings_factory(settings_path)
    stack = ExitStack()
    stack.enter_context(
        patch.dict(os.environ, {"LOCALAPPDATA": str(tmp_path / "local")})
    )
    for module in (plugin, batch_window, car_document_window, update_window):
        stack.enter_context(patch.object(module, "QSettings", settings))
    return stack, settings


def test_windows_offer_work_fields_without_base_directory_controls(
    tmp_path: Path,
) -> None:
    context, settings_factory = _window_context(tmp_path)
    with context:
        settings = settings_factory()
        settings.setValue("database", r"C:\kit-antigo\car_microcredito-R2.db")
        settings.setValue("car_base", r"C:\outra-pasta\car")
        settings.setValue("base_local_expanded", True)
        settings.sync()

        search = plugin.SearchWindow(Iface())
        batch = batch_window.BatchWindow(Iface(), plugin._load_core)
        document = car_document_window.CarDocumentWindow(Iface(), plugin._load_core)
        updates = update_window.UpdateWindow(Iface())
        try:
            search.reload_local_paths()
            expected_root = tmp_path / "local" / "Cactvs" / "BasesPlugin"
            expected_database = str(expected_root / "car_microcredito.db")
            expected_car = str(expected_root / "car")

            for window in (search, batch, document, updates):
                labels = {label.text() for label in window.findChildren(QLabel)}
                assert "Banco SQLite" not in labels
                assert "Polígonos do CAR" not in labels
                fields = {field.text() for field in window.findChildren(QLineEdit)}
                assert expected_database not in fields
                assert expected_car not in fields
                buttons = {button.text() for button in window.findChildren(QPushButton)}
                assert "Selecionar…" not in buttons
                assert not any("Configuração da base local" in text for text in buttons)
            titles = {group.title() for group in search.findChildren(QGroupBox)}
            assert "1. Identificar operação" in titles
            assert "2. Operações encontradas" in titles
            assert search.document.placeholderText() == "CPF ou CNPJ"
            assert (
                search.car.placeholderText() == "Número do CAR informado pelo cliente"
            )
            assert not updates.release_path.isReadOnly()
        finally:
            for window in (updates, document, batch, search):
                window.close()


def test_consultation_ignores_legacy_settings_and_uses_fixed_database(
    tmp_path: Path,
) -> None:
    context, settings_factory = _window_context(tmp_path)
    with context:
        fixed_root = tmp_path / "local" / "Cactvs" / "BasesPlugin"
        fixed_database = fixed_root / "car_microcredito.db"
        connection = connect(fixed_database)
        initialize(connection)
        connection.close()

        settings = settings_factory()
        settings.setValue("database", r"C:\kit-antigo\banco-inexistente.db")
        settings.setValue("car_base", r"C:\kit-antigo\car")
        settings.sync()

        window = plugin.SearchWindow(Iface())
        try:
            window.reload_local_paths()
            window.document.setText("12345678901")
            with patch.object(QMessageBox, "critical") as critical:
                window.search()

            assert not critical.called, critical.call_args
            assert window.local_paths.database == fixed_database
        finally:
            window.close()


def test_auxiliary_actions_ignore_legacy_path_preferences(tmp_path: Path) -> None:
    context, settings_factory = _window_context(tmp_path)
    with context:
        settings = settings_factory()
        settings.setValue("database", r"C:\kit-antigo\banco-inexistente.db")
        settings.setValue("car_base", r"C:\kit-antigo\car")
        settings.sync()
        fixed_root = tmp_path / "local" / "Cactvs" / "BasesPlugin"
        fixed_database = fixed_root / "car_microcredito.db"
        fixed_car = fixed_root / "car"
        connection = connect(fixed_database)
        initialize(connection)
        connection.close()
        fixed_car.mkdir(parents=True)

        batch = batch_window.BatchWindow(Iface(), plugin._load_core)
        document = car_document_window.CarDocumentWindow(Iface(), plugin._load_core)
        try:
            batch.output_path.setText(str(tmp_path / "relatorios"))
            database, car_base, _output = batch._paths()
            assert database == fixed_database
            assert car_base == fixed_car

            document_connection = document._connection()
            try:
                database_file = document_connection.execute(
                    "PRAGMA database_list"
                ).fetchone()[2]
            finally:
                document_connection.close()
            assert Path(database_file).resolve() == fixed_database.resolve()
        finally:
            document.close()
            batch.close()


def test_consultation_connections_are_readonly(tmp_path: Path) -> None:
    context, _settings_factory = _window_context(tmp_path)
    with context:
        fixed_database = (
            tmp_path / "local" / "Cactvs" / "BasesPlugin" / "car_microcredito.db"
        )
        connection = connect(fixed_database)
        initialize(connection)
        connection.close()
        search = plugin.SearchWindow(Iface())
        document = car_document_window.CarDocumentWindow(Iface(), plugin._load_core)
        batch = batch_window.BatchWindow(Iface(), plugin._load_core)
        try:
            search_connection = search._connection()
            document_connection = document._connection()
            batch_connection = batch.core_loader()[0](fixed_database)
            for readonly_connection in (
                search_connection,
                document_connection,
                batch_connection,
            ):
                try:
                    assert readonly_connection.execute("PRAGMA query_only").fetchone()[
                        0
                    ]
                    with pytest.raises(sqlite3.OperationalError, match="readonly"):
                        readonly_connection.execute(
                            "CREATE TABLE proibida (id INTEGER)"
                        )
                finally:
                    readonly_connection.close()
        finally:
            batch.close()
            document.close()
            search.close()


def test_update_failure_never_claims_that_nothing_was_modified(tmp_path: Path) -> None:
    context, _settings_factory = _window_context(tmp_path)
    with context:
        window = update_window.UpdateWindow(Iface())
        message = (
            "A atualização falhou e nem todas as bases puderam ser restauradas; "
            "interrompa o uso do plugin."
        )
        try:
            with patch.object(QMessageBox, "warning") as warning:
                window._worker_failed(message)
            assert "Nenhuma base foi modificada" not in window.status_label.text()
            assert message in window.status_label.text()
            assert warning.call_args.args[2] == message
        finally:
            window.close()


def test_update_window_accepts_fixed_location_before_database_exists(
    tmp_path: Path,
) -> None:
    context, _settings_factory = _window_context(tmp_path)
    with context:
        window = update_window.UpdateWindow(Iface())
        try:
            expected_root = tmp_path / "local" / "Cactvs" / "BasesPlugin"
            expected = expected_root / "car_microcredito.db"
            assert window._database_path() == expected.resolve()
            assert not expected_root.exists()
        finally:
            window.close()
