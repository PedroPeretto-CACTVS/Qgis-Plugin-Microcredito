"""Rule explanations remain fully readable when the analyst resizes the window."""

from __future__ import annotations

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QRect
from qgis.PyQt.QtGui import QFont, QScreen
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QStyleOptionViewItem,
    QTableWidget,
)
from test_pre_analysis_window import (
    analysis_window as analysis_window,
)
from test_pre_analysis_window import button_named, interact_with_pre_analysis

from plugin import plugin


def test_long_rule_explanations_reflow_when_the_window_is_narrowed(
    analysis_window: plugin.SearchWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        QScreen, "availableGeometry", lambda _screen: QRect(0, 0, 1280, 900)
    )
    font = QFont(analysis_window.font())
    font.setPointSize(12)
    analysis_window.setFont(font)

    def read_rules(dialog: QDialog) -> None:
        table = dialog.findChild(QTableWidget, "preAnalysisTable")
        assert table.rowCount() > 0
        row = max(
            range(table.rowCount()), key=lambda index: len(table.item(index, 2).text())
        )
        original_text = table.item(row, 2).text()

        dialog.resize(1140, 700)
        QTest.qWait(30)
        wide_column = table.columnWidth(2)
        wide_height = table.rowHeight(row)
        dialog.resize(720, 700)
        QTest.qWait(30)
        assert table.columnWidth(2) < wide_column
        assert table.rowHeight(row) > wide_height + table.fontMetrics().height(), (
            "As linhas nao acompanham a quebra do texto ao estreitar a janela."
        )

        for column in range(table.columnCount()):
            index = table.model().index(row, column)
            option = QStyleOptionViewItem()
            option.initFrom(table)
            option.rect = QRect(0, 0, table.columnWidth(column), 0)
            option.features |= QStyleOptionViewItem.ViewItemFeature.WrapText
            required = table.itemDelegate().sizeHint(option, index).height()
            assert table.rowHeight(row) >= required, (
                "O fundamento ou a providencia depende do tooltip para leitura integral."
            )
        assert table.item(row, 2).text() == original_text

        dialog.resize(1140, 700)
        QTest.qWait(30)
        QApplication.processEvents()
        assert table.rowHeight(row) <= wide_height + table.fontMetrics().height(), (
            "Ampliar a janela deixa espaco vazio excessivo nas linhas."
        )
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, read_rules)
