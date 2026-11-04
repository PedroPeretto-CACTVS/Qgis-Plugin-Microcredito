import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QEventLoop, QSettings, QTimer
from qgis.PyQt.QtWidgets import QMainWindow, QMessageBox, QPushButton
from test.update_process_support import write_signed_release

from plugin import update_window
from plugin.update_process import UpdateProcess
from plugin.update_window import UpdateWindow


@pytest.mark.parametrize("host_executable", [False, True])
def test_invalid_release_is_checked_in_another_process_without_blocking_qt(
    tmp_path: Path,
    monkeypatch,
    host_executable: bool,
) -> None:
    if host_executable:
        monkeypatch.setattr(sys, "executable", str(tmp_path / "qgis-bin.exe"))
    release = tmp_path / "publicação inválida.carbases"
    release.write_bytes(b"nao e um zip")
    root = tmp_path / "bases André"
    job = UpdateProcess(
        {
            "protocol_version": 1,
            "command": "validate",
            "release_path": str(release),
            "data_root": str(root),
            "database": str(root / "car_microcredito.db"),
        }
    )
    loop = QEventLoop()
    ticks = []
    pids = []
    failures = []
    results = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(True))
    job.started.connect(pids.append)
    job.failed.connect(failures.append)
    job.completed.connect(results.append)
    job.finished.connect(loop.quit)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timer.start()
    timeout.start(15000)
    job.start()
    loop.exec_()
    timer.stop()
    timeout.stop()

    assert not job.isRunning()
    assert len(pids) == 1 and pids[0] > 0 and pids[0] != os.getpid()
    assert ticks, "A interface Qt deve continuar processando eventos."
    assert failures and not results
    assert not root.exists(), "Validar não deve criar nem alterar bases locais."


def test_window_keeps_package_selection_locked_until_external_validation_finishes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        update_window,
        "QSettings",
        lambda *_args, **_kwargs: QSettings(
            str(tmp_path / "settings.ini"), QSettings.IniFormat
        ),
    )

    class Iface:
        @staticmethod
        def mainWindow():
            return None

    release = tmp_path / "invalido.carbases"
    release.write_bytes(b"invalido")
    window = UpdateWindow(Iface())
    window.release_path.setText(str(release))
    picker = next(
        button
        for button in window.findChildren(QPushButton)
        if button.text() == "Selecionar Bases Plugin…"
    )
    loop = QEventLoop()
    try:
        with patch.object(QMessageBox, "warning") as warning:
            window.refresh_catalog()
            picker_locked = not picker.isEnabled()
            field_locked = not window.release_path.isEnabled()
            window.worker.finished.connect(loop.quit)
            QTimer.singleShot(15000, loop.quit)
            loop.exec_()
            assert picker_locked
            assert field_locked
            assert picker.isEnabled()
            assert window.release_path.isEnabled()
            assert warning.called
            assert "Atualização não concluída" in window.status_label.text()
    finally:
        if window.worker is not None:
            window.worker.finished.connect(loop.quit)
            loop.exec_()
        window.close()


def test_signed_release_is_applied_and_restored_by_distinct_external_processes(
    tmp_path: Path,
) -> None:
    fixture = write_signed_release(tmp_path / "publicador")
    root = tmp_path / "bases André"
    target = root / fixture.target
    target.parent.mkdir(parents=True)
    target.write_bytes(b"edicao anterior")
    request = {
        "protocol_version": 1,
        "command": "validate",
        "release_path": str(fixture.release),
        "data_root": str(root),
        "database": str(root / "car_microcredito.db"),
    }
    pids = []

    def execute():
        job = UpdateProcess(request.copy(), public_key_file=fixture.public_key)
        results, failures = [], []
        loop = QEventLoop()
        job.started.connect(pids.append)
        job.completed.connect(results.append)
        job.failed.connect(failures.append)
        job.finished.connect(loop.quit)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(15000)
        job.start()
        loop.exec_()
        timeout.stop()
        assert not job.isRunning()
        assert not failures, failures
        assert len(results) == 1
        return results[0]

    validated = execute()
    assert validated["statuses"][0]["state"] == "disponivel"
    request["expected_catalog_fingerprint"] = validated["catalog_fingerprint"]
    request["command"] = "apply"
    applied = execute()
    assert applied[0]["state"] == "atual"
    assert target.read_bytes() == fixture.published_content
    request["command"] = "restore"
    restored = execute()
    assert restored["identifier"] == "fonte_teste"
    assert target.read_bytes() == b"edicao anterior"
    assert len(set(pids)) == 3 and os.getpid() not in pids


def test_interrupted_external_process_never_reports_success(tmp_path: Path) -> None:
    fixture = write_signed_release(tmp_path / "publicador")
    root = tmp_path / "bases"
    job = UpdateProcess(
        {
            "protocol_version": 1,
            "command": "validate",
            "release_path": str(fixture.release),
            "data_root": str(root),
            "database": str(root / "car_microcredito.db"),
        },
        public_key_file=fixture.public_key,
    )
    results, failures = [], []
    loop = QEventLoop()
    job.started.connect(lambda _pid: job.process.kill())
    job.completed.connect(results.append)
    job.failed.connect(failures.append)
    job.finished.connect(loop.quit)
    QTimer.singleShot(15000, loop.quit)
    job.start()
    loop.exec_()
    assert not job.isRunning()
    assert not results
    assert len(failures) == 1 and "sem confirmação válida" in failures[0]
    assert not root.exists()


def test_window_and_qgis_close_wait_for_the_external_job(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(
        update_window,
        "QSettings",
        lambda *_args, **_kwargs: QSettings(
            str(tmp_path / "settings.ini"), QSettings.IniFormat
        ),
    )
    main_window = QMainWindow()

    class Iface:
        def __init__(self, host):
            self.host = host

        def mainWindow(self):
            return self.host

    release = tmp_path / "invalido.carbases"
    release.write_bytes(b"invalid")
    main_window.show()
    window = UpdateWindow(Iface(main_window))
    window.show()
    window.release_path.setText(str(release))
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    try:
        with (
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "warning"),
        ):
            window.refresh_catalog()
            job = window.worker
            job.finished.connect(loop.quit)
            timeout.start(15000)
            dialog_closed = window.close()
            qgis_closed = main_window.close()
            remained_visible = window.isVisible() and main_window.isVisible()
            loop.exec_()
            assert not dialog_closed and not qgis_closed
            assert remained_visible
            assert not job.isRunning()
            assert window.close()
            assert main_window.close()
    finally:
        timeout.stop()
        # Release the fake QGIS host while its Python adapter is still alive;
        # cyclic GC must not dispatch Qt events through a cleared test closure.
        main_window.removeEventFilter(window)
        window.close()
        main_window.close()
        window.deleteLater()
        main_window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
