"""Janela de inventário e atualização local das bases de consulta.

Esta camada contém somente interface. A validação criptográfica, a cópia em
estágio e a promoção atômica ficam no núcleo
``qgis_plugin_microcredito.infrastructure.updates``.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

from qgis.PyQt.QtCore import QEvent, QSettings, Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
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

from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)

from .update_process import UpdateProcess


DEFAULT_CATALOG_URL = ""
RETIRED_CATALOG_URLS = frozenset(
    {
        (
            "https://api.github.com/repos/Andre-Marchetti-Cactvs/"
            "Qgis_plugin-microcredito/contents/updates/homologacao/catalog.json?"
            "ref=codex%2F0.9.0-central-updater"
        ),
        (
            "https://api.github.com/repos/Andre-Marchetti-Cactvs/"
            "Qgis_plugin-microcredito/contents/updates/homologacao/catalog.json?"
            "ref=codex%2Fhomologacao-0.9.8-atualizacao-bases"
        ),
    }
)


def _load_updates_core():
    bundled = Path(__file__).parent / "lib"
    bundled_text = str(bundled)
    if bundled.is_dir():
        if bundled_text in sys.path:
            sys.path.remove(bundled_text)
        sys.path.insert(0, bundled_text)
    module_name = "qgis_plugin_microcredito.infrastructure.updates"
    module = importlib.import_module(module_name)
    if bundled.is_dir():
        expected = (
            bundled
            / "qgis_plugin_microcredito"
            / "infrastructure"
            / "updates.py"
        ).resolve()
        loaded = Path(getattr(module, "__file__", "")).resolve()
        if loaded != expected:
            for name in tuple(sys.modules):
                if name == "qgis_plugin_microcredito" or name.startswith(
                    "qgis_plugin_microcredito."
                ):
                    del sys.modules[name]
            importlib.invalidate_caches()
            module = importlib.import_module(module_name)
    if not hasattr(module, "restore_latest"):
        importlib.invalidate_caches()
        module = importlib.reload(module)
    return (
        module.CatalogClient,
        module.LocalUpdater,
        module.PUBLISHER_PUBLIC_KEY_PEM,
        module.UpdateError,
        module.compare_catalog,
        module.ensure_not_updating,
        module.local_inventory,
        module.local_versions,
        module.latest_restore_point,
        module.restore_latest,
        module.BaseReleaseBundle,
        module.apply_catalog_release,
    )


class UpdateWindow(QDialog):
    """Não coleta nem transmite dados de consultas, CPF/CNPJ ou geometrias."""

    TABLE_COLUMNS = (
        "Base/evidência",
        "Referência",
        "Data/versão local",
        "Data de referência da fonte",
        "Versão publicada",
        "Base local",
        "Cobertura normativa",
        "Detalhe",
    )

    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.settings = QSettings("Cactvs", "CARMicrocredito")
        self.local_paths = default_local_data_paths()
        self.catalog = None
        self.catalog_fingerprint = None
        self.statuses = {}
        self.restore_point = None
        self.worker = None

        self.setWindowTitle("CAR Microcrédito | Bases de consulta")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "icon.svg")))
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setMinimumSize(780, 430)
        self.resize(980, 570)
        self.setStyleSheet("""
            QDialog { background: #f4f7f5; }
            QGroupBox { background: white; border: 1px solid #ccd8d3; border-radius: 8px;
                        margin-top: 12px; padding: 12px 10px 10px 10px; font-weight: 600; color: #25483b; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QLineEdit { min-height: 30px; padding: 0 8px; border: 1px solid #aebdb7;
                        border-radius: 5px; background: white; }
            QPushButton { min-height: 30px; padding: 0 14px; border: 1px solid #9aaba4;
                          border-radius: 5px; background: #ffffff; color: #243d34; font-weight: 600; }
            QPushButton#primary { background: #19734f; color: white; border-color: #165c41; }
            QPushButton:disabled { background: #eef1ef; color: #8a9691; border-color: #cdd5d1; }
            QPushButton#primary:disabled { background: #aab8b2; color: #eef3f1; border-color: #aab8b2; }
            QTableWidget { background: white; border: 1px solid #ccd8d3; border-radius: 6px;
                           gridline-color: #e0e7e4; alternate-background-color: #f4f8f6; }
            QHeaderView::section { background: #e7f0ec; color: #25483b; padding: 7px;
                                   border: 0; border-right: 1px solid #ccd8d3; font-weight: 600; }
            QLabel#warning { background: #fff3d6; color: #7a4b00; border: 1px solid #d9ad58;
                             border-radius: 5px; padding: 8px; }
            QLabel#status { background: #edf5f1; color: #25483b; border-radius: 5px; padding: 8px; }
        """)

        self.settings.remove("updates/catalog_url")
        self.settings.remove("updates/authcfg")
        self.release_path = QLineEdit(
            self.settings.value("updates/release_path", "", type=str)
        )
        self.release_path.setPlaceholderText(
            "Selecione o arquivo .carbases do Bases Plugin"
        )
        self.choose_release = QPushButton("Selecionar Bases Plugin…")
        self.choose_release.clicked.connect(self._select_release)
        release_row = QHBoxLayout()
        release_row.addWidget(self.release_path, 1)
        release_row.addWidget(self.choose_release)

        setup = QGroupBox("Bases Plugin")
        setup_layout = QFormLayout(setup)
        setup_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        setup_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        setup_layout.addRow("Arquivo .carbases", release_row)

        self.release_help = QLabel(
            "O Bases Plugin trabalha offline: valida assinatura, versão, compatibilidade e "
            "integridade antes de alterar as bases locais. Nenhum CPF/CNPJ, CAR, "
            "geometria ou resultado de consulta é enviado."
        )
        self.release_help.setObjectName("warning")
        self.release_help.setWordWrap(True)

        self.table = QTableWidget(0, len(self.TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(self.TABLE_COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)

        self.status_label = QLabel("Selecione um Bases Plugin para validar e atualizar as bases.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Aguardando operação")
        self.progress.setTextVisible(True)
        self.activity_label = QLabel("A preparação será executada fora do processo do QGIS.")
        self.activity_label.setWordWrap(True)
        self.activity_timer = QTimer(self)
        self.activity_timer.setInterval(1000)
        self.activity_timer.timeout.connect(self._update_activity)

        self.refresh = QPushButton("Validar Bases Plugin")
        self.refresh.setObjectName("primary")
        self.refresh.clicked.connect(self.refresh_catalog)
        self.apply = QPushButton("Aplicar Bases Plugin")
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self.apply_release)
        self.restore = QPushButton("Restaurar versão anterior")
        self.restore.setEnabled(False)
        self.restore.clicked.connect(self.restore_previous)
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        actions = QHBoxLayout()
        actions.addWidget(self.refresh)
        actions.addWidget(self.apply)
        actions.addWidget(self.restore)
        actions.addStretch(1)
        actions.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(setup)
        layout.addWidget(self.release_help)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.activity_label)
        layout.addLayout(actions)
        self.release_path.textEdited.connect(self._release_changed)
        if self.iface.mainWindow() is not None:
            self.iface.mainWindow().installEventFilter(self)
        self._show_local_inventory()

    def _release_changed(self):
        self.catalog = None
        self.catalog_fingerprint = None
        self.statuses = {}
        self._update_apply_button()

    def _start_process(self, command, completed):
        database = self._database_path()
        request = {
            "protocol_version": 1,
            "command": command,
            "data_root": str(database.parent),
            "database": str(database),
        }
        if command != "restore":
            request["release_path"] = str(Path(self.release_path.text().strip()).expanduser().resolve())
        if command == "apply":
            request["expected_catalog_fingerprint"] = self.catalog_fingerprint
        self.worker = UpdateProcess(request)
        self.worker.completed.connect(completed)
        self.worker.failed.connect(self._worker_failed)
        self.worker.progress_changed.connect(self._progress_changed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()
        self.activity_timer.start()
        self._update_activity()

    def _update_activity(self):
        worker = self.worker
        if worker is None or worker.started_at is None:
            return
        now = time.monotonic()
        elapsed = int(now - worker.started_at)
        if worker.last_response is None:
            state = "Iniciando processo externo"
        else:
            silence = int(now - worker.last_response)
            state = (f"Processo externo {worker.pid} ativo" if silence < 10
                     else f"Sem resposta do processo externo há {silence}s; conclusão ainda não confirmada")
        self.activity_label.setText(f"{state} • tempo decorrido {elapsed // 60:02d}:{elapsed % 60:02d}")

    def eventFilter(self, watched, event):
        if (watched is self.iface.mainWindow() and event.type() == QEvent.Close
                and self.worker is not None and self.worker.isRunning()):
            QMessageBox.information(self, "Atualização em andamento",
                                    "Aguarde a conclusão antes de fechar o QGIS. O processamento está em uma aplicação separada.")
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def _database_path(self) -> Path:
        return self.local_paths.database.resolve()

    def _select_release(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar Bases Plugin",
            self.release_path.text(),
            "Bases Plugin (*.carbases);;Todos os arquivos (*)",
        )
        if selected:
            self.release_path.setText(selected)
            self.refresh_catalog()

    def _show_local_inventory(self):
        database = self._database_path()
        self.table.setRowCount(0)
        self.statuses = {}
        self.restore_point = None
        self.catalog = None
        self.catalog_fingerprint = None
        self._update_apply_button()
        self.restore.setEnabled(False)
        try:
            (
                _,
                _,
                _,
                _,
                _,
                ensure_not_updating,
                local_inventory,
                _,
                latest_restore_point,
                _,
                _,
                _,
            ) = _load_updates_core()
            if database.parent.exists():
                ensure_not_updating(database.parent)
            inventory = local_inventory(database.parent, database)
            self.restore_point = latest_restore_point(database.parent, database)
        except Exception as exc:
            self.status_label.setText(f"A consulta de versões locais foi bloqueada: {exc}")
            return
        for item in inventory:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = (
                item.label,
                item.regulatory_basis,
                item.local_version or "Não identificada",
                "Não declarada localmente",
                "—",
                item.local_state,
                item.coverage,
                item.detail,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 0:
                    cell.setData(Qt.UserRole, item.identifier)
                self.table.setItem(row, column, cell)
        self.status_label.setText(
            f"Inventário de requisitos concluído: {len(inventory)} fonte(s) avaliadas. "
            "Datas de arquivo local não são apresentadas como data oficial de publicação. "
            "Licenças, outorgas, projeto, garantias e liberação permanecem em checklist documental."
        )
        self._update_restore_button()

    def _set_busy(self, busy: bool, message: str):
        self.refresh.setEnabled(not busy)
        if busy:
            self.apply.setEnabled(False)
            self.apply.setText("Aguarde…")
            self.apply.setToolTip("Aguarde a operação atual terminar.")
        else:
            self._update_apply_button()
        self.restore.setEnabled(not busy and self.restore_point is not None)
        self.release_path.setEnabled(not busy)
        self.choose_release.setEnabled(not busy)
        self.status_label.setText(message)

    def _update_restore_button(self):
        enabled = self.worker is None and self.restore_point is not None
        self.restore.setEnabled(enabled)
        if self.restore_point is None:
            self.restore.setToolTip("Ainda não existe uma versão anterior registrada para restauração.")
            return
        version = self.restore_point.restore_version or "estado local anterior"
        legacy = " (backup criado pela 0.9.0)" if self.restore_point.legacy else ""
        self.restore.setToolTip(f"Restaurar {self.restore_point.label} para {version}{legacy}.")

    def _progress_changed(self, value: int, message: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(value)
        self.progress.setFormat("%p%")
        self.status_label.setText(message)

    def _save_settings(self, release_path: Path):
        self.settings.setValue("updates/release_path", str(release_path))
        self.settings.sync()

    def refresh_catalog(self):
        if self.worker is not None:
            return
        database = self._database_path()
        release_path = Path(self.release_path.text().strip()).expanduser()
        if not release_path.is_file():
            QMessageBox.information(
                self,
                "Bases Plugin",
                "Selecione um arquivo .carbases do Bases Plugin fornecido pelo líder do projeto.",
            )
            return
        try:
            (
                _,
                _,
                public_key,
                _,
                _,
                ensure_not_updating,
                _,
                _,
                _,
                _,
                _,
                _,
            ) = _load_updates_core()
            if database.parent.exists():
                ensure_not_updating(database.parent)
        except Exception as exc:
            QMessageBox.warning(self, "Atualização bloqueada", str(exc))
            return
        release_path = release_path.resolve()
        self._save_settings(release_path)
        self.progress.setRange(0, 0)
        self.progress.setFormat("Validando pacote…")
        self._set_busy(
            True,
            "Validando assinatura e integridade de todas as bases. Nenhuma base local será modificada nesta etapa…",
        )
        self.catalog = None
        self.catalog_fingerprint = None
        self.statuses = {}
        self._start_process("validate", self._catalog_loaded)

    def _catalog_loaded(self, result):
        try:
            from qgis_plugin_microcredito.infrastructure.updates import Catalog, CatalogPackage, UpdateStatus

            document = dict(result["catalog"])
            document["packages"] = tuple(CatalogPackage(**item) for item in document["packages"])
            catalog = Catalog(**document)
            statuses = [UpdateStatus(**item) for item in result["statuses"]]
            self.catalog_fingerprint = result["catalog_fingerprint"]
        except Exception as exc:
            self._worker_failed(str(exc))
            return
        self.catalog = catalog
        self.statuses = {status.identifier: status for status in statuses}
        self.table.setRowCount(0)
        first_available_row = None
        for status in statuses:
            row = self.table.rowCount()
            self.table.insertRow(row)
            if status.state == "disponivel" and first_available_row is None:
                first_available_row = row
            local_state = {
                "atual": "Atualizada",
                "disponivel": "Disponível",
                "inaplicavel": "Não aplicável",
            }.get(status.state, status.state)
            values = (
                status.label,
                status.regulatory_basis,
                status.installed_version or "Não identificada",
                status.source_date,
                status.available_version,
                local_state,
                status.coverage,
                status.detail,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 0:
                    cell.setData(Qt.UserRole, status.identifier)
                self.table.setItem(row, column, cell)
        if statuses:
            self.table.selectRow(first_available_row if first_available_row is not None else 0)
        available = sum(status.state == "disponivel" for status in statuses)
        blocked = sum(status.state == "inaplicavel" for status in statuses)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Pacote validado")
        if available:
            noun = "atualização disponível" if available == 1 else "atualizações disponíveis"
            channel = "produção" if getattr(catalog, "channel", "homologacao") == "producao" else "homologação"
            message = f"Bases Plugin de {channel} válido. {available} {noun}."
        elif blocked:
            message = (
                "Bases Plugin anterior ao estado local mais recente. "
                "Nenhum pacote regressivo pode ser aplicado."
            )
        else:
            message = (
                "Bases Plugin assinado e válido. Nenhuma atualização disponível: "
                "as versões publicadas já estão instaladas."
            )
        self._set_busy(False, message)

    def _update_apply_button(self):
        if self.worker is not None:
            self.apply.setEnabled(False)
            self.apply.setText("Aguarde…")
            self.apply.setToolTip("Aguarde a operação atual terminar.")
            return

        if self.catalog is None:
            self.apply.setEnabled(False)
            self.apply.setText("Validar Bases Plugin primeiro")
            self.apply.setToolTip("Valide o Bases Plugin assinado antes de aplicá-lo.")
            return
        available = sum(
            status.state == "disponivel" for status in self.statuses.values()
        )
        self.apply.setEnabled(available > 0)
        self.apply.setText(
            f"Aplicar Bases Plugin ({available})"
            if available
            else "Bases já atualizadas"
        )
        self.apply.setToolTip(
            "Aplicar todas as bases novas como uma única operação reversível."
            if available
            else "Todas as versões desta publicação já estão instaladas."
        )

    def apply_release(self):
        if self.worker is not None:
            return
        database = self._database_path()
        catalog = self.catalog
        release_path = Path(self.release_path.text().strip()).expanduser()
        available = sum(
            status.state == "disponivel" for status in self.statuses.values()
        )
        if catalog is None or not release_path.is_file() or not available:
            return
        answer = QMessageBox.question(
            self,
            "Confirmar Bases Plugin",
            f"Aplicar {available} atualização(ões) da publicação selecionada?\n\n"
            "Todas serão validadas. Se uma falhar, as anteriores serão restauradas automaticamente.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self._set_busy(True, "Aplicando em processo separado. Aguarde antes de consultar as bases ou fechar o QGIS…")
        self._start_process("apply", self._package_applied)

    def restore_previous(self):
        if self.worker is not None:
            return
        database = self._database_path()
        point = self.restore_point
        if point is None:
            QMessageBox.information(self, "Restauração", "Não existe versão anterior disponível para restauração.")
            return
        version = point.restore_version or "o estado local anterior"
        answer = QMessageBox.question(
            self,
            "Confirmar restauração",
            f"Restaurar ‘{point.label}’ para {version}?\n\n"
            "A versão atual será preservada como um novo ponto de restauração. "
            "Nenhum dado de consulta será enviado ao publicador.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self._set_busy(True, "Validando o histórico antes da restauração…")
        self._start_process("restore", self._restore_completed)

    def _package_applied(self, statuses):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("100% — atualização concluída")
        self._show_local_inventory()
        count = len(statuses)
        message = (
            f"Pacote aplicado com sucesso: {count} base(s) atualizada(s). "
            "As versões anteriores ficaram disponíveis para restauração."
        )
        self.status_label.setText(message)
        QMessageBox.information(self, "Bases Plugin aplicado", message)

    def _restore_completed(self, status):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("100% — restauração concluída")
        self._show_local_inventory()
        self.status_label.setText(f"{status['label']}: {status['detail']}")
        QMessageBox.information(self, "Versão restaurada", status["detail"])

    def _worker_failed(self, message: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Atualização não concluída")
        self._set_busy(False, f"Atualização não concluída: {message}")
        QMessageBox.warning(self, "Atualização não concluída", message)

    def _worker_finished(self):
        worker = self.worker
        self.worker = None
        self.activity_timer.stop()
        self.activity_label.setText("Processo externo encerrado. Confira o resultado acima.")
        if worker is not None:
            worker.deleteLater()
        self.refresh.setEnabled(True)
        self.release_path.setEnabled(True)
        self.choose_release.setEnabled(True)
        self._update_apply_button()
        self._update_restore_button()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Atualização em andamento", "Aguarde a conclusão da atualização antes de fechar esta janela.")
            event.ignore()
            return
        event.accept()
