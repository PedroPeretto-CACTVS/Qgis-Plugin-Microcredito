"""The user validates and installs prepared bases through actual Qt clicks."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QSettings,
    Qt,
    QTimer,
)
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QMessageBox, QPushButton

from database.session import connect
from installer.prebuilt_bases import prepare_prebuilt_bases
from installer.prebuilt_release import build_prebuilt_release
from plugin import update_window
from plugin.update_process import UpdateProcess
from qgis_plugin_microcredito.application.query_service import find_by_car


class Iface:
    @staticmethod
    def mainWindow() -> None:
        return None


def _wait_for_job(job: UpdateProcess, timeout_ms: int = 30000) -> None:
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    job.finished.connect(loop.quit)
    try:
        timeout.start(timeout_ms)
        if job.isRunning():
            loop.exec_()
    finally:
        timeout.stop()
    assert not job.isRunning(), "O processo externo não concluiu dentro do limite."


def test_real_qt_clicks_copy_prebuilt_bases_into_fixed_local_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    from prebuilt_support import SYNTHETIC_CAR, write_complete_release
    from update_process_support import TEST_PUBLIC_KEY_PEM

    source = write_complete_release(tmp_path / "publisher")
    candidate = tmp_path / "candidate"
    manifest_path = prepare_prebuilt_bases(
        source.release, candidate, TEST_PUBLIC_KEY_PEM
    )
    manifest = json.loads(manifest_path.read_bytes())
    manifest["prepared_at"] = "2026-10-27T10:00:00-03:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    release = tmp_path / "bases-plugin-27-10-2026.carbases"
    build_prebuilt_release(candidate, release, TEST_PUBLIC_KEY_PEM)

    local_app_data = tmp_path / "local-app-data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    # The test-only dependency directory must also be visible to QProcess.
    dependencies = str(Path(pytest.__file__).resolve().parents[1])
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(filter(None, (dependencies, os.environ.get("PYTHONPATH")))),
    )
    monkeypatch.setattr(
        update_window,
        "QSettings",
        lambda *_args, **_kwargs: QSettings(
            str(tmp_path / "qsettings.ini"), QSettings.IniFormat
        ),
    )
    jobs: list[UpdateProcess] = []
    pids: list[int] = []
    failures: list[str] = []

    def process_factory(request: dict) -> UpdateProcess:
        job = UpdateProcess(request, public_key_file=source.public_key)
        job.started.connect(pids.append)
        job.failed.connect(failures.append)
        jobs.append(job)
        return job

    monkeypatch.setattr(update_window, "UpdateProcess", process_factory)
    window = update_window.UpdateWindow(Iface())
    fixed_root = local_app_data / "Cactvs" / "BasesPlugin"
    ticks: list[float] = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    try:
        window.show()
        window.release_path.setText(str(release))
        assert window.local_paths.root == fixed_root
        assert not fixed_root.exists()
        timer.start()
        with (
            patch.object(QMessageBox, "warning") as warning,
            patch.object(QMessageBox, "critical") as critical,
            patch.object(QMessageBox, "information") as information,
            patch.object(
                QMessageBox, "question", return_value=QMessageBox.Yes
            ) as question,
        ):
            QTest.mouseClick(window.refresh, Qt.LeftButton)
            assert len(jobs) == 1
            _wait_for_job(jobs[-1])
            assert not failures, failures
            assert not warning.called, warning.call_args
            assert not critical.called, critical.call_args
            assert window.worker is None
            assert window.release_format == "prebuilt"
            assert window.apply.isEnabled()
            assert "assinatura" not in window.release_help.text().casefold()
            assert "assinado" not in window.status_label.text().casefold()
            assert not fixed_root.exists(), "Validar não pode instalar bases."
            ticks_before_apply = len(ticks)

            QTest.mouseClick(window.apply, Qt.LeftButton)
            assert len(jobs) == 2
            _wait_for_job(jobs[-1])

            assert not failures, failures
            assert not warning.called, warning.call_args
            assert not critical.called, critical.call_args
            assert question.call_count == 1
            confirmation = question.call_args.args[2].casefold()
            assert "cópia" in confirmation
            assert "restauradas automaticamente" not in confirmation
            assert information.call_count == 1
            success = information.call_args.args[2].casefold()
            assert "cópia" in success
            assert "ficaram disponíveis para restauração" not in success
            assert not window.restore.isEnabled()
            assert window.worker is None
            assert window.progress.value() == 100
            assert len(ticks) > ticks_before_apply

        assert len(pids) == 2
        assert len(set(pids)) == 2
        assert os.getpid() not in pids
        assert len(manifest["files"]) == 35
        assert all((fixed_root / relative).is_file() for relative in manifest["files"])
        assert len(list((fixed_root / "car").rglob("*.gpkg"))) == 27
        assert len(list((fixed_root / "ambientais").glob("*.gpkg"))) == 6
        database = fixed_root / "car_microcredito.db"
        assert (
            hashlib.sha256(database.read_bytes()).hexdigest()
            == manifest["files"]["car_microcredito.db"]["sha256"]
        )
        with closing(connect(database, readonly=True)) as connection:
            matches = find_by_car(connection, SYNTHETIC_CAR)
            assert len(matches) == 1
            assert matches[0]["ref_bacen"] == "1"
        buttons = {button.text() for button in window.findChildren(QPushButton)}
        assert "Selecionar…" not in buttons
    finally:
        timer.stop()
        for job in jobs:
            if job.isRunning():
                job.process.kill()
                _wait_for_job(job, timeout_ms=5000)
        window.activity_timer.stop()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
