"""Spreadsheet validation gives actionable guidance through the actual UI button."""

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtWidgets import QMessageBox, QPushButton

from plugin import batch_window, plugin


class Iface:
    @staticmethod
    def mainWindow() -> None:
        return None


@pytest.mark.parametrize("selection", ["empty", "whitespace", "directory", "missing"])
def test_validate_button_requests_an_existing_spreadsheet(
    tmp_path: Path, selection: str
) -> None:
    paths = {
        "empty": "",
        "whitespace": "   ",
        "directory": str(tmp_path),
        "missing": str(tmp_path / "inexistente.xlsx"),
    }
    window = batch_window.BatchWindow(Iface(), plugin._load_core)
    try:
        window.xlsx_path.setText(paths[selection])
        button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.text() == "Validar planilha"
        )
        with patch.object(QMessageBox, "critical") as message:
            button.click()

        assert message.call_args is not None
        assert message.call_args.args[1:] == (
            "Planilha inválida",
            "Selecione uma planilha Excel (.xlsx) existente antes de validar.",
        )
        assert window.table.rowCount() == 0
    finally:
        window.close()
