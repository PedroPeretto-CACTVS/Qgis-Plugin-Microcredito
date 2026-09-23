from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsProject,
    QgsRendererCategory,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QSettings, Qt, QUrl, QVariant
from qgis.PyQt.QtGui import QColor, QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qgis_plugin_microcredito.domain.policy import (
    aggregate,
    compatible_operation,
    evaluate_lists,
    list_message,
    unique_operation,
)
from qgis_plugin_microcredito.application.pre_analysis import (
    PRE_ANALYSIS_LABELS,
    TECHNICAL_DECISIONS,
    build_pre_analysis,
)
from qgis_plugin_microcredito.domain.financing import (
    AUTOMATIC_RESOURCE_SOURCE,
    CREDIT_LINES,
    RESOURCE_SOURCES,
    resolve_resource_source,
    suggest_resource_source,
)

from .analysis import default_sources
from .car_source import (
    add_google_satellite,
    coordinates_from_google_maps_url,
    export_car_feature,
    find_car_feature,
    find_cars_by_point,
    normalize_car,
)
from .evidence import (
    collect_database_evidence,
    file_evidence,
    geometry_source_from_geojson,
)
from .map_output import MAP_PALETTE, MAP_STYLE_BY_CODE, render_analysis_map
from .report import write_report
from .worker import run_environment

SUPREME_MODE = (Path(__file__).parent / "supreme_mode.txt").is_file()

RESOURCE_SOURCE_OPTIONS = (
    ("Automática pela UF do CAR — sugestão", AUTOMATIC_RESOURCE_SOURCE),
    *((label, code) for code, label in RESOURCE_SOURCES),
)

CREDIT_LINE_OPTIONS = (
    ("Selecione a linha de crédito…", ""),
    *((line, line) for line in CREDIT_LINES),
)


def normalized_document_value(value: object) -> str:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return digits if len(digits) in (11, 14) else ""


def documents_for_mte(associated_documents, *additional_values) -> list[str]:
    documents = {
        normalized_document_value(item.get("documento_normalizado"))
        for item in associated_documents
    }
    documents.update(normalized_document_value(value) for value in additional_values)
    return sorted(value for value in documents if value)


def focused_extent(layer, destination_crs, context, margin: float = 1.35):
    """Retorna o limite do CAR no CRS do mapa, com uma pequena margem visual."""
    extent = layer.extent()
    if (
        layer.crs().isValid()
        and destination_crs.isValid()
        and layer.crs() != destination_crs
    ):
        extent = QgsCoordinateTransform(
            layer.crs(), destination_crs, context
        ).transformBoundingBox(extent)
    extent.scale(margin)
    return extent


from .core import _load_core


class CarMicrocreditoPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.batch_action = None
        self.update_action = None
        self.window = None
        self.batch_window = None
        self.update_window = None
        self.results = []

    def initGui(self):
        action_text = (
            "CAR Microcrédito — Consulta em massa"
            if SUPREME_MODE
            else "CAR Microcrédito"
        )
        icon = QIcon(str(Path(__file__).parent / "icon.svg"))
        self.action = QAction(icon, action_text, self.iface.mainWindow())
        self.action.triggered.connect(
            self.show_batch_window if SUPREME_MODE else self.show_window
        )
        self.iface.addPluginToMenu("CAR Microcrédito", self.action)
        self.iface.addToolBarIcon(self.action)
        self.update_action = QAction(
            icon, "Bases de consulta e atualizações", self.iface.mainWindow()
        )
        self.update_action.triggered.connect(self.show_update_window)
        self.iface.addPluginToMenu("CAR Microcrédito", self.update_action)
        if SUPREME_MODE:
            self.batch_action = QAction(
                icon, "Consulta individual", self.iface.mainWindow()
            )
            self.batch_action.triggered.connect(self.show_window)
            self.iface.addPluginToMenu("CAR Microcrédito", self.batch_action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu("CAR Microcrédito", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.batch_action:
            self.iface.removePluginMenu("CAR Microcrédito", self.batch_action)
        if self.update_action:
            self.iface.removePluginMenu("CAR Microcrédito", self.update_action)

    def show_window(self):
        if self.window is None:
            self.window = SearchWindow(self.iface, supreme_mode=SUPREME_MODE)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def show_batch_window(self):
        if self.batch_window is None:
            from .batch_window import BatchWindow

            self.batch_window = BatchWindow(self.iface, _load_core)
        self.batch_window.show()
        self.batch_window.raise_()
        self.batch_window.activateWindow()

    def show_update_window(self):
        if self.update_window is None:
            from .update_window import UpdateWindow

            self.update_window = UpdateWindow(self.iface)
        self.update_window.show()
        self.update_window.raise_()
        self.update_window.activateWindow()


class SearchWindow(QDialog):
    COLUMNS = (
        ("situacao_car", "Situação CAR"),
        ("car_original", "CAR"),
        ("sncr", "SNCR"),
        ("nirf_cib", "CIB/NIRF"),
        ("ref_bacen", "Ref. Bacen"),
        ("nu_ordem", "Ordem"),
        ("tipo_vinculo", "Vínculo"),
    )

    def __init__(self, iface, supreme_mode: bool = False):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.supreme_mode = supreme_mode
        self.batch_window = None
        self.car_document_window = None
        self.results = []
        self._busy_depth = 0
        self._owner_needed = False
        self.last_analysis = None
        self._technical_decision = None
        self._technical_decision_car = ""
        self.settings = QSettings("Cactvs", "CARMicrocredito")
        self.setWindowTitle("CAR Microcrédito | Apoio à decisão socioambiental")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "icon.svg")))
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setMinimumSize(600, 560)
        self.setStyleSheet("""
            QDialog { background: #f4f7f5; }
            QLabel#title { color: #165c41; font-size: 20px; font-weight: 700; }
            QLabel#subtitle { color: #5e6d67; font-size: 11px; }
            QGroupBox { background: white; border: 1px solid #ccd8d3; border-radius: 8px;
                        margin-top: 12px; padding: 12px 10px 10px 10px; font-weight: 600; color: #25483b; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QLineEdit { min-height: 30px; padding: 0 8px; border: 1px solid #aebdb7;
                        border-radius: 5px; background: white; }
            QLineEdit:focus { border: 2px solid #2b7a59; }
            QLineEdit[requiredMissing="true"] { border: 2px solid #c62828; background: #fff1f1; }
            QPushButton { min-height: 30px; padding: 0 14px; border: 1px solid #9aaba4;
                          border-radius: 5px; background: #ffffff; color: #243d34; font-weight: 600; }
            QPushButton:hover { background: #edf5f1; border-color: #2b7a59; }
            QPushButton#primary { background: #19734f; color: white; border-color: #165c41; }
            QPushButton#primary:hover { background: #135d40; }
            QPushButton#baseLocalToggle { min-height: 28px; padding: 0 10px; text-align: left;
                                          background: #e7f0ec; color: #25483b;
                                          border-color: #b8cbc3; font-weight: 700; }
            QPushButton#baseLocalToggle:hover { background: #dceae4; border-color: #2b7a59; }
            QTableWidget { background: white; border: 1px solid #ccd8d3; border-radius: 6px;
                           gridline-color: #e0e7e4; alternate-background-color: #f4f8f6; }
            QHeaderView::section { background: #e7f0ec; color: #25483b; padding: 7px;
                                   border: 0; border-right: 1px solid #ccd8d3; font-weight: 600; }
            QLabel#status { background: #edf5f1; color: #25483b; border-radius: 5px; padding: 8px; }
            QLabel#preAnalysisSummary { background: #edf5f1; color: #25483b; border-radius: 5px;
                                        border: 1px solid #79ae91; padding: 10px; }
            QLabel#status[statusLevel="ok"] { background: #e7f4ec; color: #145a3d; border: 1px solid #79ae91; }
            QLabel#status[statusLevel="review"] { background: #fff3d6; color: #7a4b00; border: 1px solid #d9ad58; }
            QLabel#status[statusLevel="neutral"] { background: #edf5f1; color: #25483b; border: 0; }
            QLabel#notice { color: #65736e; padding: 2px; }
        """)

        self.db_path = QLineEdit()
        saved_db = self.settings.value("database", "", type=str)
        self.db_path.setText(saved_db)
        self.db_path.setPlaceholderText("Selecione o arquivo car_microcredito.db")
        choose_db = QPushButton("Selecionar…")
        choose_db.clicked.connect(self.select_database)

        db_row = QHBoxLayout()
        db_row.addWidget(self.db_path, 1)
        db_row.addWidget(choose_db)

        self.car_base_path = QLineEdit()
        saved_car_base = self.settings.value("car_base", "", type=str)
        if not saved_car_base and saved_db:
            automatic_car_base = Path(saved_db).resolve().parent / "car"
            if automatic_car_base.is_dir():
                saved_car_base = str(automatic_car_base)
        self.car_base_path.setText(saved_car_base)
        self.car_base_path.setPlaceholderText(
            "Pasta com GeoPackage, SHP ou GeoJSON baixados do SICAR"
        )
        choose_car_base = QPushButton("Selecionar…")
        choose_car_base.clicked.connect(self.select_car_base)
        car_base_row = QHBoxLayout()
        car_base_row.addWidget(self.car_base_path, 1)
        car_base_row.addWidget(choose_car_base)

        self.document = QLineEdit()
        self.document.setPlaceholderText("CPF ou CNPJ")
        search = QPushButton("Buscar operações")
        search.setObjectName("primary")
        search.clicked.connect(self.search)
        self.document.returnPressed.connect(self.search)

        search_row = QHBoxLayout()
        search_row.addWidget(self.document, 1)
        search_row.addWidget(search)

        self.car = QLineEdit()
        self.car.setPlaceholderText("Número do CAR informado pelo cliente")
        search_mma = QPushButton("Buscar CAR e MMA/MCR")
        search_mma.clicked.connect(self.search_mma)
        self.car.returnPressed.connect(self.search_mma)
        self.car.textChanged.connect(self._update_resource_source_suggestion)
        car_row = QHBoxLayout()
        car_row.addWidget(self.car, 1)
        car_row.addWidget(search_mma)

        search_car_document = QPushButton("Procurar CPF/CNPJ no Sicor")
        search_car_document.setObjectName("carDocumentLookupButton")
        search_car_document.setToolTip(
            "Consultar documentos vinculados ao CAR no banco local; o vínculo não "
            "comprova titularidade"
        )
        search_car_document.clicked.connect(self.open_car_document_lookup)
        car_document_row = QHBoxLayout()
        car_document_row.addStretch(1)
        car_document_row.addWidget(search_car_document)

        self.owner_document = QLineEdit()
        self.owner_document.setPlaceholderText("CPF ou CNPJ do proprietário/possuidor")
        self.owner_document.textChanged.connect(self._owner_document_changed)

        self.fund = QComboBox()
        self.fund.setObjectName("constitutionalFund")
        for label, code in RESOURCE_SOURCE_OPTIONS:
            self.fund.addItem(label, code)
        self.fund.setToolTip(
            "A sugestão usa apenas a UF do CAR; confirme a fonte contratual."
        )
        self.program = QComboBox()
        self.program.setObjectName("financingProgram")
        for label, code in CREDIT_LINE_OPTIONS:
            self.program.addItem(label, code)

        self.latitude = QLineEdit()
        self.latitude.setPlaceholderText("Latitude, ex.: -11.83610")
        self.longitude = QLineEdit()
        self.longitude.setPlaceholderText("Longitude, ex.: -63.02009")
        search_point = QPushButton("Localizar CAR pelo ponto")
        search_point.clicked.connect(self.search_car_by_point)
        coordinate_row = QHBoxLayout()
        coordinate_row.addWidget(self.latitude)
        coordinate_row.addWidget(self.longitude)
        point_row = QVBoxLayout()
        point_row.setContentsMargins(0, 0, 0, 0)
        point_row.setSpacing(5)
        point_row.addLayout(coordinate_row)
        point_row.addWidget(search_point, 0, Qt.AlignRight)

        self.maps_url = QLineEdit()
        self.maps_url.setPlaceholderText(
            "Cole o link de compartilhamento do Google Maps"
        )
        extract_maps = QPushButton("Extrair coordenada")
        extract_maps.clicked.connect(self.extract_google_maps_point)
        maps_row = QHBoxLayout()
        maps_row.addWidget(self.maps_url, 1)
        maps_row.addWidget(extract_maps)

        self.mma_result = QLabel("Nenhum CAR consultado na lista do MMA.")
        self.mma_result.setObjectName("status")
        self.mma_result.setProperty("statusLevel", "neutral")
        self.mma_result.setWordWrap(True)
        self.mma_result.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.notice = QLabel(
            "O resultado mostra vínculos encontrados nas bases importadas. "
            "CAR não informado pelo Sicor exige consulta complementar."
        )
        self.notice.setObjectName("notice")
        self.notice.setWordWrap(True)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in self.COLUMNS])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setMinimumHeight(112)
        self.table.setToolTip(
            "Selecione uma linha para usar o CAR e a operação correspondentes"
        )
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.use_selected_car)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.Stretch)

        load_plots = QPushButton("Carregar no mapa")
        load_plots.setToolTip(
            "Carregar no mapa a geometria do CAR ou a gleba da operação selecionada"
        )
        load_plots.clicked.connect(self.load_selected_plots)
        analyze = QPushButton("Gerar relatório final")
        analyze.setToolTip("Executar a análise e salvar o PDF e o JSON definitivos")
        analyze.setObjectName("primary")
        analyze.clicked.connect(lambda: self.analyze_selected("final"))
        preview_interferences = QPushButton("Pré-análise das regras")
        preview_interferences.setObjectName("preAnalysisButton")
        preview_interferences.setToolTip(
            "Interpretar as fontes, conferir possíveis impedimentos e registrar a decisão técnica"
        )
        preview_interferences.clicked.connect(
            lambda: self.analyze_selected("pre_analysis")
        )
        preview_report = QPushButton("Prévia do relatório")
        preview_report.setToolTip("Gerar e abrir um PDF provisório")
        preview_report.clicked.connect(lambda: self.analyze_selected("report_preview"))
        clear = QPushButton("Limpar consulta")
        clear.clicked.connect(self.clear_query)
        preview_row = QHBoxLayout()
        preview_row.addStretch(1)
        preview_row.addWidget(preview_interferences)
        preview_row.addWidget(preview_report)
        action_row = QHBoxLayout()
        action_row.addWidget(clear)
        action_row.addStretch(1)
        action_row.addWidget(load_plots)
        action_row.addWidget(analyze)

        self.processing_label = QLabel("Pronto para consultar.")
        self.processing_label.setObjectName("notice")
        self.processing_bar = QProgressBar()
        self.processing_bar.setRange(0, 0)
        self.processing_bar.setTextVisible(False)
        self.processing_bar.setFixedHeight(8)
        self.processing_bar.hide()
        processing_row = QHBoxLayout()
        processing_row.addWidget(self.processing_label, 1)
        processing_row.addWidget(self.processing_bar, 2)
        self.interactive_controls = [
            choose_db,
            choose_car_base,
            search,
            search_mma,
            search_car_document,
            self.fund,
            self.program,
            search_point,
            extract_maps,
            clear,
            preview_interferences,
            preview_report,
            load_plots,
            analyze,
        ]

        title = QLabel("CAR Microcrédito")
        title.setObjectName("title")
        subtitle = QLabel(
            "Consulta bases, interpreta regras e organiza evidências para a decisão do técnico"
        )
        subtitle.setObjectName("subtitle")
        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addStretch(1)
        if self.supreme_mode:
            open_batch = QPushButton("Consulta em massa — subir Excel")
            open_batch.setObjectName("primary")
            open_batch.setToolTip("Abrir a consulta em lista da versão Usuário Supremo")
            open_batch.clicked.connect(self.open_batch_window)
            title_row.addWidget(open_batch)
            self.interactive_controls.append(open_batch)

        self.database_toggle = QPushButton()
        self.database_toggle.setObjectName("baseLocalToggle")
        self.database_toggle.setCheckable(True)
        self.database_panel = QGroupBox()
        self.database_panel.setObjectName("baseLocalPanel")
        database_layout = QFormLayout(self.database_panel)
        database_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        database_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        database_layout.addRow("Banco SQLite", db_row)
        database_layout.addRow("Polígonos do CAR", car_base_row)
        expanded = self.settings.value("base_local_expanded", False, type=bool)
        paths_valid = Path(saved_db).is_file() and Path(saved_car_base).is_dir()
        self.database_toggle.setChecked(expanded or not paths_valid)
        self._set_base_local_expanded(
            self.database_toggle.isChecked(), persist=False
        )
        self.database_toggle.toggled.connect(self._set_base_local_expanded)
        self.interactive_controls.append(self.database_toggle)

        query_group = QGroupBox("2. Identificar operação")
        query_layout = QFormLayout(query_group)
        query_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        query_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        query_layout.addRow("CPF ou CNPJ", search_row)
        query_layout.addRow("Número do CAR", car_row)
        query_layout.addRow("CPF/CNPJ vinculado", car_document_row)
        query_layout.addRow("Proprietário/possuidor", self.owner_document)
        query_layout.addRow("Fonte de recursos", self.fund)
        query_layout.addRow("Linha de crédito", self.program)
        query_layout.addRow("Coordenada WGS84", point_row)
        query_layout.addRow("Link do Google Maps", maps_row)
        query_layout.addRow("Retorno MMA/MCR", self.mma_result)

        results_group = QGroupBox("3. Operações encontradas")
        results_group.setMinimumHeight(190)
        results_layout = QVBoxLayout(results_group)
        self.notice.setMaximumHeight(48)
        results_layout.addWidget(self.notice)
        results_layout.addWidget(self.table, 1)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: #ccd8d3")
        top_content = QWidget()
        top_layout = QVBoxLayout(top_content)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        top_layout.addWidget(self.database_toggle)
        top_layout.addWidget(self.database_panel)
        top_layout.addWidget(query_group)
        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QFrame.NoFrame)
        top_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        top_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        top_scroll.setWidget(top_content)
        top_scroll.setMinimumHeight(175)

        self.content_splitter = QSplitter(Qt.Vertical)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(8)
        self.content_splitter.setToolTip(
            "Arraste a divisória para ajustar o espaço da lista de operações"
        )
        self.content_splitter.addWidget(top_scroll)
        self.content_splitter.addWidget(results_group)
        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(7)
        layout.addLayout(title_row)
        layout.addWidget(subtitle)
        layout.addWidget(self.content_splitter, 1)
        layout.addWidget(separator)
        layout.addLayout(processing_row)
        layout.addLayout(preview_row)
        layout.addLayout(action_row)

        saved_geometry = self.settings.value("window_geometry")
        if saved_geometry:
            self.restoreGeometry(saved_geometry)
        else:
            screen = self.screen().availableGeometry()
            self.resize(
                min(1120, int(screen.width() * 0.92)),
                min(760, int(screen.height() * 0.88)),
            )
        saved_splitter = self.settings.value("content_splitter")
        if saved_splitter:
            self.content_splitter.restoreState(saved_splitter)
        else:
            self.content_splitter.setSizes([390, 135])
        self._update_resource_source_suggestion()

    def open_batch_window(self):
        if self.batch_window is None:
            from .batch_window import BatchWindow

            self.batch_window = BatchWindow(self.iface, _load_core)
        self.batch_window.show()
        self.batch_window.raise_()
        self.batch_window.activateWindow()

    def _set_base_local_expanded(
        self, expanded: bool, persist: bool = True
    ) -> None:
        self.database_panel.setVisible(expanded)
        arrow = "▼" if expanded else "▶"
        action = "ocultar" if expanded else "mostrar"
        self.database_toggle.setText(f"{arrow} 1. Configuração da base local")
        self.database_toggle.setAccessibleName(
            f"Configuração da base local; {action} opções"
        )
        if persist:
            self.settings.setValue("base_local_expanded", expanded)

    def _update_resource_source_suggestion(self) -> None:
        index = self.fund.findData(AUTOMATIC_RESOURCE_SOURCE)
        if index < 0:
            return
        suggested = suggest_resource_source(self.car.text())
        label = (
            f"Automática pela UF do CAR — {suggested} sugerido"
            if suggested
            else "Automática pela UF do CAR — aguardando CAR"
        )
        self.fund.setItemText(index, label)

    def open_car_document_lookup(self) -> None:
        if not normalize_car(self.car.text()):
            QMessageBox.information(
                self,
                "CAR obrigatório",
                "Informe o número completo do CAR antes de procurar o CPF/CNPJ.",
            )
            self.car.setFocus()
            return
        if self.car_document_window is None:
            from .car_document_window import CarDocumentWindow

            self.car_document_window = CarDocumentWindow(self.iface, _load_core)
        self.car_document_window.database.setText(self.db_path.text())
        self.car_document_window.car.setText(self.car.text())
        self.car_document_window.show()
        self.car_document_window.raise_()
        self.car_document_window.activateWindow()
        self.car_document_window.search()

    def closeEvent(self, event):
        if self._busy_depth:
            event.ignore()
            return
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("content_splitter", self.content_splitter.saveState())
        super().closeEvent(event)

    def _begin_processing(self, message: str):
        if not self._busy_depth:
            self._input_controls = self.findChildren(QLineEdit) + [self.table]
            for control in self._input_controls:
                control.setEnabled(False)
        self._busy_depth += 1
        self.processing_label.setText(message)
        self.processing_bar.show()
        for control in self.interactive_controls:
            control.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()

    def _set_owner_required(self, required: bool):
        self._owner_needed = required
        raw = self.owner_document.text().strip()
        missing = (required and not self._normalized_owner_document()) or (
            bool(raw) and not self._normalized_owner_document()
        )
        self.owner_document.setProperty("requiredMissing", missing)
        self.owner_document.style().unpolish(self.owner_document)
        self.owner_document.style().polish(self.owner_document)
        self.owner_document.update()

    def _normalized_owner_document(self) -> str:
        return normalized_document_value(self.owner_document.text())

    def _owner_document_changed(self):
        raw = self.owner_document.text().strip()
        missing = (self._owner_needed and not self._normalized_owner_document()) or (
            bool(raw) and not self._normalized_owner_document()
        )
        self.owner_document.setProperty("requiredMissing", missing)
        self.owner_document.style().unpolish(self.owner_document)
        self.owner_document.style().polish(self.owner_document)

    def _processing_step(self, message: str):
        self.processing_label.setText(message)
        QApplication.processEvents()

    def _select_report_directory(self, chooser=None) -> Path | None:
        default_dir = self.settings.value(
            "report_output_dir",
            str(Path(self.db_path.text()).resolve().parent.parent / "output" / "pdf"),
            type=str,
        )
        chooser = chooser or QFileDialog.getExistingDirectory
        selected = chooser(
            self, "Escolher pasta para salvar o relatório final", default_dir
        )
        if not selected:
            return None
        destination = Path(selected)
        self.settings.setValue("report_output_dir", str(destination))
        return destination

    def _end_processing(self):
        self._busy_depth = max(0, self._busy_depth - 1)
        QApplication.restoreOverrideCursor()
        if self._busy_depth:
            return
        self.processing_bar.hide()
        self.processing_label.setText("Processamento concluído.")
        for control in self.interactive_controls:
            control.setEnabled(True)
        for control in getattr(self, "_input_controls", []):
            control.setEnabled(True)
        QApplication.processEvents()

    def select_database(self):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Selecionar banco", "", "SQLite (*.db *.sqlite)"
        )
        if selected:
            self.db_path.setText(selected)
            self.settings.setValue("database", selected)

    def select_car_base(self):
        selected = QFileDialog.getExistingDirectory(
            self, "Selecionar pasta das bases do CAR"
        )
        if selected:
            self.car_base_path.setText(selected)
            self.settings.setValue("car_base", selected)

    @staticmethod
    def _car_choices(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for source_index, candidate in enumerate(candidates):
            original = str(
                candidate.get("car_original")
                or candidate.get("car")
                or candidate.get("car_normalizado")
                or ""
            ).strip()
            normalized = normalize_car(original)
            if not normalized or original == "-1":
                continue
            choice = grouped.setdefault(
                normalized,
                {
                    "car": original,
                    "car_normalizado": normalized,
                    "referencias": [],
                    "ordens": [],
                    "detalhes": [],
                    "source_indices": [],
                },
            )
            choice["source_indices"].append(source_index)
            reference = str(candidate.get("ref_bacen") or "").strip()
            if not reference and candidate.get("arquivo"):
                reference = Path(str(candidate["arquivo"])).name
            order = str(candidate.get("nu_ordem") or candidate.get("fid") or "").strip()
            detail = str(candidate.get("tipo_vinculo") or "Polígono SICAR").strip()
            for field, value in (
                ("referencias", reference),
                ("ordens", order),
                ("detalhes", detail),
            ):
                if value and value not in choice[field]:
                    choice[field].append(value)
        return list(grouped.values())

    def _car_selection_dialog(
        self, choices: list[dict[str, object]], origin: str
    ) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("Selecionar CAR")
        dialog.setMinimumSize(680, 330)
        dialog.resize(900, 440)
        layout = QVBoxLayout(dialog)
        title = QLabel("Selecione o CAR desejado")
        title.setObjectName("title")
        layout.addWidget(title)
        instruction = QLabel(
            f"Foram encontrados {len(choices)} CAR distintos {origin}. "
            "Confira os dados e escolha qual será usado na análise."
        )
        instruction.setObjectName("notice")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        columns = (
            "CAR",
            "Referência Bacen / base",
            "Ordem / FID",
            "Vínculo",
            "Registros",
        )
        table = QTableWidget(len(choices), len(columns))
        table.setObjectName("carSelectionTable")
        table.setHorizontalHeaderLabels(columns)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for row, choice in enumerate(choices):
            values = (
                choice["car"],
                ", ".join(choice["referencias"]),
                ", ".join(choice["ordens"]),
                ", ".join(choice["detalhes"]),
                len(choice["source_indices"]),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, row)
                table.setItem(row, column, item)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        if choices:
            table.selectRow(0)
        layout.addWidget(table, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(dialog.reject)
        choose = QPushButton("Usar CAR selecionado")
        choose.setObjectName("primary")
        choose.clicked.connect(dialog.accept)
        actions.addWidget(cancel)
        actions.addWidget(choose)
        layout.addLayout(actions)
        table.doubleClicked.connect(dialog.accept)
        return dialog

    def _choose_car(self, candidates: list[dict[str, object]], origin: str):
        choices = self._car_choices(candidates)
        if not choices:
            return None
        if len(choices) == 1:
            return choices[0]
        dialog = self._car_selection_dialog(choices, origin)
        QApplication.setOverrideCursor(Qt.ArrowCursor)
        try:
            if dialog.exec() != QDialog.Accepted:
                return None
        finally:
            QApplication.restoreOverrideCursor()
        table = dialog.findChild(QTableWidget, "carSelectionTable")
        row = table.currentRow() if table else -1
        item = table.item(row, 0) if table and row >= 0 else None
        choice_index = item.data(Qt.UserRole) if item else None
        if choice_index is None or not 0 <= int(choice_index) < len(choices):
            return None
        return choices[int(choice_index)]

    def _apply_car_choice(self, choice: dict[str, object]):
        self.car.setText(str(choice["car"]))
        source_indices = choice.get("source_indices") or []
        if not source_indices:
            return
        wanted = int(source_indices[0])
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == wanted:
                self.table.setCurrentCell(row, 0)
                self.table.selectRow(row)
                break

    def search_car_by_point(self):
        self._begin_processing("Procurando o CAR que contém a coordenada…")
        try:
            latitude = float(self.latitude.text().strip().replace(",", "."))
            longitude = float(self.longitude.text().strip().replace(",", "."))
            directory = self.car_base_path.text().strip()
            if not directory and self.db_path.text().strip():
                directory = str(Path(self.db_path.text()).resolve().parent / "car")
                self.car_base_path.setText(directory)
            matches = find_cars_by_point(directory, latitude, longitude)
            if not matches:
                self.notice.setText(
                    "Nenhum polígono do SICAR instalado contém o ponto informado."
                )
                return
            choice = self._choose_car(matches, "sobrepostos nesse ponto")
            if choice is None:
                self.notice.setText(
                    f"{len(self._car_choices(matches))} CAR distintos contêm o ponto. "
                    "A seleção foi cancelada; nenhum CAR foi alterado."
                )
                return
            self._apply_car_choice(choice)
            self.notice.setText(
                f"CAR {choice['car']} selecionado entre {len(self._car_choices(matches))} imóvel(is) que contêm o ponto."
            )
            self.search_mma()
        except ValueError as exc:
            QMessageBox.information(self, "Coordenada inválida", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Falha ao localizar CAR", str(exc))
        finally:
            self._end_processing()

    def extract_google_maps_point(self):
        self._begin_processing("Extraindo a coordenada do link do Google Maps…")
        try:
            latitude, longitude = coordinates_from_google_maps_url(self.maps_url.text())
            self.latitude.setText(f"{latitude:.8f}")
            self.longitude.setText(f"{longitude:.8f}")
            self.search_car_by_point()
        except Exception as exc:
            QMessageBox.information(self, "Link do Google Maps", str(exc))
        finally:
            self._end_processing()

    def clear_query(self):
        self._clear_map_layers()
        for field in (
            self.document,
            self.car,
            self.owner_document,
            self.latitude,
            self.longitude,
            self.maps_url,
        ):
            field.clear()
        self.fund.setCurrentIndex(self.fund.findData(AUTOMATIC_RESOURCE_SOURCE))
        self.program.setCurrentIndex(0)
        self._set_owner_required(False)
        self.last_analysis = None
        self._technical_decision = None
        self._technical_decision_car = ""
        self.results = []
        self._fill_table()
        self._set_mma_status("Nenhum CAR consultado na lista do MMA.", "neutral")
        self.notice.setText(
            "Consulta limpa e camadas carregadas pelo plugin removidas do mapa."
        )
        self.document.setFocus()

    def _clear_map_layers(self):
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        groups = [
            node
            for node in list(root.children())
            if isinstance(node, QgsLayerTreeGroup)
            and node.name().startswith("CAR Microcrédito — ")
        ]
        for group in groups:
            layer_ids = [node.layerId() for node in group.findLayers()]
            if layer_ids:
                project.removeMapLayers(layer_ids)
            if group.parent():
                group.parent().removeChildNode(group)
        managed_basemaps = [
            layer.id()
            for layer in project.mapLayers().values()
            if layer.customProperty("car_microcredito/managed_basemap", False)
        ]
        if managed_basemaps:
            project.removeMapLayers(managed_basemaps)
        self.iface.mapCanvas().refresh()

    def _car_geometry(self, output_dir: Path):
        directory = self.car_base_path.text().strip()
        if not directory and self.db_path.text().strip():
            automatic = Path(self.db_path.text()).resolve().parent / "car"
            if automatic.is_dir():
                directory = str(automatic)
                self.car_base_path.setText(directory)
        if not directory or not self.car.text().strip():
            return None
        self.settings.setValue("car_base", directory)
        return export_car_feature(
            directory,
            self.car.text(),
            output_dir
            / f"car_{normalize_car(self.car.text())}_{uuid4().hex[:12]}.geojson",
        )

    def _connection(self):
        connect, initialize, _, _, _, _, _, _ = _load_core()
        database = self.db_path.text().strip()
        if not database:
            raise ValueError(
                "Selecione o banco car_microcredito.db antes de continuar."
            )
        if not Path(database).is_file():
            raise ValueError(
                "O banco selecionado não existe. Selecione o arquivo car_microcredito.db do projeto."
            )
        self.settings.setValue("database", database)
        connection = connect(database)
        initialize(connection)
        return connection

    def search(self):
        self._begin_processing("Consultando operações e vínculos no Sicor…")
        try:
            self.car.clear()
            self._set_mma_status(
                "Aguardando a seleção do CAR encontrado para consultar MMA/MCR.",
                "neutral",
            )
            _, _, find_by_document, _, _, _, _, _ = _load_core()
            connection = self._connection()
            try:
                self.results = find_by_document(connection, self.document.text())
            finally:
                connection.close()
            self._fill_table()
            choices = self._car_choices(self.results)
            if choices:
                choice = self._choose_car(self.results, "associados ao CPF/CNPJ")
                if choice:
                    self._apply_car_choice(choice)
                    self.notice.setText(
                        f"{len(self.results)} vínculo(s) e {len(choices)} CAR distinto(s) encontrado(s). "
                        f"CAR {choice['car']} selecionado; selecione outra linha da tabela para trocar."
                    )
                else:
                    self.notice.setText(
                        f"{len(self.results)} vínculo(s) e {len(choices)} CAR distinto(s) encontrado(s). "
                        "Selecione uma linha da tabela antes da análise."
                    )
            else:
                self.notice.setText(
                    f"{len(self.results)} vínculo(s) encontrado(s), sem número de CAR válido."
                )
        except Exception as exc:
            QMessageBox.critical(self, "Falha na consulta", str(exc))
        finally:
            self._end_processing()

    def search_mma(self):
        self._begin_processing("Consultando a publicação MMA/MCR…")
        try:
            _, _, _, _, find_mma, _, find_car, _ = _load_core()
            connection = self._connection()
            try:
                results = find_mma(connection, self.car.text())
                evidence = collect_database_evidence(connection)
                self.results = find_car(connection, self.car.text())
            finally:
                connection.close()
            self._fill_table()
            outcome = evaluate_lists(results, [], evidence, [])["mma_mcr"]
            self._set_mma_status(
                list_message(outcome, "MMA/MCR"),
                "ok" if outcome == "sem_ocorrencia_identificada" else "review",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Falha na consulta MMA/MCR", str(exc))
        finally:
            self._end_processing()

    def _set_mma_status(self, text: str, level: str = "neutral"):
        self.mma_result.setText(text)
        self.mma_result.setProperty("statusLevel", level)
        self.mma_result.style().unpolish(self.mma_result)
        self.mma_result.style().polish(self.mma_result)
        self.mma_result.update()

    def _local_car_context(self) -> dict[str, object]:
        directory = self.car_base_path.text().strip()
        if not directory and self.db_path.text().strip():
            automatic = Path(self.db_path.text()).resolve().parent / "car"
            if automatic.is_dir():
                directory = str(automatic)
        if not directory or not self.car.text().strip():
            return {}
        found = find_car_feature(directory, self.car.text())
        if not found:
            return {}
        layer, feature, _, _ = found
        fields = {field.name().lower(): field.name() for field in layer.fields()}

        def value(*candidates):
            field = next((fields[name] for name in candidates if name in fields), None)
            return feature[field] if field else None

        return {
            "area_ha": value("num_area", "area", "area_ha"),
            "modulos_fiscais": value("mod_fiscal", "modulos_fiscais"),
            "status": value("ind_status", "status", "status_imo"),
            "municipio": value("municipio", "nom_munici"),
        }

    def _fill_table(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.results))
        for row_index, result in enumerate(self.results):
            for column_index, (field, _) in enumerate(self.COLUMNS):
                value = result.get(field) or ""
                if field == "situacao_car":
                    value = {
                        "car_candidato": "CAR localizado",
                        "car_nao_informado_pelo_sicor": "CAR não informado",
                    }.get(str(value), value)
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, row_index)
                self.table.setItem(row_index, column_index, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()

    def _selected_result(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        source_index = item.data(Qt.UserRole) if item else None
        if source_index is None or not 0 <= int(source_index) < len(self.results):
            return None
        return self.results[int(source_index)]

    def use_selected_car(self):
        result = self._selected_result()
        if result and result.get("car_normalizado"):
            self.car.setText(
                str(result.get("car_original") or result["car_normalizado"])
            )
            self._set_mma_status(
                "CAR preenchido a partir da operação selecionada. Clique em Consultar lista MMA/MCR.",
                "neutral",
            )

    def load_selected_plots(self):
        result = self._selected_result()
        self._begin_processing("Localizando e carregando a geometria no mapa…")
        try:
            project_root = Path(self.db_path.text()).resolve().parent.parent
            car_geometry = self._car_geometry(project_root / "resultados")
            if car_geometry:
                self._load_map_context(car_geometry)
                return
            if result is None:
                QMessageBox.information(
                    self,
                    "Geometria indisponível",
                    "O CAR não foi localizado na base cadastral e nenhuma operação foi selecionada para reconstruir a gleba.",
                )
                return
            _, _, _, build_glebas_geojson, _, _, _, _ = _load_core()
            connection = self._connection()
            try:
                collection = build_glebas_geojson(
                    connection,
                    str(result["ref_bacen"]),
                    str(result.get("nu_ordem") or ""),
                )
            finally:
                connection.close()
            if not collection["features"]:
                QMessageBox.information(
                    self,
                    "Gleba indisponível",
                    "A operação selecionada não possui polígono válido na base importada.",
                )
                return
            output_dir = Path(self.db_path.text()).resolve().parent / "exportacoes"
            output_dir.mkdir(parents=True, exist_ok=True)
            output = (
                output_dir
                / f"glebas_{result['ref_bacen']}_{result.get('nu_ordem') or '0'}.geojson"
            )
            output.write_text(
                json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._load_map_context(output)
        except Exception as exc:
            QMessageBox.critical(self, "Falha ao carregar glebas", str(exc))
        finally:
            self._end_processing()

    def _load_map_context(self, target_path: str | Path, proximity_m: float = 5000.0):
        target = QgsVectorLayer(
            str(target_path), f"CAR analisado — {self.car.text().strip()}", "ogr"
        )
        if not target.isValid() or target.featureCount() == 0:
            raise ValueError("O QGIS não conseguiu abrir a geometria selecionada.")
        target.renderer().setSymbol(
            QgsFillSymbol.createSimple(
                {
                    "color": "255,214,0,55",
                    "outline_color": "20,24,31,255",
                    "outline_width": "1.8",
                }
            )
        )
        target.setCustomProperty("car_microcredito/managed", True)

        context = QgsProject.instance().transformContext()
        target_geometries = [
            feature.geometry()
            for feature in target.getFeatures()
            if feature.hasGeometry()
        ]
        target_union = QgsGeometry.unaryUnion(target_geometries)
        if target_union.isNull() or target_union.isEmpty():
            raise ValueError(
                "Não foi possível formar a geometria do CAR para buscar as camadas próximas."
            )
        metric_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        target_metric = QgsGeometry(target_union)
        target_metric.transform(
            QgsCoordinateTransform(target.crs(), metric_crs, context)
        )
        proximity_metric = target_metric.buffer(proximity_m, 24)

        project = QgsProject.instance()
        add_google_satellite()
        root = project.layerTreeRoot()
        group_name = f"CAR Microcrédito — {normalize_car(self.car.text())}"
        previous = root.findGroup(group_name)
        if previous:
            previous_ids = [node.layerId() for node in previous.findLayers()]
            if previous_ids:
                project.removeMapLayers(previous_ids)
            if previous.parent():
                previous.parent().removeChildNode(previous)
        group = root.insertGroup(0, group_name)

        total_nearby = total_intersections = loaded_layers = 0
        sources = default_sources(
            Path(self.db_path.text()).resolve().parent / "ambientais"
        )
        for index, source in enumerate(sources):
            source_layer = QgsVectorLayer(str(source.path), source.name, "ogr")
            if not source_layer.isValid():
                continue
            exact_in_source = QgsGeometry(target_union)
            exact_in_source.transform(
                QgsCoordinateTransform(target.crs(), source_layer.crs(), context)
            )
            proximity_in_source = QgsGeometry(proximity_metric)
            proximity_in_source.transform(
                QgsCoordinateTransform(metric_crs, source_layer.crs(), context)
            )

            geometry_name = QgsWkbTypes.displayString(source_layer.wkbType())
            memory = QgsVectorLayer(
                f"{geometry_name}?crs={source_layer.crs().authid()}",
                source.name,
                "memory",
            )
            provider = memory.dataProvider()
            provider.addAttributes(list(source_layer.fields()))
            relation_field = "cm_relacao"
            existing_names = {field.name().lower() for field in source_layer.fields()}
            while relation_field.lower() in existing_names:
                relation_field = "_" + relation_field
            provider.addAttributes([QgsField(relation_field, QVariant.String)])
            memory.updateFields()

            features = []
            intersections = nearby = 0
            request = QgsFeatureRequest().setFilterRect(
                proximity_in_source.boundingBox()
            )
            for feature in source_layer.getFeatures(request):
                if not feature.hasGeometry() or not feature.geometry().intersects(
                    proximity_in_source
                ):
                    continue
                relation = (
                    "INTERSEÇÃO"
                    if feature.geometry().intersects(exact_in_source)
                    else "PRÓXIMA (ATÉ 5 KM)"
                )
                intersections += relation == "INTERSEÇÃO"
                nearby += relation != "INTERSEÇÃO"
                copied = QgsFeature(memory.fields())
                copied.setGeometry(QgsGeometry(feature.geometry()))
                copied.setAttributes(feature.attributes() + [relation])
                features.append(copied)
            if not features:
                continue
            provider.addFeatures(features)
            memory.updateExtents()

            color_hex = MAP_STYLE_BY_CODE.get(
                source.code, MAP_PALETTE[index % len(MAP_PALETTE)]
            )[0]
            theme_color = QColor(color_hex)
            color = f"{theme_color.red()},{theme_color.green()},{theme_color.blue()}"
            nearby_symbol = QgsFillSymbol.createSimple(
                {
                    "color": f"{color},15",
                    "outline_color": f"{color},230",
                    "outline_width": "0.7",
                    "outline_style": "dash",
                }
            )
            intersection_symbol = QgsFillSymbol.createSimple(
                {
                    "color": f"{color},120",
                    "outline_color": f"{color},255",
                    "outline_width": "1.7",
                }
            )
            memory.setRenderer(
                QgsCategorizedSymbolRenderer(
                    relation_field,
                    [
                        QgsRendererCategory(
                            "INTERSEÇÃO", intersection_symbol, "INTERSEÇÃO COM O CAR"
                        ),
                        QgsRendererCategory(
                            "PRÓXIMA (ATÉ 5 KM)", nearby_symbol, "PRÓXIMA — ATÉ 5 KM"
                        ),
                    ],
                )
            )
            memory.setName(
                f"{source.name} — {intersections} interseção(ões), {nearby} próxima(s)"
            )
            memory.setCustomProperty("car_microcredito/fonte", source.source_url)
            memory.setCustomProperty("car_microcredito/raio_proximidade_m", proximity_m)
            memory.setCustomProperty("car_microcredito/managed", True)
            project.addMapLayer(memory, False)
            group.addLayer(memory)
            loaded_layers += 1
            total_intersections += intersections
            total_nearby += nearby

        project.addMapLayer(target, False)
        group.insertLayer(0, target)
        group.setExpanded(True)
        canvas = self.iface.mapCanvas()
        extent = focused_extent(target, canvas.mapSettings().destinationCrs(), context)
        canvas.setExtent(extent)
        canvas.refresh()
        self.notice.setText(
            f"CAR e {loaded_layers} camada(s) ambiental(is) próximas carregados sobre o Google Satellite: "
            f"{total_intersections} interferência(s) e {total_nearby} feição(ões) em até 5 km."
        )

    @staticmethod
    def _result_label(value: object) -> str:
        return {
            "ocorrencia_para_analise": "Ocorrência para análise",
            "sem_ocorrencia_identificada": "Sem ocorrência identificada",
            "inconclusivo": "Inconclusivo",
        }.get(str(value), str(value or "Não informado"))

    def _pre_analysis_dialog(self, analysis: dict[str, object]) -> QDialog:
        pre_analysis = analysis.get("pre_analise") or build_pre_analysis(analysis)
        analysis["pre_analise"] = pre_analysis
        dialog = QDialog(self)
        dialog.setWindowTitle("Pré-análise normativa para decisão técnica")
        dialog.setMinimumSize(820, 520)
        dialog.resize(1160, 700)

        layout = QVBoxLayout(dialog)
        title = QLabel("Pré-análise das regras para apoio à decisão")
        title.setObjectName("title")
        layout.addWidget(title)
        summary = QLabel(
            f"<b>{pre_analysis.get('classificacao_geral_rotulo')}</b><br>"
            f"{pre_analysis.get('resumo')}"
        )
        summary.setObjectName("preAnalysisSummary")
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(summary)

        explanation = QLabel(
            "A ferramenta interpreta cada fonte e aponta possíveis impedimentos, "
            "lacunas ou ausência de indício. Ela não decide a contratação."
        )
        explanation.setObjectName("notice")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        columns = (
            "Regra/fonte",
            "Conclusão preliminar",
            "Entendimento e fundamento",
            "Providência do técnico",
        )
        rules = list(pre_analysis.get("regras") or [])
        table = QTableWidget(len(rules), len(columns))
        table.setObjectName("preAnalysisTable")
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
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
                reference = str(item.get("referencia") or "")
                cell.setToolTip(
                    str(value or "")
                    + (f"\n\nReferência: {reference}" if reference else "")
                )
                table.setItem(row, column, cell)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        table.resizeRowsToContents()
        layout.addWidget(table, 1)

        decision_group = QGroupBox("Decisão do técnico responsável pela contratação")
        decision_form = QFormLayout(decision_group)
        decision = QComboBox()
        decision.setObjectName("technicalDecisionCombo")
        for code, label in TECHNICAL_DECISIONS:
            decision.addItem(label, code)
        justification = QPlainTextEdit()
        justification.setObjectName("technicalDecisionJustification")
        justification.setPlaceholderText(
            "Registre documentos, exceções, condicionantes e fundamento da decisão."
        )
        justification.setMaximumHeight(85)
        existing = analysis.get("decisao_tecnica") or {}
        existing_index = decision.findData(str(existing.get("codigo") or "pendente"))
        decision.setCurrentIndex(existing_index if existing_index >= 0 else 0)
        justification.setPlainText(str(existing.get("justificativa") or ""))
        decision_form.addRow("Conclusão", decision)
        decision_form.addRow("Justificativa", justification)
        layout.addWidget(decision_group)

        actions = QHBoxLayout()
        actions.addStretch(1)
        close = QPushButton("Fechar sem alterar")
        close.clicked.connect(dialog.reject)
        actions.addWidget(close)
        register = QPushButton("Registrar decisão técnica")
        register.setObjectName("primary")

        def register_decision() -> None:
            code = str(decision.currentData() or "pendente")
            text = justification.toPlainText().strip()
            if code != "pendente" and len(text) < 15:
                QMessageBox.information(
                    dialog,
                    "Justificativa necessária",
                    "Descreva o fundamento da decisão técnica com pelo menos 15 caracteres.",
                )
                return
            recorded = {
                "codigo": code,
                "rotulo": decision.currentText(),
                "justificativa": text,
                "registrada_em": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "pre_analise_sha256": pre_analysis.get("sha256"),
                "responsabilidade": (
                    "Decisão humana do técnico; não produzida automaticamente pela ferramenta."
                ),
            }
            self._technical_decision = recorded
            self._technical_decision_car = normalize_car(analysis.get("car"))
            analysis["decisao_tecnica"] = recorded
            self.last_analysis = analysis
            dialog.accept()

        register.clicked.connect(register_decision)
        actions.addWidget(register)
        layout.addLayout(actions)
        return dialog

    def _show_pre_analysis(self, analysis: dict[str, object]) -> None:
        self._pre_analysis_dialog(analysis).exec()

    def _interference_preview_dialog(self, analysis: dict[str, object]) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle("Prévia dos resultados de interferência")
        dialog.setMinimumSize(720, 400)
        dialog.resize(1020, 560)

        layout = QVBoxLayout(dialog)
        title = QLabel("Prévia dos resultados de interferência")
        title.setObjectName("title")
        layout.addWidget(title)

        overall = analysis.get("resultado_geral")
        summary = QLabel(f"Resultado geral: <b>{self._result_label(overall)}</b>")
        summary.setObjectName("status")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        explanation = QLabel(
            "Confira as interseções calculadas antes de gerar o relatório. "
            "Uma ocorrência indica necessidade de revisão documental e não define, isoladamente, a decisão de crédito."
        )
        explanation.setObjectName("notice")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        columns = (
            "Fonte",
            "Resultado",
            "Feições",
            "Área sobreposta (ha)",
            "Referência",
            "Observação",
        )
        layers = list(analysis.get("ambiental", {}).get("camadas", []))
        table = QTableWidget(len(layers), len(columns))
        table.setObjectName("interferencePreviewTable")
        table.setHorizontalHeaderLabels(columns)
        table.setAlternatingRowColors(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)

        backgrounds = {
            "ocorrencia_para_analise": QColor("#FDECEC"),
            "sem_ocorrencia_identificada": QColor("#EAF5EF"),
            "inconclusivo": QColor("#FFF5D6"),
        }
        for row, item in enumerate(layers):
            result_code = str(item.get("resultado") or "inconclusivo")
            observation = str(
                item.get("motivo")
                or item.get("orientacao_revisao")
                or "Base consultada sem interseção com o imóvel."
            )
            values = (
                item.get("fonte"),
                self._result_label(result_code),
                item.get("quantidade", 0),
                item.get("area_sobreposta_ha", 0),
                item.get("referencia_regulatoria"),
                observation,
            )
            background = backgrounds.get(result_code, QColor("#FFFFFF"))
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setBackground(background)
                cell.setToolTip(str(value or ""))
                if column in (2, 3):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row, column, cell)

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(len(columns) - 1, QHeaderView.Stretch)
        table.resizeRowsToContents()
        layout.addWidget(table, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close = QPushButton("Fechar")
        close.clicked.connect(dialog.accept)
        close_row.addWidget(close)
        layout.addLayout(close_row)
        return dialog

    def _show_interference_preview(self, analysis: dict[str, object]):
        self._interference_preview_dialog(analysis).exec()

    def analyze_selected(self, mode: str = "final"):
        result = self._selected_result()
        if not compatible_operation(result, self.car.text()):
            result = None
        if not self.car.text().strip():
            QMessageBox.information(
                self, "Informar CAR", "Informe o número do CAR para compor a análise."
            )
            return
        resource_source, resource_source_mode, resource_source_state = (
            resolve_resource_source(self.fund.currentData(), self.car.text())
        )
        if not resource_source:
            QMessageBox.information(
                self,
                "Fonte de recursos",
                "Não foi possível sugerir a fonte pela UF do CAR. Escolha FCO, "
                "FNO ou OGU manualmente.",
            )
            self.fund.setFocus()
            return
        selected_report_dir = None
        if mode == "final":
            selected_report_dir = self._select_report_directory()
            if selected_report_dir is None:
                return
        self._begin_processing("Preparando os dados da análise…")
        try:
            (
                _,
                _,
                _,
                build_glebas_geojson,
                find_mma_mcr_by_car,
                find_documents_by_car,
                find_by_car,
                find_slave_labor_by_documents,
            ) = _load_core()
            connection = self._connection()
            try:
                self._processing_step(
                    "Consultando operações, CPF/CNPJ e listas regulatórias…"
                )
                operations = find_by_car(connection, self.car.text())
                if result is None and len(operations) == 1:
                    result = operations[0]
                collection = {"type": "FeatureCollection", "features": []}
                mma = find_mma_mcr_by_car(connection, self.car.text())
                associated_documents = find_documents_by_car(
                    connection, self.car.text()
                )
                manual_raw = self.owner_document.text().strip()
                manual_document = self._normalized_owner_document()
                if manual_raw and not manual_document:
                    self._set_owner_required(True)
                    QMessageBox.information(
                        self,
                        "CPF/CNPJ inválido",
                        "Informe 11 dígitos para CPF ou 14 dígitos para CNPJ do proprietário/possuidor.",
                    )
                    return
                if manual_document and not any(
                    item.get("documento_normalizado") == manual_document
                    for item in associated_documents
                ):
                    associated_documents.append(
                        {
                            "car_original": self.car.text().strip(),
                            "ref_bacen": "",
                            "nu_ordem": "",
                            "documento_original": manual_raw,
                            "documento_normalizado": manual_document,
                            "documento_mascarado": 0,
                            "tipo_vinculo": "proprietario_possuidor_informado_manualmente",
                            "base_origem": "INFORMACAO_DO_USUARIO",
                            "arquivo": "",
                            "importado_em": "",
                        }
                    )
                if not associated_documents:
                    self._set_owner_required(True)
                    QMessageBox.information(
                        self,
                        "Proprietário/possuidor necessário",
                        "O CAR não retornou CPF/CNPJ no Sicor. Preencha o campo vermelho para realizar a consulta no cadastro do MTE.",
                    )
                    return
                self._set_owner_required(False)
                consulted_mte_documents = documents_for_mte(
                    associated_documents,
                    self.document.text(),
                    self.owner_document.text(),
                )
                slave_labor = find_slave_labor_by_documents(
                    connection,
                    consulted_mte_documents,
                )
                database_evidence = collect_database_evidence(connection)
            finally:
                connection.close()
            result = result or {
                "ref_bacen": "",
                "nu_ordem": "",
                "estado": "",
                "municipio_ibge": "",
            }
            project_root = Path(self.db_path.text()).resolve().parent.parent
            geo_dir = project_root / "resultados"
            geo_dir.mkdir(parents=True, exist_ok=True)
            safe_key = normalize_car(self.car.text()) + "_" + uuid4().hex[:12]
            target_path = geo_dir / f"gleba_car_{safe_key}.geojson"
            car_geometry = self._car_geometry(geo_dir)
            if car_geometry:
                target_path = car_geometry
                geometry_origin = "poligono_cadastral_sicar"
                geometry_source = geometry_source_from_geojson(target_path)
            else:
                selected = (
                    result
                    if compatible_operation(result, self.car.text())
                    else unique_operation(operations, self.car.text())
                )
                if selected:
                    result = selected
                    connection = self._connection()
                    try:
                        collection = build_glebas_geojson(
                            connection,
                            str(result["ref_bacen"]),
                            str(result.get("nu_ordem") or ""),
                        )
                    finally:
                        connection.close()
                if not collection["features"]:
                    QMessageBox.information(
                        self,
                        "Análise inconclusiva",
                        "Não foi localizado polígono na base cadastral do CAR nem gleba válida para esta operação.",
                    )
                    return
                target_path.write_text(
                    json.dumps(collection, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                geometry_origin = "gleba_operacao_sicor"
                geometry_source = str(result.get("arquivo") or "")
            self._processing_step(
                "Cruzando o imóvel com as bases socioambientais nacionais…"
            )
            environmental = run_environment(
                target_path,
                default_sources(
                    Path(self.db_path.text()).resolve().parent / "ambientais"
                ),
            )
            self._processing_step(
                "Cruzamentos territoriais concluídos. Preparando o mapa…"
            )
            source_results = evaluate_lists(
                mma, slave_labor, database_evidence, associated_documents
            )
            overall = aggregate(
                [environmental["resultado_geral"], *source_results.values()]
            )
            analysis = {
                "resultado_geral": overall,
                "resultado_fontes": source_results,
                "car": self.car.text().strip(),
                "operacao": result,
                "mma_mcr": mma,
                "documentos_associados": associated_documents,
                "trabalho_escravo": slave_labor,
                "ambiental": environmental,
                "geometria_empreendimento": str(target_path),
                "origem_geometria": geometry_origin,
                "fonte_geometria": geometry_source,
                "evidencia_geometria": file_evidence(target_path),
                "documentos_consultados_mte": consulted_mte_documents,
                "fundo_constitucional": resource_source,
                "fonte_recursos_modo": resource_source_mode,
                "fonte_recursos_uf": resource_source_state,
                "programa_financiamento": str(self.program.currentData() or ""),
                **database_evidence,
            }
            analysis["pre_analise"] = build_pre_analysis(analysis)
            if (
                self._technical_decision
                and self._technical_decision_car == normalize_car(analysis.get("car"))
                and self._technical_decision.get("pre_analise_sha256")
                == analysis["pre_analise"].get("sha256")
            ):
                analysis["decisao_tecnica"] = dict(self._technical_decision)
            elif self._technical_decision_car == normalize_car(analysis.get("car")):
                self._technical_decision = None
                self._technical_decision_car = ""
            self.last_analysis = analysis
            if mode in {"interferences", "pre_analysis"}:
                self._processing_step("Abrindo a pré-análise normativa…")
                self._show_pre_analysis(analysis)
                return
            report_dir = selected_report_dir or (project_root / "output" / "pdf")
            report_dir.mkdir(parents=True, exist_ok=True)
            preview_prefix = "previa_" if mode == "report_preview" else ""
            map_legend = []
            map_path = render_analysis_map(
                target_path,
                default_sources(
                    Path(self.db_path.text()).resolve().parent / "ambientais"
                ),
                report_dir / f"{preview_prefix}mapa_car_{safe_key}.png",
                legend_entries=map_legend,
            )
            if map_path:
                analysis["mapa_path"] = str(map_path)
                analysis["mapa_legenda"] = map_legend
            self._processing_step("Gerando o relatório PDF e o arquivo de auditoria…")
            report_name = (
                "previa_relatorio_car" if mode == "report_preview" else "analise_car"
            )
            report_path = report_dir / f"{report_name}_{safe_key}.pdf"
            pdf_path, json_path = write_report(analysis, report_path)
            if mode == "report_preview":
                self._processing_step("Abrindo a prévia do relatório…")
                opened = QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(pdf_path.resolve()))
                )
                if not opened:
                    QMessageBox.information(
                        self,
                        "Prévia criada",
                        f"A prévia foi criada, mas o visualizador de PDF não abriu automaticamente.\n\nPDF: {pdf_path}",
                    )
                return
            QMessageBox.information(
                self,
                "Relatório criado",
                f"Pré-análise: {analysis['pre_analise']['classificacao_geral_rotulo']}\n"
                f"Decisão técnica: "
                f"{(analysis.get('decisao_tecnica') or {}).get('rotulo', 'Pendente')}"
                f"\n\nPDF: {pdf_path}\nJSON: {json_path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Falha na análise", str(exc))
        finally:
            self._end_processing()
