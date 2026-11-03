"""A freshly installed package remains usable through the existing QGIS screen."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QMessageBox, QPushButton

from installer.cli import app as installer_app
from installer.install import install_package
from plugin import plugin
from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)

SYNTHETIC_DOCUMENT = "12345678901"
SYNTHETIC_CAR = "MT-5100102-00000000000000000000000000000001"


class Iface:
    @staticmethod
    def mainWindow() -> None:
        return None


@pytest.mark.parametrize("provisioning_command", ["install", "migrate"])
@pytest.mark.parametrize("prior_settings", ["new", "stale"])
def test_installed_fixed_bases_are_queried_after_package_moves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prior_settings: str,
    provisioning_command: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "installer"))
    from test_installer import _write_package

    settings_file = tmp_path / "home/.config/Cactvs/CARMicrocredito.conf"
    settings_file.parent.mkdir(parents=True)
    settings = QSettings(str(settings_file), QSettings.IniFormat)
    if prior_settings == "stale":
        settings.setValue("database", str(tmp_path / "removed-kit/old.db"))
        settings.setValue("car_base", str(tmp_path / "removed-kit/car"))
        settings.sync()
    if sys.platform == "win32":
        import winreg

        handle = object()

        def create_key(root, name):
            assert root == winreg.HKEY_CURRENT_USER
            assert name == r"Software\Cactvs\CARMicrocredito"
            return handle

        def set_value(key, name, reserved, kind, value):
            assert key is handle and kind == winreg.REG_SZ
            assert name in {"database", "car_base"}
            settings.setValue(name, value)
            settings.sync()

        # The OS registry boundary is routed into an actual isolated Qt INI file.
        # No installer or query behavior is mocked and no native key is touched.
        monkeypatch.setattr(winreg, "CreateKey", create_key)
        monkeypatch.setattr(winreg, "SetValueEx", set_value)
        monkeypatch.setattr(winreg, "CloseKey", lambda key: None)
    monkeypatch.setattr(plugin, "QSettings", lambda *_args, **_kwargs: settings)
    package = _write_package(tmp_path)
    source_database = package / "arquivos/dados/car_microcredito.db"
    with sqlite3.connect(source_database) as connection:
        connection.execute(
            "INSERT INTO importacao (id,tipo,arquivo,sha256,total_linhas,linhas_validas,escopo,ativo) "
            "VALUES (1,'propriedades','synthetic.csv',?,1,1,'nacional',1)",
            ("a" * 64,),
        )
        connection.execute(
            "INSERT INTO sicor_propriedade (importacao_id,ref_bacen,nu_ordem,documento_original,"
            "documento_normalizado,car_original,car_normalizado) VALUES (1,'synthetic-operation','1',?,?,?,?)",
            (
                SYNTHETIC_DOCUMENT,
                SYNTHETIC_DOCUMENT,
                SYNTHETIC_CAR,
                SYNTHETIC_CAR.replace("-", ""),
            ),
        )
    connection.close()
    manifest_path = package / "MANIFESTO_SHA256.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[source_database.relative_to(package).as_posix()] = hashlib.sha256(
        source_database.read_bytes()
    ).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    if provisioning_command == "install":
        installed = install_package(
            package, profiles_root=tmp_path / "profiles", skip_qgis_check=True
        )
        assert installed[0].is_dir()
    else:
        # Model the closed-QGIS process-list boundary; queries and migration run real.
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: subprocess.CompletedProcess(
                "tasklist", 0, stdout=""
            ),
        )
        result = CliRunner().invoke(
            installer_app, ["migrate-bases", str(source_database)]
        )
        assert result.exit_code == 0, result.output
    package.rename(tmp_path / "package-moved")
    paths = default_local_data_paths()
    window = plugin.SearchWindow(Iface())
    try:
        window.document.setText(SYNTHETIC_DOCUMENT)
        button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.text() == "Buscar operações"
        )
        with patch.object(QMessageBox, "critical") as critical:
            button.click()
        assert not critical.called, critical.call_args
        assert window.table.rowCount() == 1
        assert window.table.item(0, 1).text() == SYNTHETIC_CAR
        assert Path(window.db_path.text()).resolve() == paths.database.resolve()
        assert Path(window.car_base_path.text()).resolve() == paths.car.resolve()
    finally:
        window.close()
