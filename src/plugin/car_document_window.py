"""Consulta local e controlada de CPF/CNPJ vinculados a um CAR no Sicor."""

from __future__ import annotations

from pathlib import Path

from qgis_plugin_microcredito.domain.normalize import (
    normalize_car,
    normalize_document,
)

try:
    from qgis_plugin_microcredito.domain.normalize import format_document
except ImportError:
    # O QGIS pode manter o módulo da versão anterior em memória após instalar
    # um ZIP novo. Esta ponte permite abrir a 0.9.5 antes mesmo de reiniciá-lo.
    def format_document(value: object) -> str:
        digits = normalize_document(value)
        if len(digits) == 11:
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
        if len(digits) == 14:
            return (
                f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
            )
        return "Documento indisponível"


from qgis.PyQt.QtCore import QSettings, Qt
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

        self.status = QLabel(
            "Informe o CAR completo para iniciar. Os documentos serão exibidos integralmente."
        )
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
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(close)

        privacy = QLabel(
            "Privacidade: os CPF/CNPJ são exibidos integralmente para permitir a conferência do vínculo. "
            "A ferramenta não envia CAR ou CPF/CNPJ ao GitHub, não exporta esta consulta e não grava "
            "o documento pesquisado em log. Use os dados somente para finalidade autorizada."
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
            self,
            "Selecionar banco SQLite",
            self.database.text(),
            "SQLite (*.db *.sqlite);;Todos os arquivos (*)",
        )
        if selected:
            self.database.setText(selected)
            self.settings.setValue("database", selected)

    def _connection(self):
        path = self.database.text().strip()
        if not path:
            raise ValueError(
                "Selecione o banco car_microcredito.db antes de consultar."
            )
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
            QMessageBox.information(
                self, "CAR obrigatório", "Informe o número completo do CAR."
            )
            return
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
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.results))
        for row_index, result in enumerate(self.results):
            document = normalize_document(result.get("documento_normalizado"))
            values = {
                **result,
                "tipo_documento": "CPF"
                if len(document) == 11
                else "CNPJ"
                if len(document) == 14
                else "Indisponível",
                "documento": format_document(document),
                "tipo_vinculo": self.LINK_LABELS.get(
                    str(result.get("tipo_vinculo") or ""),
                    str(result.get("tipo_vinculo") or ""),
                ),
            }
            for column_index, (field, _) in enumerate(self.COLUMNS):
                item = QTableWidgetItem(str(values.get(field) or ""))
                item.setData(Qt.UserRole, row_index)
                self.table.setItem(row_index, column_index, item)
        self.table.setSortingEnabled(True)
        if self.results:
            self.table.selectRow(0)

    def closeEvent(self, event):
        self.results.clear()
        self.table.setRowCount(0)
        self.car.clear()
        self.status.setText(
            "Informe o CAR completo para iniciar. Os documentos serão exibidos integralmente."
        )
        super().closeEvent(event)
