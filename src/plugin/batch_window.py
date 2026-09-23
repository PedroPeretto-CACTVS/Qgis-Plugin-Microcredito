from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from qgis.PyQt.QtCore import QSettings, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from qgis_plugin_microcredito.application.hashing import file_sha256
from qgis_plugin_microcredito.application.pre_analysis import build_pre_analysis
from qgis_plugin_microcredito.domain.financing import (
    AUTOMATIC_RESOURCE_SOURCE,
    resolve_resource_source,
)
from qgis_plugin_microcredito.domain.policy import (
    aggregate,
    evaluate_lists,
    unique_operation,
)

from .analysis import default_sources
from .batch import BatchRow, read_batch_xlsx
from .car_source import export_car_feature, normalize_car
from .evidence import (
    collect_database_evidence,
    file_evidence,
    geometry_source_from_geojson,
)
from .map_output import render_analysis_map
from .report import write_batch_report
from .worker import EnvironmentalWorker


class BatchWindow(QDialog):
    def __init__(self, iface, core_loader):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.core_loader = core_loader
        self.settings = QSettings("Cactvs", "CARMicrocredito")
        self.rows: list[BatchRow] = []
        self.tasks: list[dict[str, object]] = []
        self.cancel_requested = False
        self.setWindowTitle("CAR Microcrédito | Usuário Supremo - consulta em lista")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "icon.svg")))
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setMinimumSize(680, 480)
        self.resize(1050, 680)
        self.setStyleSheet("""
            QDialog { background: #f4f7f5; }
            QLabel#title { color: #165c41; font-size: 20px; font-weight: 700; }
            QLabel#subtitle { color: #5e6d67; font-size: 11px; }
            QLabel#status { background: #edf5f1; color: #25483b; border-radius: 5px; padding: 8px; }
            QGroupBox { background: white; border: 1px solid #ccd8d3; border-radius: 8px; margin-top: 12px; padding: 12px 10px 10px 10px; font-weight: 600; color: #25483b; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QLineEdit { min-height: 30px; padding: 0 8px; border: 1px solid #aebdb7; border-radius: 5px; background: white; }
            QPushButton { min-height: 30px; padding: 0 14px; border: 1px solid #9aaba4; border-radius: 5px; background: white; color: #243d34; font-weight: 600; }
            QPushButton#primary { background: #19734f; color: white; border-color: #165c41; }
            QTableWidget { background: white; border: 1px solid #ccd8d3; gridline-color: #e0e7e4; }
            QHeaderView::section { background: #e7f0ec; color: #25483b; padding: 7px; border: 0; border-right: 1px solid #ccd8d3; font-weight: 600; }
        """)

        self.db_path = QLineEdit(self.settings.value("database", "", type=str))
        self.car_base_path = QLineEdit(self.settings.value("car_base", "", type=str))
        self.xlsx_path = QLineEdit()
        self.output_path = QLineEdit()
        saved_db = self.db_path.text().strip()
        saved_output = self.settings.value(
            "batch_report_output_dir", "", type=str
        ).strip()
        if not self.car_base_path.text().strip() and saved_db:
            self.car_base_path.setText(str(Path(saved_db).resolve().parent / "car"))
        if saved_output:
            self.output_path.setText(saved_output)
        elif saved_db:
            self.output_path.setText(
                str(Path(saved_db).resolve().parent.parent / "output" / "lotes")
            )

        choose_db = QPushButton("Selecionar…")
        choose_db.clicked.connect(
            lambda: self._choose_file(
                self.db_path, "Banco SQLite (*.db *.sqlite *.sqlite3)"
            )
        )
        choose_car = QPushButton("Selecionar…")
        choose_car.clicked.connect(lambda: self._choose_directory(self.car_base_path))
        choose_xlsx = QPushButton("Selecionar planilha…")
        choose_xlsx.clicked.connect(
            lambda: self._choose_file(self.xlsx_path, "Planilha Excel (*.xlsx)")
        )
        choose_output = QPushButton("Escolher pasta…")
        choose_output.clicked.connect(self._choose_output_directory)

        title = QLabel("Consulta em lista — Usuário Supremo")
        title.setObjectName("title")
        subtitle = QLabel(
            "Valide a planilha, processe todos os CARs e gere um único PDF agrupado por CPF/CNPJ"
        )
        subtitle.setObjectName("subtitle")

        paths = QGroupBox("1. Arquivos")
        form = QFormLayout(paths)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.addRow("Banco SQLite", self._row(self.db_path, choose_db))
        form.addRow("Polígonos do CAR", self._row(self.car_base_path, choose_car))
        form.addRow("Planilha de consultas", self._row(self.xlsx_path, choose_xlsx))
        form.addRow("Pasta dos relatórios", self._row(self.output_path, choose_output))

        self.include_maps = QCheckBox(
            "Incluir mapa de satélite em cada CAR (mais lento)"
        )
        self.include_maps.setChecked(True)
        template = QPushButton("Salvar modelo Excel…")
        template.clicked.connect(self.save_template)
        validate = QPushButton("Validar planilha")
        validate.clicked.connect(self.validate_spreadsheet)
        options = QHBoxLayout()
        options.addWidget(self.include_maps)
        options.addStretch(1)
        options.addWidget(template)
        options.addWidget(validate)

        self.status = QLabel(
            "Selecione o modelo preenchido e valide antes de processar."
        )
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            (
                "Linha",
                "CPF/CNPJ",
                "CAR",
                "Fonte",
                "Linha de crédito",
                "Status",
                "Pré-análise ou mensagem",
            )
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for index in range(6):
            header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.Stretch)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.cancel = QPushButton("Cancelar processamento")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self._request_cancel)
        self.clear_button = QPushButton("Limpar consulta")
        self.clear_button.clicked.connect(self._clear_query)
        choose_final_output = QPushButton("Escolher pasta do relatório…")
        choose_final_output.clicked.connect(self._choose_output_directory)
        process = QPushButton("Processar lote e gerar PDF")
        process.setObjectName("primary")
        process.clicked.connect(self.process_batch)
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addWidget(close)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.cancel)
        actions.addStretch(1)
        actions.addWidget(choose_final_output)
        actions.addWidget(process)
        self.process_button = process

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(paths)
        layout.addLayout(options)
        layout.addWidget(self.status)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.progress)
        layout.addLayout(actions)

    @staticmethod
    def _row(field, button):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field, 1)
        layout.addWidget(button)
        return layout

    def _choose_file(self, field, file_filter):
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar arquivo", field.text(), file_filter
        )
        if path:
            field.setText(path)

    def _choose_directory(self, field):
        path = QFileDialog.getExistingDirectory(self, "Selecionar pasta", field.text())
        if path:
            field.setText(path)

    def _choose_output_directory(self):
        initial = self.output_path.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(
            self, "Escolher pasta dos relatórios", initial
        )
        if path:
            self.output_path.setText(path)
            self.settings.setValue("batch_report_output_dir", path)
            self.settings.sync()

    def _choose_final_output(self, current: Path) -> Path:
        selected = QFileDialog.getExistingDirectory(
            self, "Escolher onde salvar o relatório", str(current)
        )
        if not selected:
            return current
        output = self._prepare_output_directory(Path(selected))
        self.output_path.setText(str(output))
        self.settings.setValue("batch_report_output_dir", str(output))
        self.settings.sync()
        return output

    def _clear_query(self):
        if getattr(self, "processing", False):
            return
        self.xlsx_path.clear()
        self.rows = []
        self.tasks = []
        self.table.setRowCount(0)
        self.progress.setValue(0)
        self.cancel_requested = False
        if hasattr(self, "spreadsheet_sha256"):
            del self.spreadsheet_sha256
        self.status.setText(
            "Consulta limpa. Selecione outra planilha e valide antes de processar."
        )

    def save_template(self):
        source = Path(__file__).parent / "modelo_consulta_lote.xlsx"
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar modelo",
            "modelo_consulta_lote.xlsx",
            "Planilha Excel (*.xlsx)",
        )
        if destination:
            shutil.copy2(source, destination)
            QMessageBox.information(
                self,
                "Modelo salvo",
                f"Preencha a aba Consultas e mantenha os nomes das colunas.\n\n{destination}",
            )

    def _set_cell(self, row: int, column: int, value: object):
        self.table.setItem(row, column, QTableWidgetItem(str(value or "")))

    def validate_spreadsheet(self):
        try:
            spreadsheet = Path(self.xlsx_path.text().strip())
            before = file_sha256(spreadsheet)
            self.rows = read_batch_xlsx(spreadsheet)
            if before != file_sha256(spreadsheet):
                raise ValueError(
                    "Planilha alterada durante a leitura. Valide novamente."
                )
            self.spreadsheet_sha256 = before
            self.tasks = []
            self.table.setRowCount(len(self.rows))
            for index, row in enumerate(self.rows):
                self._set_cell(index, 0, row.source_row)
                self._set_cell(index, 1, row.document)
                self._set_cell(index, 2, row.car or "Localizar pelo CPF/CNPJ")
                self._set_cell(index, 3, row.resource_source)
                self._set_cell(index, 4, row.credit_line)
                self._set_cell(index, 5, "Válido")
                self._set_cell(index, 6, "Aguardando processamento")
            self.status.setText(
                f"Planilha válida: {len(self.rows)} linha(s). Linhas sem CAR serão expandidas pelos vínculos do Sicor."
            )
            return True
        except Exception as exc:
            self.rows = []
            self.table.setRowCount(0)
            QMessageBox.critical(self, "Planilha inválida", str(exc))
            return False

    def _request_cancel(self):
        self.cancel_requested = True
        worker = getattr(self, "active_worker", None)
        if worker is not None:
            worker.cancel_current()
        self.cancel.setEnabled(False)
        self.status.setText(
            "Cancelando o processamento atual e registrando os itens restantes…"
        )

    def _record_cancelled_tasks(
        self, start: int, failures: list[dict[str, object]]
    ) -> None:
        for table_row, pending in enumerate(self.tasks[start:], start):
            row: BatchRow = pending["row"]
            message = "Não processado por cancelamento do lote."
            failures.append(
                {
                    "linha": row.source_row,
                    "documento": row.document,
                    "car": pending["car"],
                    "estado": "cancelado",
                    "erro": message,
                }
            )
            for column, value in enumerate(
                (
                    row.source_row,
                    row.document,
                    pending["car"],
                    row.resource_source,
                    row.credit_line,
                    "Cancelado",
                    message,
                )
            ):
                self._set_cell(table_row, column, value)

    @staticmethod
    def _prepare_output_directory(output: Path) -> Path:
        try:
            output.mkdir(parents=True, exist_ok=True)
            probe = output / ("teste_gravacao_" + uuid4().hex[:12])
            probe.mkdir()
            (probe / "ok.txt").write_text("ok", encoding="utf-8")
        except OSError as exc:
            raise PermissionError(
                "Não foi possível gravar na pasta escolhida para os relatórios. "
                "Escolha outra pasta em ‘Pasta dos relatórios’ e tente novamente. "
                f"Detalhe do Windows: {exc}"
            ) from exc
        finally:
            if "probe" in locals():
                shutil.rmtree(probe, ignore_errors=True)
        return output

    def _prepare_work_directory(self) -> Path:
        configured = os.environ.get("CAR_MICROCREDITO_TEMP_DIR", "").strip()
        root = (
            Path(configured)
            if configured
            else Path(os.environ.get("LOCALAPPDATA") or self.output_path.text())
            / "Cactvs"
            / "CAR_Microcredito"
            / "temporarios"
        )
        work = root / "lotes" / self.run_id
        try:
            work.mkdir(parents=True)
        except OSError as exc:
            raise PermissionError(
                "O Windows bloqueou a pasta temporária usada durante a consulta. "
                f"Detalhe: {exc}"
            ) from exc
        return work

    def _paths(self):
        database = Path(self.db_path.text().strip())
        car_base = Path(self.car_base_path.text().strip())
        output_text = self.output_path.text().strip()
        if not database.is_file():
            raise ValueError("Selecione um banco SQLite existente.")
        if not car_base.is_dir():
            raise ValueError("Selecione a pasta nacional com os polígonos do CAR.")
        if not output_text:
            raise ValueError("Escolha a pasta em que os relatórios serão gravados.")
        output = self._prepare_output_directory(Path(output_text).expanduser())
        self.settings.setValue("database", str(database))
        self.settings.setValue("car_base", str(car_base))
        self.settings.setValue("batch_report_output_dir", str(output))
        self.settings.sync()
        return database, car_base, output

    def _expand_tasks(self, connection, find_by_document):
        tasks = []
        seen = set()
        failures = []
        for row in self.rows:
            cars = (
                [row.car]
                if row.car.strip()
                else [
                    str(item.get("car_original") or item.get("car_normalizado") or "")
                    for item in find_by_document(connection, row.document)
                ]
            )
            unique = {}
            for car in cars:
                normalized = normalize_car(car)
                if normalized:
                    unique[normalized] = car
            if not unique:
                failures.append(
                    {
                        "linha": row.source_row,
                        "documento": row.document,
                        "car": row.car,
                        "erro": "Nenhum CAR válido localizado para o CPF/CNPJ.",
                    }
                )
                continue
            for normalized, car in unique.items():
                key = (row.document, normalized)
                if key in seen:
                    failures.append(
                        {
                            "linha": row.source_row,
                            "documento": row.document,
                            "car": car,
                            "estado": "duplicado",
                            "erro": "Consulta duplicada; considerada a primeira linha.",
                        }
                    )
                    continue
                seen.add(key)
                tasks.append({"row": row, "car": car, "car_normalizado": normalized})
        return tasks, failures

    def _build_analysis(
        self, connection, task, database, car_base, output, analyzer, functions
    ):
        (
            _,
            _,
            _,
            build_glebas_geojson,
            find_mma,
            find_documents,
            find_by_car,
            find_slave,
        ) = functions
        row: BatchRow = task["row"]
        car = str(task["car"])
        operations = find_by_car(connection, car)
        operation = {"ref_bacen": "", "nu_ordem": "", "estado": car[:2]}
        collection = {"type": "FeatureCollection", "features": []}
        documents = find_documents(connection, car)
        supplied = [row.document, row.owner_document]
        for document in supplied:
            if document and not any(
                item.get("documento_normalizado") == document for item in documents
            ):
                documents.append(
                    {
                        "car_original": car,
                        "ref_bacen": "",
                        "nu_ordem": "",
                        "documento_original": document,
                        "documento_normalizado": document,
                        "documento_mascarado": 0,
                        "tipo_vinculo": "documento_informado_na_planilha",
                        "base_origem": "PLANILHA_USUARIO_SUPREMO",
                        "arquivo": self.xlsx_path.text(),
                        "importado_em": "",
                    }
                )
        labor = find_slave(
            connection,
            [str(item.get("documento_normalizado") or "") for item in documents],
        )
        mma = find_mma(connection, car)
        database_evidence = self.database_evidence

        safe_car = task["car_normalizado"]
        work = self.work_directory
        target = export_car_feature(car_base, car, work / f"car_{safe_car}.geojson")
        if target:
            origin = "poligono_cadastral_sicar"
            geometry_source = geometry_source_from_geojson(target)
        else:
            operation = unique_operation(operations, car)
            if operation:
                collection = build_glebas_geojson(
                    connection,
                    str(operation["ref_bacen"]),
                    str(operation.get("nu_ordem") or ""),
                )
            if not collection.get("features"):
                raise ValueError(
                    "Polígono não localizado no SICAR nem em gleba comprovadamente associada."
                )
            target = work / f"gleba_car_{safe_car}.geojson"
            target.write_text(
                json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            origin = "gleba_operacao_sicor"
            geometry_source = str(operation.get("arquivo") or "")

        environmental = analyzer.analyze(target)
        source_results = evaluate_lists(mma, labor, database_evidence, documents)
        overall = aggregate(
            [environmental["resultado_geral"], *source_results.values()]
        )
        resource_source, source_mode, source_state = resolve_resource_source(
            row.resource_source, car
        )
        analysis = {
            "resultado_geral": overall,
            "resultado_fontes": source_results,
            "car": car,
            "operacao": operation,
            "mma_mcr": mma,
            "documentos_associados": documents,
            "trabalho_escravo": labor,
            "ambiental": environmental,
            "geometria_empreendimento": str(target),
            "origem_geometria": origin,
            "fonte_geometria": geometry_source,
            "evidencia_geometria": file_evidence(target),
            "documentos_consultados_mte": sorted(
                {
                    str(item.get("documento_normalizado") or "")
                    for item in documents
                    if item.get("documento_normalizado")
                }
            ),
            "fundo_constitucional": resource_source,
            "fonte_recursos_modo": source_mode,
            "fonte_recursos_uf": source_state,
            "programa_financiamento": row.credit_line,
            **database_evidence,
            "planilha_sha256": self.spreadsheet_sha256,
            "documento_lote": row.document,
            "linha_planilha": row.source_row,
            "referencia_interna": row.internal_reference,
            "observacao_planilha": row.observation,
        }
        analysis["pre_analise"] = build_pre_analysis(analysis)
        if self.include_maps.isChecked():
            map_legend = []
            map_path = render_analysis_map(
                target,
                analyzer.sources,
                work / f"mapa_{row.document}_{safe_car}.png",
                legend_entries=map_legend,
            )
            if map_path:
                analysis["mapa_path"] = str(map_path)
                analysis["mapa_legenda"] = map_legend
        return analysis

    def process_batch(self):
        if not self.validate_spreadsheet():
            return
        self.cancel_requested = False
        self.processing = True
        self.run_id = uuid4().hex
        self.locked_controls = (
            self.findChildren(QPushButton)
            + self.findChildren(QLineEdit)
            + self.findChildren(QCheckBox)
        )
        for control in self.locked_controls:
            control.setEnabled(False)
        self.cancel.setEnabled(True)
        self.process_button.setEnabled(False)
        analyses = []
        try:
            database, car_base, output = self._paths()
            self.work_directory = self._prepare_work_directory()
            functions = self.core_loader()
            connect, initialize, find_by_document, *_ = functions
            connection = connect(database)
            try:
                self.database_evidence = collect_database_evidence(connection)
                self.tasks, failures = self._expand_tasks(connection, find_by_document)
                self.table.setRowCount(len(self.tasks))
                sources = default_sources(database.parent / "ambientais")
                analyzer = EnvironmentalWorker(sources)
                self.active_worker = analyzer
                total = len(self.tasks)
                for index, task in enumerate(self.tasks):
                    if self.cancel_requested:
                        self._record_cancelled_tasks(index, failures)
                        break
                    row: BatchRow = task["row"]
                    resolved_source, _, _ = resolve_resource_source(
                        row.resource_source, task["car"]
                    )
                    displayed_source = (
                        f"AUTO → {resolved_source}"
                        if row.resource_source == AUTOMATIC_RESOURCE_SOURCE
                        else row.resource_source
                    )
                    for column, value in enumerate(
                        (
                            row.source_row,
                            row.document,
                            task["car"],
                            displayed_source,
                            row.credit_line,
                            "Processando",
                            "Consultando bases…",
                        )
                    ):
                        self._set_cell(index, column, value)
                    self.status.setText(
                        f"Processando {index + 1} de {total}: CPF/CNPJ {row.document} — CAR {task['car']}"
                    )
                    self.progress.setValue(round(index * 100 / total))
                    QApplication.processEvents()
                    if self.cancel_requested:
                        self._record_cancelled_tasks(index, failures)
                        break
                    try:
                        analysis = self._build_analysis(
                            connection,
                            task,
                            database,
                            car_base,
                            output,
                            analyzer,
                            functions,
                        )
                        analyses.append(analysis)
                        self._set_cell(index, 5, "Concluído")
                        self._set_cell(
                            index,
                            6,
                            analysis["pre_analise"]["classificacao_geral_rotulo"],
                        )
                    except Exception as exc:
                        cancelled = (
                            self.cancel_requested
                            and "cancelado pelo usuário" in str(exc).lower()
                        )
                        failures.append(
                            {
                                "linha": row.source_row,
                                "documento": row.document,
                                "car": task["car"],
                                "estado": "cancelado" if cancelled else "falha",
                                "erro": str(exc),
                            }
                        )
                        self._set_cell(index, 5, "Cancelado" if cancelled else "Falha")
                        self._set_cell(
                            index,
                            6,
                            "Processamento cancelado pelo usuário."
                            if cancelled
                            else str(exc),
                        )
                    QApplication.processEvents()
            finally:
                if getattr(self, "active_worker", None) is not None:
                    self.active_worker.close()
                    self.active_worker = None
                connection.close()
            analyses.sort(
                key=lambda item: (
                    str(item.get("documento_lote")),
                    normalize_car(item.get("car")),
                )
            )
            self.status.setText(
                "Processamento concluído. Escolha onde salvar o PDF e o JSON…"
            )
            self.progress.setValue(96)
            QApplication.processEvents()
            output = self._choose_final_output(output)
            self.status.setText("Montando o PDF consolidado e o JSON de auditoria…")
            QApplication.processEvents()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            document_list = sorted({str(item["documento_lote"]) for item in analyses})
            if not document_list:
                report_name = f"relatorio_falhas_{stamp}.pdf"
            elif len(document_list) == 1:
                report_name = f"relatorio_{document_list[0]}_{stamp}.pdf"
            else:
                report_name = f"relatorio_consolidado_{document_list[0]}_mais_{len(document_list) - 1}_cpfs_{stamp}.pdf"
            report = output / report_name
            summary = {
                "estado": "cancelado"
                if self.cancel_requested
                else "concluido_com_falhas"
                if failures
                else "concluido",
                "linhas_recebidas": len(self.rows),
                "tarefas_preparadas": len(self.tasks),
                "analisados": len(analyses),
                "duplicados": sum(f.get("estado") == "duplicado" for f in failures),
                "cancelados": sum(f.get("estado") == "cancelado" for f in failures),
                "falhas": sum(
                    f.get("estado") not in ("duplicado", "cancelado") for f in failures
                ),
                "planilha_sha256": self.spreadsheet_sha256,
            }
            pdf, audit = write_batch_report(analyses, report, failures, summary)
            self.progress.setValue(100)
            prefix = "Lote parcial" if self.cancel_requested else "Lote concluído"
            self.status.setText(
                f"{prefix}: {len(analyses)} CAR(s), {len(failures)} falha(s). PDF único criado."
            )
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf.resolve())))
            message = f"PDF consolidado: {pdf}\nJSON de auditoria: {audit}\n\nCARs analisados: {len(analyses)}\nFalhas: {len(failures)}"
            if not opened:
                message += "\n\nO visualizador de PDF não abriu automaticamente."
            QMessageBox.information(self, "Lote concluído", message)
        except Exception as exc:
            QMessageBox.critical(self, "Falha no processamento em lote", str(exc))
        finally:
            self.processing = False
            work_directory = getattr(self, "work_directory", None)
            if work_directory is not None:
                shutil.rmtree(work_directory, ignore_errors=True)
                self.work_directory = None
            for control in self.locked_controls:
                control.setEnabled(True)
            self.cancel.setEnabled(False)
            self.process_button.setEnabled(True)

    def closeEvent(self, event):
        if getattr(self, "processing", False):
            event.ignore()
        else:
            super().closeEvent(event)
