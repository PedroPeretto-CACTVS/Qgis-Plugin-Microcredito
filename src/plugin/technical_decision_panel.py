"""Consultation controls for the analysis owner's recorded technical decision."""

from __future__ import annotations

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)
from qgis_plugin_microcredito.application.pre_analysis import TECHNICAL_DECISIONS


class _DecisionJustification(QPlainTextEdit):
    """Start with three readable lines, leaving the parent's scroll available."""

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setHeight(max(65, 3 * self.fontMetrics().lineSpacing() + 16))
        return hint


class TechnicalDecisionPanel(QGroupBox):
    """Present automatic and recorded results; the caller validates and stores."""

    submitted = pyqtSignal(str, str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Resultado e decisão técnica", parent)
        self.setObjectName("consultationDecisionPanel")
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self.result = QLabel()
        self.result.setObjectName("consultationDecisionResult")
        self.result.setTextFormat(Qt.TextFormat.PlainText)
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        form.addRow(self.result)

        self.automatic_result = QLabel()
        self.automatic_result.setObjectName("consultationAutomaticResult")
        self.automatic_result.setTextFormat(Qt.TextFormat.PlainText)
        self.automatic_result.setWordWrap(True)
        form.addRow(self.automatic_result)

        self.combo = QComboBox()
        self.combo.setObjectName("consultationDecisionCombo")
        self.combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.combo.setMinimumContentsLength(16)
        for code, label in TECHNICAL_DECISIONS:
            self.combo.addItem(label, code)
        form.addRow("Decisão", self.combo)

        self.justification = _DecisionJustification()
        self.justification.setObjectName("consultationDecisionJustification")
        self.justification.setMinimumHeight(65)
        self.justification.setPlaceholderText(
            "Registre documentos, exceções, condicionantes e fundamento da decisão."
        )
        form.addRow("Justificativa", self.justification)

        self.register = QPushButton("Registrar decisão")
        self.register.setObjectName("registerConsultationDecision")
        self.register.clicked.connect(self._submit)
        form.addRow(self.register)
        self.controls = (self.combo, self.justification, self.register)

        self.notice = QLabel()
        self.notice.setObjectName("notice")
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        self.notice.setWordWrap(True)
        form.addRow(self.notice)
        self.show_analysis({}, {}, ready=False)

    def _submit(self) -> None:
        self.submitted.emit(
            str(self.combo.currentData() or "pendente"),
            self.combo.currentText(),
            self.justification.toPlainText().strip(),
        )

    def set_ready(self, ready: bool) -> None:
        """Enable manual recording when the caller's consultation permits it."""
        for control in self.controls:
            control.setEnabled(ready)
        self.notice.setText(
            "Registre sua avaliação manual aqui sem executar a pré-análise automática. "
            "Alterar os campos só modifica o resultado após registrar."
            if ready
            else "Informe o CAR para registrar sua avaliação manual."
        )

    def show_analysis(
        self,
        pre_analysis: dict[str, object],
        decision: dict[str, object],
        *,
        ready: bool,
        reset_editor: bool = True,
    ) -> None:
        """Show a saved decision first, without treating unsaved edits as saved."""
        code = str(decision.get("codigo") or "pendente")
        label = dict(TECHNICAL_DECISIONS).get(code)
        automatic = str(pre_analysis.get("classificacao_geral_rotulo") or "")
        has_decision = bool(label and code != "pendente")
        is_manual = decision.get("origem") == "analise_manual"
        if has_decision:
            self.result.setText(f"Decisão técnica registrada: {label}")
        elif automatic:
            self.result.setText(f"Pré-análise automática: {automatic}")
        else:
            self.result.setText("Pré-análise pendente")
        secondary = ""
        if has_decision and automatic:
            secondary = f"Pré-análise automática: {automatic}"
        elif has_decision and is_manual:
            secondary = "Pré-análise automática não executada"
        self.automatic_result.setText(secondary)
        self.automatic_result.setVisible(bool(secondary))
        if reset_editor:
            index = self.combo.findData(code)
            self.combo.setCurrentIndex(index if index >= 0 else 0)
            self.justification.setPlainText(str(decision.get("justificativa") or ""))
        self.set_ready(ready)
        if has_decision and is_manual:
            self.notice.setText(
                "Avaliação manual registrada pelo técnico. Os resultados automáticos "
                "são apresentados separadamente e podem ter sido calculados após "
                "o registro; não são tratados como revisados pelo técnico."
                if automatic
                else "Avaliação manual registrada pelo técnico, sem pré-análise automática."
            )
