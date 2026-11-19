"""Long explanations can be read gradually even when a row exceeds the viewport."""

from __future__ import annotations

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QRect
from qgis.PyQt.QtGui import QFont, QScreen
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QTableWidget,
)
from test_pre_analysis_window import (
    analysis_window as analysis_window,
)
from test_pre_analysis_window import button_named, interact_with_pre_analysis

from plugin import plugin


def test_analyst_can_scroll_gradually_through_an_explanation_taller_than_the_view(
    analysis_window: plugin.SearchWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        QScreen, "availableGeometry", lambda _screen: QRect(0, 0, 1280, 900)
    )
    font = QFont(analysis_window.font())
    font.setPointSize(12)
    analysis_window.setFont(font)

    def read_gradually(dialog: QDialog) -> None:
        dialog.resize(720, 650)
        QTest.qWait(30)
        table = dialog.findChild(QTableWidget, "preAnalysisTable")
        candidates = [
            row
            for row in range(table.rowCount())
            if table.rowHeight(row) > table.viewport().height()
        ]
        assert candidates, (
            "O exemplo precisa de um fundamento maior que a area visivel."
        )
        index = table.model().index(candidates[0], 2)
        table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
        QApplication.processEvents()
        scrollbar = table.verticalScrollBar()
        assert scrollbar.value() < scrollbar.maximum()
        before = table.visualRect(index).top()
        scrollbar.setValue(scrollbar.value() + 1)
        QApplication.processEvents()
        moved = before - table.visualRect(index).top()
        assert 0 < moved <= 2 * table.fontMetrics().height(), (
            "Um pequeno ajuste da rolagem pula um fundamento inteiro, "
            "impedindo ler seu fim."
        )
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, read_gradually)
