"""The analyst can reach the decision controls on different screen sizes."""

from __future__ import annotations

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QPoint, QRect
from qgis.PyQt.QtGui import QFont, QScreen
from qgis.PyQt.QtWidgets import QApplication, QDialog
from test_pre_analysis_window import (
    analysis_window as analysis_window,
)
from test_pre_analysis_window import button_named, interact_with_pre_analysis

from plugin import plugin


@pytest.mark.parametrize("screen_size", [(910, 512), (1280, 720)])
@pytest.mark.parametrize("font_size", [10, 12])
def test_pre_analysis_fits_the_screen_with_reachable_decision_actions(
    analysis_window: plugin.SearchWindow,
    monkeypatch: pytest.MonkeyPatch,
    screen_size: tuple[int, int],
    font_size: int,
) -> None:
    available = QRect(0, 0, *screen_size)
    monkeypatch.setattr(QScreen, "availableGeometry", lambda _screen: available)
    font = QFont(analysis_window.font())
    font.setPointSize(font_size)
    analysis_window.setFont(font)

    def read_and_close(dialog: QDialog) -> None:
        QApplication.processEvents()
        frame = dialog.frameGeometry()
        assert frame.width() <= available.width(), (
            "A pre-analise abre mais larga que a area util da tela."
        )
        assert frame.height() <= available.height(), (
            "A pre-analise abre mais alta que a area util da tela."
        )
        for text in ("Fechar sem alterar", "Registrar decisão técnica"):
            action = button_named(dialog, text)
            action_rect = QRect(action.mapTo(dialog, QPoint()), action.size())
            assert action.isVisibleTo(dialog)
            assert dialog.rect().contains(action_rect), (
                f"A acao {text!r} ficou fora da janela."
            )
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, read_and_close)
