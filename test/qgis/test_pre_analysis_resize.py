"""The analyst can allocate more space to a long technical justification."""

from __future__ import annotations

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QRect
from qgis.PyQt.QtGui import QFont, QScreen
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QPlainTextEdit,
    QSplitter,
)
from test_pre_analysis_window import (
    JUSTIFICATION,
    button_named,
    interact_with_pre_analysis,
)
from test_pre_analysis_window import (
    analysis_window as analysis_window,
)

from plugin import plugin


def test_analyst_can_expand_the_technical_justification_without_losing_text(
    analysis_window: plugin.SearchWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        QScreen, "availableGeometry", lambda _screen: QRect(0, 0, 1280, 720)
    )
    font = QFont(analysis_window.font())
    font.setPointSize(12)
    analysis_window.setFont(font)
    long_justification = "\n".join([JUSTIFICATION] * 8)

    def expand_the_editor(dialog: QDialog) -> None:
        editor = dialog.findChild(QPlainTextEdit, "technicalDecisionJustification")
        editor.setPlainText(long_justification)
        splitter = dialog.findChild(QSplitter, "preAnalysisSplitter")
        assert splitter is not None, (
            "O tecnico nao consegue ajustar o espaco entre regras e justificativa."
        )
        assert splitter.isVisibleTo(dialog)
        span = splitter.height()
        splitter.setSizes([3 * span // 4, span // 4])
        QApplication.processEvents()
        compact_height = editor.height()
        splitter.setSizes([span // 4, 3 * span // 4])
        QApplication.processEvents()
        assert editor.height() >= compact_height + 30, (
            "Ampliar o painel de decisao nao aumenta o espaco de escrita."
        )
        assert editor.toPlainText() == long_justification
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, expand_the_editor)
