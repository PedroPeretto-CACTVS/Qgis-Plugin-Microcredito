"""Readable pre-analysis widgets; the caller owns recording the decision."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from qgis.PyQt.QtCore import QEvent, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QResizeEvent, QShowEvent
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qgis_plugin_microcredito.application.pre_analysis import TECHNICAL_DECISIONS


class _RulesTable(QTableWidget):
    """Reflow full explanations after the visible column widths settle."""

    def __init__(self, rows: int, columns: int) -> None:
        super().__init__(rows, columns)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self._reflow_timer = QTimer(self)
        self._reflow_timer.setSingleShot(True)
        self._reflow_timer.setInterval(0)
        self._reflow_timer.timeout.connect(self.resizeRowsToContents)
        self.horizontalHeader().sectionResized.connect(self._queue_reflow)

    def _queue_reflow(self) -> None:
        self._reflow_timer.start()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._queue_reflow()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._queue_reflow()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
            QEvent.Type.StyleChange,
        ):
            self._queue_reflow()


def build_pre_analysis_dialog(
    parent: QWidget,
    pre_analysis: dict[str, object],
    existing_decision: dict[str, object],
    on_record: Callable[[str, str, str], bool],
) -> QDialog:
    """Build the decision dialog without changing the caller's analysis state."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Pré-análise normativa para decisão técnica")
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
    dialog.setSizeGripEnabled(True)
    available = parent.screen().availableGeometry()
    dialog.setMinimumSize(
        min(640, max(240, available.width() - 40)),
        min(360, max(200, available.height() - 40)),
    )
    dialog.resize(
        min(1160, int(available.width() * 0.92)),
        min(700, int(available.height() * 0.88)),
    )

    layout = QVBoxLayout(dialog)
    content = QWidget()
    content_layout = QVBoxLayout(content)
    title = QLabel("Pré-análise das regras para apoio à decisão")
    title.setObjectName("title")
    content_layout.addWidget(title)
    decision_code = str(existing_decision.get("codigo") or "pendente")
    decision_label = dict(TECHNICAL_DECISIONS).get(decision_code)
    has_recorded_decision = bool(decision_label and decision_code != "pendente")
    if has_recorded_decision:
        recorded_result = QLabel(f"Decisão técnica registrada: {decision_label}")
        recorded_result.setObjectName("preAnalysisRecordedDecision")
        recorded_result.setTextFormat(Qt.TextFormat.PlainText)
        recorded_result.setWordWrap(True)
        recorded_result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        content_layout.addWidget(recorded_result)
    automatic_prefix = "Pré-análise automática: " if has_recorded_decision else ""
    summary = QLabel(
        f"<b>{automatic_prefix}{pre_analysis.get('classificacao_geral_rotulo')}</b><br>"
        f"{pre_analysis.get('resumo')}"
    )
    summary.setObjectName("preAnalysisSummary")
    summary.setWordWrap(True)
    summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    content_layout.addWidget(summary)

    explanation = QLabel(
        "A ferramenta interpreta cada fonte e aponta possíveis impedimentos, "
        "lacunas ou ausência de indício. Ela não decide a contratação."
    )
    explanation.setObjectName("notice")
    explanation.setWordWrap(True)
    content_layout.addWidget(explanation)

    splitter = QSplitter(Qt.Orientation.Vertical)
    splitter.setObjectName("preAnalysisSplitter")
    splitter.setChildrenCollapsible(False)
    splitter.setMinimumHeight(360)
    splitter.setHandleWidth(8)
    splitter.setToolTip(
        "Arraste a divisória para ajustar o espaço das regras e da justificativa"
    )
    content_layout.addWidget(splitter, 1)

    columns = (
        "Regra / fonte",
        "Conclusão",
        "Fundamento",
        "Providência",
    )
    rules = cast(list[dict[str, object]], pre_analysis.get("regras") or [])
    table = _RulesTable(len(rules), len(columns))
    table.setObjectName("preAnalysisTable")
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    backgrounds = {
        "possivel_impedimento": QColor("#FDECEC"),
        "sem_indicio_impedimento": QColor("#EAF5EF"),
        "inconclusivo": QColor("#FFF5D6"),
        "validacao_tecnica": QColor("#EAF1FB"),
    }
    for row, item in enumerate(rules):
        result_code = str(item.get("classificacao") or "inconclusivo")
        foundation = (
            f"{item.get('entendimento_regra', '')} Resultado desta consulta: "
            f"{item.get('fundamento_resultado', '')}"
        )
        values = (
            item.get("regra"),
            item.get("classificacao_rotulo"),
            foundation,
            item.get("providencia_tecnica"),
        )
        background = backgrounds.get(result_code, QColor("#FFFFFF"))
        for column, value in enumerate(values):
            cell = QTableWidgetItem(str(value or ""))
            cell.setBackground(background)
            cell.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            reference = str(item.get("referencia") or "")
            cell.setToolTip(
                str(value or "") + (f"\n\nReferência: {reference}" if reference else "")
            )
            table.setItem(row, column, cell)
    header = table.horizontalHeader()
    header.setMinimumSectionSize(80)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    splitter.addWidget(table)

    decision_group = QGroupBox("Decisão do técnico responsável pela contratação")
    decision_form = QFormLayout(decision_group)
    decision_form.setFieldGrowthPolicy(
        QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
    )
    decision_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    decision = QComboBox()
    decision.setObjectName("technicalDecisionCombo")
    for code, label in TECHNICAL_DECISIONS:
        decision.addItem(label, code)
    justification = QPlainTextEdit()
    justification.setObjectName("technicalDecisionJustification")
    justification.setPlaceholderText(
        "Registre documentos, exceções, condicionantes e fundamento da decisão."
    )
    justification.setMinimumHeight(60)
    existing_index = decision.findData(
        str(existing_decision.get("codigo") or "pendente")
    )
    decision.setCurrentIndex(existing_index if existing_index >= 0 else 0)
    justification.setPlainText(str(existing_decision.get("justificativa") or ""))
    decision_form.addRow("Conclusão", decision)
    decision_form.addRow("Justificativa", justification)
    splitter.addWidget(decision_group)
    splitter.setStretchFactor(0, 3)
    splitter.setStretchFactor(1, 2)
    splitter.setSizes([240, 180])

    scroll = QScrollArea()
    scroll.setObjectName("preAnalysisScroll")
    scroll.setWidgetResizable(True)
    scroll.setWidget(content)
    layout.addWidget(scroll, 1)

    actions = QHBoxLayout()
    actions.addStretch(1)
    close = QPushButton("Fechar sem alterar")
    close.clicked.connect(dialog.reject)
    actions.addWidget(close)
    register = QPushButton("Registrar decisão técnica")
    register.setObjectName("primary")

    def register_decision() -> None:
        if on_record(
            str(decision.currentData() or "pendente"),
            decision.currentText(),
            justification.toPlainText().strip(),
        ):
            dialog.accept()

    register.clicked.connect(register_decision)
    actions.addWidget(register)
    layout.addLayout(actions)
    return dialog
