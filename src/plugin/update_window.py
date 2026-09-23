"""Janela de inventário e atualização local das bases de consulta.

Esta camada contém somente interface. A validação criptográfica, a cópia em
estágio e a promoção atômica ficam no núcleo
``qgis_plugin_microcredito.infrastructure.updates``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from urllib.parse import urlparse

from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.gui import QgsAuthConfigSelect
from qgis.PyQt.QtCore import QSettings, Qt, QThread, pyqtSignal
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


DEFAULT_CATALOG_URL = (
    "https://api.github.com/repos/PedroPeretto-CACTVS/Qgis-Plugin-Microcredito/"
    "contents/updates/producao/catalog.json?ref=main"
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
    )


def _github_token(authcfg: str) -> str | None:
    """Lê um PAT apenas em memória; QSettings guarda somente o id authcfg."""
    if not authcfg:
        return None
    config = QgsAuthMethodConfig()
    loaded = QgsApplication.authManager().loadAuthenticationConfig(authcfg, config, True)
    if isinstance(loaded, tuple):
        ok, loaded_config = loaded
        if loaded_config is not None:
            config = loaded_config
    else:  # compatibilidade com bindings QGIS que atualizam por referência
        ok = loaded
    if not ok:
        raise ValueError("Não foi possível abrir a credencial selecionada no QGIS.")
    if config.method() != "Basic":
        raise ValueError("A credencial do GitHub deve usar o método Basic do QGIS.")
    token = config.config("password").strip()
    if not token:
        raise ValueError("A credencial selecionada não possui token no campo de senha.")
    return token


def _is_github_api_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() == "api.github.com"


class _CatalogWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, catalog_url: str, public_key: str, bearer_token: str | None, parent=None):
        super().__init__(parent)
        self.catalog_url = catalog_url
        self.public_key = public_key
        self.bearer_token = bearer_token

    def run(self):
        try:
            CatalogClient, _, _, _, _, _, _, _, _, _ = _load_updates_core()
            self.completed.emit(CatalogClient(
                self.catalog_url, self.public_key, bearer_token=self.bearer_token
            ).fetch_catalog())
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.bearer_token = None


class _ApplyWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress_changed = pyqtSignal(int, str)

    def __init__(self, data_root: Path, database: Path, catalog_url: str, public_key: str,
                 bearer_token: str | None, package, parent=None):
        super().__init__(parent)
        self.data_root = data_root
        self.database = database
        self.catalog_url = catalog_url
        self.public_key = public_key
        self.bearer_token = bearer_token
        self.package = package

    def run(self):
        try:
            CatalogClient, LocalUpdater, _, _, _, _, _, _, _, _ = _load_updates_core()
            client = CatalogClient(self.catalog_url, self.public_key, bearer_token=self.bearer_token)
            updater = LocalUpdater(
                self.data_root, self.database, client,
                progress=lambda value, message: self.progress_changed.emit(value, message),
            )
            self.completed.emit(updater.apply(self.package))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.bearer_token = None


class _RestoreWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress_changed = pyqtSignal(int, str)

    def __init__(self, data_root: Path, database: Path, parent=None):
        super().__init__(parent)
        self.data_root = data_root
        self.database = database

    def run(self):
        try:
            _, _, _, _, _, _, _, _, _, restore_latest = _load_updates_core()
            self.completed.emit(restore_latest(
                self.data_root,
                self.database,
                progress=lambda value, message: self.progress_changed.emit(value, message),
            ))
        except Exception as exc:
            self.failed.emit(str(exc))


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
        self.catalog = None
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

        self.database = QLineEdit(self.settings.value("database", "", type=str))
        self.database.setPlaceholderText("Selecione o banco local car_microcredito.db")
        choose_database = QPushButton("Selecionar…")
        choose_database.clicked.connect(self._select_database)
        database_row = QHBoxLayout()
        database_row.addWidget(self.database, 1)
        database_row.addWidget(choose_database)

        self.catalog_url = QLineEdit(self.settings.value("updates/catalog_url", DEFAULT_CATALOG_URL, type=str))
        self.catalog_url.setPlaceholderText(DEFAULT_CATALOG_URL)
        self.catalog_url.setToolTip("Somente HTTPS. O endereço não recebe nenhuma informação da consulta.")

        self.auth_config = QgsAuthConfigSelect(self)
        saved_authcfg = self.settings.value("updates/authcfg", "", type=str)
        if saved_authcfg:
            self.auth_config.setConfigId(saved_authcfg)
        self.auth_config.setToolTip(
            "Selecione uma configuração Basic do QGIS. Informe um nome genérico como usuário "
            "e o token GitHub de leitura no campo senha. O plugin salva somente o id da configuração."
        )

        setup = QGroupBox("Fontes locais e catálogo do publicador")
        setup_layout = QFormLayout(setup)
        setup_layout.setRowWrapPolicy(QFormLayout.WrapLongRows)
        setup_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        setup_layout.addRow("Banco SQLite", database_row)
        setup_layout.addRow("Catálogo assinado (HTTPS)", self.catalog_url)
        setup_layout.addRow("Credencial do GitHub privado", self.auth_config)

        self.test_warning = QLabel(
            "Atualização 0.9.5 por catálogo assinado: downloads grandes podem ser retomados; a credencial fica "
            "no banco de autenticação criptografado do QGIS; nenhum CPF/CNPJ, CAR, geometria ou resultado de "
            "consulta é enviado ao GitHub."
        )
        self.test_warning.setObjectName("warning")
        self.test_warning.setWordWrap(True)

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
        self.table.itemSelectionChanged.connect(self._update_apply_button)

        self.status_label = QLabel("Informe o banco local para ver as versões já instaladas.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Aguardando operação")
        self.progress.setTextVisible(True)

        self.refresh = QPushButton("Procurar atualizações")
        self.refresh.setObjectName("primary")
        self.refresh.clicked.connect(self.refresh_catalog)
        self.apply = QPushButton("Atualizar selecionada")
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self.apply_selected)
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
        layout.addWidget(self.test_warning)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.progress)
        layout.addLayout(actions)
        self._show_local_inventory()

    def _database_path(self) -> Path | None:
        value = self.database.text().strip()
        if not value:
            return None
        path = Path(value).expanduser()
        return path.resolve() if path.is_file() else None

    def _select_database(self):
        selected, _ = QFileDialog.getOpenFileName(
            self, "Selecionar banco local", self.database.text(), "Banco SQLite (*.db);;Todos os arquivos (*)"
        )
        if selected:
            self.database.setText(selected)
            self._show_local_inventory()

    def _show_local_inventory(self):
        database = self._database_path()
        self.table.setRowCount(0)
        self.statuses = {}
        self.restore_point = None
        self.catalog = None
        self._update_apply_button()
        self.restore.setEnabled(False)
        if database is None:
            self.status_label.setText("Selecione um arquivo car_microcredito.db existente. Nenhuma base foi alterada.")
            return
        try:
            _, _, _, _, _, ensure_not_updating, local_inventory, _, latest_restore_point, _ = _load_updates_core()
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
        self.database.setEnabled(not busy)
        self.catalog_url.setEnabled(not busy)
        self.auth_config.setEnabled(not busy)
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

    def _save_settings(self, database: Path, catalog_url: str, authcfg: str):
        self.settings.setValue("database", str(database))
        self.settings.setValue("updates/catalog_url", catalog_url)
        self.settings.setValue("updates/authcfg", authcfg)

    def refresh_catalog(self):
        database = self._database_path()
        catalog_url = self.catalog_url.text().strip()
        if database is None:
            QMessageBox.information(self, "Banco local", "Selecione um arquivo car_microcredito.db existente.")
            return
        if not catalog_url:
            QMessageBox.information(
                self, "Catálogo de homologação",
                "A versão de teste não possui URL de produção. Informe a URL HTTPS do catálogo assinado de homologação."
            )
            return
        try:
            _, _, public_key, _, _, ensure_not_updating, _, _, _, _ = _load_updates_core()
            ensure_not_updating(database.parent)
            authcfg = self.auth_config.configId()
            bearer_token = _github_token(authcfg) if _is_github_api_url(catalog_url) else None
            if _is_github_api_url(catalog_url) and not bearer_token:
                raise ValueError("Selecione uma credencial Basic com token GitHub de leitura.")
        except Exception as exc:
            QMessageBox.warning(self, "Atualização bloqueada", str(exc))
            return
        self._save_settings(database, catalog_url, authcfg)
        self.progress.setRange(0, 0)
        self.progress.setFormat("Consultando catálogo…")
        self._set_busy(True, "Baixando catálogo e assinatura. Nenhuma base local será modificada nesta etapa…")
        self.worker = _CatalogWorker(catalog_url, public_key, bearer_token, self)
        self.worker.completed.connect(self._catalog_loaded)
        self.worker.failed.connect(self._worker_failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _catalog_loaded(self, catalog):
        database = self._database_path()
        if database is None:
            self._worker_failed("O banco local deixou de estar disponível.")
            return
        try:
            _, _, _, _, compare_catalog, _, _, _, _, _ = _load_updates_core()
            statuses = compare_catalog(catalog, database.parent, database)
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
            values = (
                status.label,
                status.regulatory_basis,
                status.installed_version or "Não identificada",
                status.source_date,
                status.available_version,
                "Atualizada" if status.state == "atual" else "Disponível",
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
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Catálogo validado")
        if available:
            noun = "atualização disponível" if available == 1 else "atualizações disponíveis"
            channel = "produção" if getattr(catalog, "channel", "homologacao") == "producao" else "homologação"
            message = f"Catálogo assinado de {channel} válido. {available} {noun}."
        else:
            message = (
                "Catálogo assinado e válido. Nenhuma atualização disponível: "
                "as versões publicadas já estão instaladas."
            )
        self._set_busy(False, message)

    def _selected_package(self):
        row = self.table.currentRow()
        if row < 0 or self.catalog is None:
            return None
        item = self.table.item(row, 0)
        identifier = item.data(Qt.UserRole) if item else None
        status = self.statuses.get(identifier)
        if status is None or status.state != "disponivel":
            return None
        return next((package for package in self.catalog.packages if package.identifier == identifier), None)

    def _update_apply_button(self):
        if self.worker is not None:
            self.apply.setEnabled(False)
            self.apply.setText("Aguarde…")
            self.apply.setToolTip("Aguarde a operação atual terminar.")
            return

        row = self.table.currentRow()
        if self.catalog is None:
            self.apply.setEnabled(False)
            self.apply.setText("Procurar atualizações primeiro")
            self.apply.setToolTip("Consulte o catálogo assinado antes de escolher uma atualização.")
            return
        if row < 0:
            self.apply.setEnabled(False)
            self.apply.setText("Selecione uma atualização")
            self.apply.setToolTip("Selecione na tabela uma linha marcada como Disponível.")
            return

        item = self.table.item(row, 0)
        identifier = item.data(Qt.UserRole) if item else None
        status = self.statuses.get(identifier)
        if status is not None and status.state == "atual":
            self.apply.setEnabled(False)
            self.apply.setText("Base já atualizada")
            self.apply.setToolTip("A versão publicada desta base já está instalada.")
            return

        package = self._selected_package()
        self.apply.setEnabled(package is not None)
        self.apply.setText("Atualizar selecionada" if package is not None else "Atualização indisponível")
        self.apply.setToolTip(
            f"Instalar a versão {package.version}." if package is not None
            else "A linha selecionada não possui um pacote de atualização válido."
        )

    def apply_selected(self):
        database = self._database_path()
        package = self._selected_package()
        if database is None or package is None:
            return
        answer = QMessageBox.question(
            self, "Confirmar atualização",
            f"Atualizar ‘{package.label}’ para a versão {package.version}?\n\n"
            "O pacote será validado, preparado em cópia temporária e a versão anterior será guardada para reversão.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        catalog_url = self.catalog_url.text().strip()
        _, _, public_key, _, _, _, _, _, _, _ = _load_updates_core()
        try:
            bearer_token = _github_token(self.auth_config.configId()) if _is_github_api_url(catalog_url) else None
        except Exception as exc:
            QMessageBox.warning(self, "Credencial indisponível", str(exc))
            return
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self._set_busy(True, "Validando e aplicando a atualização local. Mantenha esta janela aberta…")
        self.worker = _ApplyWorker(
            database.parent, database, catalog_url, public_key, bearer_token, package, self
        )
        self.worker.completed.connect(self._package_applied)
        self.worker.failed.connect(self._worker_failed)
        self.worker.progress_changed.connect(self._progress_changed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def restore_previous(self):
        database = self._database_path()
        point = self.restore_point
        if database is None or point is None:
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
        self.worker = _RestoreWorker(database.parent, database, self)
        self.worker.completed.connect(self._restore_completed)
        self.worker.failed.connect(self._restore_failed)
        self.worker.progress_changed.connect(self._progress_changed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _package_applied(self, status):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("100% — atualização concluída")
        self._show_local_inventory()
        self.status_label.setText(f"{status.label}: {status.detail}")
        QMessageBox.information(self, "Base atualizada", status.detail)

    def _restore_completed(self, status):
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("100% — restauração concluída")
        self._show_local_inventory()
        self.status_label.setText(f"{status.label}: {status.detail}")
        QMessageBox.information(self, "Versão restaurada", status.detail)

    def _restore_failed(self, message: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Restauração não aplicada")
        self._set_busy(False, f"A versão atual foi preservada: {message}")
        QMessageBox.warning(self, "Restauração não aplicada", message)

    def _worker_failed(self, message: str):
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("Atualização não aplicada")
        self._set_busy(False, f"Nenhuma base foi modificada: {message}")
        QMessageBox.warning(self, "Atualização não aplicada", message)

    def _worker_finished(self):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self._update_apply_button()
        self._update_restore_button()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Atualização em andamento", "Aguarde a conclusão da atualização antes de fechar esta janela.")
            event.ignore()
            return
        event.accept()
