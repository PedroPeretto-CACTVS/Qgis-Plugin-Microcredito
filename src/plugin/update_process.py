"""Ponte assíncrona para o atualizador; nenhum dado é importado no QGIS."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from qgis.PyQt.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

MAX_EVENT_BYTES = 3 * 1024 * 1024
_ACTIVE_JOBS = set()


def updates_running() -> bool:
    """Inclui processos que continuam vivos após o fechamento de um diálogo."""
    return bool(_ACTIVE_JOBS)


def python_executable() -> str:
    """Não confunde o executável hospedeiro qgis-bin.exe com Python."""
    candidates = [Path(sys.executable)]
    for prefix in (sys.prefix, sys.base_prefix):
        candidates.extend((Path(prefix) / "python.exe", Path(prefix) / "bin/python3"))
    for candidate in candidates:
        if candidate.name.lower().startswith("python") and candidate.is_file():
            return str(candidate.resolve())
    raise RuntimeError(
        "O Python desta instalação do QGIS não foi localizado. Solicite suporte técnico."
    )


class UpdateProcess(QObject):
    """Expõe progresso e resultado somente após saída confirmada do filho."""

    started = pyqtSignal(int)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()
    progress_changed = pyqtSignal(int, str)

    def __init__(self, request: dict, *, public_key_file: Path | None = None):
        # A referência forte global evita destruir um processo mutante com a UI.
        super().__init__()
        self.request = request
        self.public_key_file = public_key_file
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.readyReadStandardError.connect(self._drain_errors)
        self.process.finished.connect(self._exited)
        self.process.errorOccurred.connect(self._process_error)
        self.process.started.connect(self._send_request)
        self._buffer = bytearray()
        self._result = None
        self._has_result = False
        self._failure = None
        self._protocol_error = False
        self._active = False
        self._done = False
        self.started_at = None
        self.last_response = None
        self.pid = None

    def start(self):
        if self._active or self._done:
            raise RuntimeError("Esta operação já foi iniciada.")
        self._active = True
        self.started_at = time.monotonic()
        _ACTIVE_JOBS.add(self)
        QTimer.singleShot(0, self._launch)

    def isRunning(self) -> bool:
        return self._active

    def _launch(self):
        try:
            executable = python_executable()
            script = Path(__file__).with_name("update_worker.py")
            if not script.is_file():
                raise RuntimeError(
                    "O atualizador não está completo. Reinstale o pacote do plugin."
                )
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("PYTHONIOENCODING", "utf-8")
            environment.insert("PYTHONUNBUFFERED", "1")
            self.process.setProcessEnvironment(environment)
            self.process.setWorkingDirectory(str(script.parent))
            arguments = ["-u", str(script)]
            if self.public_key_file is not None:
                # Usado somente por homologações isoladas; a janela não expõe override.
                arguments.extend(["--public-key-file", str(self.public_key_file)])
            self.process.start(executable, arguments)
        except Exception as exc:
            self._failure = str(exc)
            self._finish(False)

    def _send_request(self):
        payload = json.dumps(self.request, ensure_ascii=True).encode("utf-8") + b"\n"
        self.process.write(payload)
        self.process.closeWriteChannel()

    def _drain_errors(self):
        # Logs inesperados não viram eventos nem são confundidos com sucesso.
        self.process.readAllStandardError()

    def _read_output(self):
        data = bytes(self.process.readAllStandardOutput())
        if self._protocol_error:
            return
        self._buffer.extend(data)
        while b"\n" in self._buffer:
            line, _, remaining = self._buffer.partition(b"\n")
            self._buffer = bytearray(remaining)
            if len(line) > MAX_EVENT_BYTES:
                self._protocol_error = True
                break
            try:
                self._accept_event(json.loads(line))
            except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                self._protocol_error = True
                break
        if len(self._buffer) > MAX_EVENT_BYTES or self._protocol_error:
            self._buffer.clear()
            self._protocol_error = True
        # Não matar o processo: ele pode estar promovendo ou revertendo bases.

    def _accept_event(self, event):
        if not isinstance(event, dict) or event.get("protocol_version") != 1:
            raise ValueError("Protocolo inválido")
        kind = event["event"]
        if kind == "started":
            pid = event["pid"]
            if (
                self.pid is not None
                or type(pid) is not int
                or pid != int(self.process.processId())
            ):
                raise ValueError("Processo inválido")
            self.pid = pid
            self.started.emit(pid)
        elif self.pid is None:
            raise ValueError("Processo sem identificação")
        elif kind == "progress":
            value, message = event["value"], event["message"]
            if (
                type(value) is not int
                or not 0 <= value <= 100
                or not isinstance(message, str)
            ):
                raise ValueError("Progresso inválido")
            self.progress_changed.emit(value, message)
        elif kind == "heartbeat":
            pass
        elif kind == "result":
            if self._has_result or self._failure is not None:
                raise ValueError("Resultado duplicado")
            self._result = event["payload"]
            self._has_result = True
        elif kind == "error":
            if (
                self._has_result
                or self._failure is not None
                or not isinstance(event["message"], str)
            ):
                raise ValueError("Falha inválida")
            self._failure = event["message"]
        else:
            raise ValueError("Evento desconhecido")
        self.last_response = time.monotonic()

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self._failure = "Não foi possível iniciar o processo externo. Nenhuma atualização foi iniciada."
            self._finish(False)

    def _exited(self, code, status):
        self._read_output()
        self._drain_errors()
        complete = (
            status == QProcess.NormalExit
            and code == 0
            and self._has_result
            and self._failure is None
            and not self._protocol_error
            and not self._buffer.strip()
        )
        if not complete and (
            status != QProcess.NormalExit or self._protocol_error or not self._failure
        ):
            self._failure = (
                "O processo externo terminou sem confirmação válida. "
                "Não é possível garantir a conclusão ou a reversão. "
                "Não utilize as bases até verificar o estado da atualização com o suporte."
            )
        self._finish(complete)

    def _finish(self, success):
        if self._done:
            return
        self._done = True
        self._active = False
        _ACTIVE_JOBS.discard(self)
        if success:
            self.completed.emit(self._result)
        else:
            self.failed.emit(self._failure or "Atualização não concluída.")
        self.finished.emit()
