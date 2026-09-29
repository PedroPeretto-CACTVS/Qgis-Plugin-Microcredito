"""Consulta local e controlada de CPF/CNPJ vinculados a um CAR no Sicor."""
from __future__ import annotations

from pathlib import Path

from qgis_plugin_microcredito.domain.normalize import (
    mask_document,
    normalize_car,
    normalize_document,
)

from qgis.PyQt.QtCore import QSettings, Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

class CarDocumentWindow(QDialog):
    """Mostra evidências CAR→documento sem presumir titularidade do imóvel."""

    COLUMNS = (
        ("tipo_documento", "Tipo"),
        ("documento", "CPF/CNPJ"),
        ("tipo_vinculo", "Vínculo encontrado"),
        ("ref_bacen", "Ref. Bacen"),
        ("nu_ordem", "Ordem"),
        ("base_origem", "Base/evidência"),
        ("importado_em", "Importado em"),
    )

    LINK_LABELS = {
        "documento_na_propriedade": "Documento no registro de propriedade do Sicor",
        "mutuario_da_operacao": "Mutuário com a mesma Ref. Bacen",
    }

    def __init__(self, iface, load_core):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.load_core = load_core
        self.settings = QSettings("Cactvs", "CARMicrocredito")
        self.results: list[dict[str, object]] = []
        self.revealed_row = -1
        self.reveal_generation = 0

        self.setWindowTitle("CAR Microcrédito | Consultar CPF/CNPJ por CAR")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "icon.svg")))
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setMinimumSize(820, 470)
        self.resize(1120, 620)
        self.setStyleSheet("""
            QDialog { background: #f4f7f5; }
            QLabel#title { color: #165c41; font-size: 19px; font-weight: 700; }
            QLabel#notice { color: #5e6d67; padding: 3px; }
            QLabel#status { background: #edf5f1; color: #25483b; border-radius: 5px; padding: 8px; }
            QLineEdit { min-height: 30px; padding: 0 8px; border: 1px solid #aebdb7;
                        border-radius: 5px; background: white; }
            QPushButton { min-height: 30px; padding: 0 14px; border: 1px solid #9aaba4;
                          border-radius: 5px; background: white; color: #243d34; font-weight: 600; }
            QPushButton:hover { background: #edf5f1; border-color: #2b7a59; }
            QPushButton#primary { background: #19734f; color: white; border-color: #165c41; }
            QTableWidget { background: white; border: 1px solid #ccd8d3; border-radius: 6px;
                           gridline-color: #e0e7e4; alternate-background-color: #f4f8f6; }
            QHeaderView::section { background: #e7f0ec; color: #25483b; padding: 7px;
                                   border: 0; border-right: 1px solid #ccd8d3; font-weight: 600; }
        """)

        title = QLabel("Consultar CPF/CNPJ vinculado a um CAR")
        title.setObjectName("title")
        introduction = QLabel(
            "A consulta é feita somente no banco SQLite local. O resultado identifica documentos "
            "presentes no registro de propriedade ou vinculados à mesma Ref. Bacen no Sicor; "
            "não comprova a titularidade atual do imóvel."
        )
        introduction.setObjectName("notice")
        introduction.setWordWrap(True)

        self.database = QLineEdit(self.settings.value("database", "", type=str))
        self.database.setPlaceholderText("Selecione o arquivo car_microcredito.db")
        choose_database = QPushButton("Selecionar…")
        choose_database.clicked.connect(self._select_database)
        database_row = QHBoxLayout()
        database_row.addWidget(QLabel("Banco SQLite"))
        database_row.addWidget(self.database, 1)
        database_row.addWidget(choose_database)

        self.car = QLineEdit()
        self.car.setPlaceholderText("Informe o número completo do CAR")
        self.car.setClearButtonEnabled(True)
        search = QPushButton("Buscar vínculos no Sicor")
        search.setObjectName("primary")
        search.clicked.connect(self.search)
        self.car.returnPressed.connect(self.search)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Número do CAR"))
        search_row.addWidget(self.car, 1)
        search_row.addWidget(search)

        self.status = QLabel("Informe o CAR completo para iniciar. Os documentos permanecerão mascarados.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        self.reveal = QPushButton("Revelar selecionado por 30 s")
        self.reveal.setToolTip("Exibe temporariamente o documento completo da linha selecionada")
        self.reveal.clicked.connect(self.reveal_selected)
        self.reveal.setEnabled(False)
        self.hide_documents = QPushButton("Ocultar documentos")
        self.hide_documents.clicked.connect(self.mask_all)
        self.hide_documents.setEnabled(False)
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addWidget(self.reveal)
        actions.addWidget(self.hide_documents)
        actions.addStretch(1)
        actions.addWidget(close)

        privacy = QLabel(
            "Privacidade: a ferramenta não envia CAR ou CPF/CNPJ ao GitHub, não exporta os resultados "
            "e não grava o documento pesquisado em log. Use a revelação somente para finalidade autorizada."
        )
        privacy.setObjectName("notice")
        privacy.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(9)
        layout.addWidget(title)
        layout.addWidget(introduction)
        layout.addLayout(database_row)
        layout.addLayout(search_row)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)
        layout.addWidget(privacy)
        layout.addLayout(actions)

    def _select_database(self):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Selecionar banco SQLite", self.database.text(), "SQLite (*.db *.sqlite);;Todos os arquivos (*)"
        )
        if selected:
            self.database.setText(selected)
            self.settings.setValue("database", selected)

    def _connection(self):
        path = self.database.text().strip()
        if not path:
            raise ValueError("Selecione o banco car_microcredito.db antes de consultar.")
        if not Path(path).is_file():
            raise ValueError("O banco SQLite selecionado não existe.")
        self.settings.setValue("database", path)
        connect, initialize, *_ = self.load_core()
        connection = connect(path)
        initialize(connection)
        return connection

    def search(self):
        car_value = self.car.text().strip()
        if not normalize_car(car_value):
            QMessageBox.information(self, "CAR obrigatório", "Informe o número completo do CAR.")
            return
        self.mask_all()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.status.setText("Consultando o banco local…")
        QApplication.processEvents()
        try:
            *_, find_documents_by_car, _, _ = self.load_core()
            connection = self._connection()
            try:
                self.results = find_documents_by_car(connection, car_value)
            finally:
                connection.close()
            self._fill_table()
            documents = {
                normalize_document(row.get("documento_normalizado"))
                for row in self.results
                if normalize_document(row.get("documento_normalizado"))
            }
            if documents:
                self.status.setText(
                    f"{len(documents)} documento(s) distinto(s) encontrado(s) em "
                    f"{len(self.results)} evidência(s). Confira o tipo de vínculo; o resultado não prova titularidade."
                )
            else:
                self.status.setText(
                    "Nenhum CPF/CNPJ foi localizado para este CAR nas edições ativas do Sicor. "
                    "A ausência não comprova inexistência de vínculo."
                )
        except Exception as exc:
            self.results = []
            self._fill_table()
            QMessageBox.critical(self, "Falha na consulta", str(exc))
            self.status.setText("A consulta não foi concluída.")
        finally:
            QApplication.restoreOverrideCursor()

    def _fill_table(self):
        self.revealed_row = -1
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.results))
        for row_index, result in enumerate(self.results):
            document = normalize_document(result.get("documento_normalizado"))
            values = {
                **result,
                "tipo_documento": "CPF" if len(document) == 11 else "CNPJ" if len(document) == 14 else "Indisponível",
                "documento": mask_document(document),
                "tipo_vinculo": self.LINK_LABELS.get(
                    str(result.get("tipo_vinculo") or ""), str(result.get("tipo_vinculo") or "")
                ),
            }
            # Garante que o valor mascarado prevaleça sobre qualquer campo de origem.
            values["documento"] = mask_document(document)
            for column_index, (field, _) in enumerate(self.COLUMNS):
                item = QTableWidgetItem(str(values.get(field) or ""))
                item.setData(Qt.UserRole, row_index)
                self.table.setItem(row_index, column_index, item)
        self.table.setSortingEnabled(True)
        if self.results:
            self.table.selectRow(0)
        self._update_buttons()

    def _selected_source_row(self) -> int:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        source_row = item.data(Qt.UserRole) if item else None
        if source_row is None or not 0 <= int(source_row) < len(self.results):
            return -1
        return int(source_row)

    def _update_buttons(self):
        has_selection = self._selected_source_row() >= 0
        self.reveal.setEnabled(has_selection)
        self.hide_documents.setEnabled(bool(self.results))

    def reveal_selected(self):
        source_row = self._selected_source_row()
        if source_row < 0:
            return
        answer = QMessageBox.question(
            self,
            "Exibir dado pessoal",
            "O CPF/CNPJ será exibido nesta tela por 30 segundos. Use-o somente para a finalidade "
            "autorizada da análise de crédito. O vínculo Sicor não comprova titularidade atual.\n\nContinuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        document = normalize_document(
            self.results[source_row].get("documento_normalizado")
        )
        if not document:
            QMessageBox.information(self, "Documento indisponível", "A fonte não contém um CPF/CNPJ completo.")
            return
        visible_row = self.table.currentRow()
        self.mask_all()
        item = self.table.item(visible_row, 1)
        if item:
            item.setText(document)
            self.revealed_row = visible_row
        self.reveal_generation += 1
        generation = self.reveal_generation
        self.status.setText("Documento revelado temporariamente. Ele será ocultado automaticamente em 30 segundos.")
        QTimer.singleShot(30_000, lambda: self._expire_reveal(generation))

    def _expire_reveal(self, generation: int):
        if generation == self.reveal_generation:
            self.mask_all()
            self.status.setText("Tempo de exibição encerrado. Os documentos voltaram a ser mascarados.")

    def mask_all(self):
        self.reveal_generation += 1
        for visible_row in range(self.table.rowCount()):
            first = self.table.item(visible_row, 0)
            source_row = first.data(Qt.UserRole) if first else None
            if source_row is None or not 0 <= int(source_row) < len(self.results):
                continue
            document = self.results[int(source_row)].get("documento_normalizado")
            item = self.table.item(visible_row, 1)
            if item:
                item.setText(mask_document(document))
        self.revealed_row = -1

    def closeEvent(self, event):
        self.mask_all()
        self.results.clear()
        self.table.setRowCount(0)
        self.car.clear()
        self.status.setText("Informe o CAR completo para iniciar. Os documentos permanecerão mascarados.")
        super().closeEvent(event)
