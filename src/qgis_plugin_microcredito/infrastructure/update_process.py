"""JSONL worker used to run base maintenance outside the QGIS process."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, BinaryIO, cast

from qgis_plugin_microcredito.infrastructure.base_access import (
    EXTERNAL_UPDATE_PENDING,
    read_base_access,
)
from qgis_plugin_microcredito.infrastructure.updates import (
    PUBLISHER_PUBLIC_KEY_PEM,
    BaseReleaseBundle,
    Catalog,
    UpdateError,
    _try_lock_stream,
    _unlock_stream,
    _UpdateLockBusy,
    apply_catalog_release,
    compare_catalog,
    latest_restore_point,
    restore_latest,
)

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 2 * 1024 * 1024
HEARTBEAT_SECONDS = 2.0
EXTERNAL_JOB_LOCK = "external-update-process.lock"

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class ProtocolError(UpdateError):
    """Raised when an update-process request violates the public protocol."""


@dataclass
class _JobLock:
    stream: BinaryIO


class JsonLineEmitter:
    """Serialize worker events without allowing a closed pipe to abort maintenance."""

    def __init__(self, stream: IO[str]) -> None:
        self._stream = stream
        self._lock = threading.Lock()
        self._available = True

    def emit(self, event: str, **fields: JsonValue) -> None:
        document: dict[str, JsonValue] = {
            "protocol_version": PROTOCOL_VERSION,
            "event": event,
            **fields,
        }
        encoded = json.dumps(
            document, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise ProtocolError("Evento do processo de atualização acima do limite.")
        with self._lock:
            if not self._available:
                return
            try:
                self._stream.write(encoded.decode("utf-8") + "\n")
                self._stream.flush()
            except (BrokenPipeError, OSError, ValueError):
                self._available = False


class Heartbeat:
    """Emit liveness independently from the operation progress callback."""

    def __init__(self, emitter: JsonLineEmitter) -> None:
        self._emitter = emitter
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=HEARTBEAT_SECONDS + 1)

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT_SECONDS):
            self._emitter.emit("heartbeat")


def catalog_fingerprint(catalog: Catalog) -> str:
    """Return the stable identity used between validation and application."""

    canonical = json.dumps(
        asdict(catalog),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _read_request(stream: IO[bytes]) -> dict[str, JsonValue]:
    payload = stream.read(MAX_MESSAGE_BYTES + 1)
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Solicitação do processo de atualização acima do limite.")
    if not payload:
        raise ProtocolError("Solicitação do processo de atualização ausente.")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Solicitação do processo de atualização inválida.") from exc
    if not isinstance(document, dict):
        raise ProtocolError(
            "Solicitação do processo de atualização deve ser um objeto."
        )
    return cast(dict[str, JsonValue], document)


def _required_text(request: Mapping[str, JsonValue], name: str) -> str:
    value = request.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"Campo obrigatório inválido: {name}.")
    return value


def _paths(request: Mapping[str, JsonValue]) -> tuple[Path, Path]:
    data_root = Path(_required_text(request, "data_root")).resolve()
    database = Path(_required_text(request, "database")).resolve()
    if database.parent != data_root:
        raise ProtocolError(
            "A pasta de dados e o banco SQLite informados são incompatíveis."
        )
    return data_root, database


def _validate_request(request: Mapping[str, JsonValue]) -> str:
    if request.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("Versão do protocolo de atualização incompatível.")
    command = _required_text(request, "command")
    if command not in {"validate", "apply", "restore"}:
        raise ProtocolError("Comando do processo de atualização inválido.")
    return command


def _run_validate(
    request: Mapping[str, JsonValue],
    public_key_pem: str,
    emitter: JsonLineEmitter,
) -> dict[str, JsonValue]:
    data_root, database = _paths(request)
    release_path = Path(_required_text(request, "release_path")).resolve()
    emitter.emit("progress", value=0, message="Validando o Bases Plugin assinado…")
    release = BaseReleaseBundle(release_path, public_key_pem)
    catalog = release.fetch_catalog()
    if data_root.exists():
        with read_base_access(data_root):
            statuses = compare_catalog(catalog, data_root, database)
    else:
        statuses = compare_catalog(catalog, data_root, database)
    emitter.emit("progress", value=100, message="Bases Plugin validado.")
    return {
        "catalog": cast(JsonValue, asdict(catalog)),
        "statuses": cast(JsonValue, [asdict(status) for status in statuses]),
        "catalog_fingerprint": catalog_fingerprint(catalog),
    }


def _acquire_job_lock(data_root: Path) -> _JobLock:
    directory = data_root / ".atualizacoes"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / EXTERNAL_JOB_LOCK
    try:
        stream = path.open("a+b")
        acquired = _try_lock_stream(stream)
    except OSError as exc:
        if "stream" in locals():
            stream.close()
        raise UpdateError(
            "Não foi possível iniciar o processo externo de atualização."
        ) from exc
    if not acquired:
        stream.close()
        raise UpdateError(
            "Já existe outro processo externo de atualização ou restauração em andamento."
        )
    return _JobLock(stream)


def _release_job_lock(lock: _JobLock) -> None:
    try:
        _unlock_stream(lock.stream)
    finally:
        lock.stream.close()


def _marker_path(data_root: Path) -> Path:
    return data_root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING


def _write_pending_marker(
    data_root: Path,
    *,
    command: str,
    fingerprint: str | None,
) -> Path:
    target = _marker_path(data_root)
    if target.exists():
        raise UpdateError(
            "Existe uma atualização externa interrompida ou pendente de verificação. "
            "As bases foram bloqueadas para recuperação segura."
        )
    document: dict[str, JsonValue] = {
        "schema_version": 1,
        "command": command,
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
    }
    if fingerprint is not None:
        document["catalog_fingerprint"] = fingerprint
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(
                json.dumps(
                    document,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _apply_failure_is_safely_recovered(exc: Exception) -> bool:
    """Return true only when the core proves that no partial state remains."""

    if isinstance(exc, _UpdateLockBusy):
        return True
    if not isinstance(exc, UpdateError):
        return False
    message = str(exc)
    if message.startswith(
        "A publicação não foi aplicada; as bases anteriores foram restauradas."
    ):
        return True
    return message in {
        "O Bases Plugin contém pacote incompatível ou inaplicável. "
        "Nenhuma base foi modificada.",
        "O destino das bases locais não é uma pasta válida.",
        "O destino do banco SQLite não é um arquivo válido.",
    }


def _run_apply(
    request: Mapping[str, JsonValue],
    public_key_pem: str,
    emitter: JsonLineEmitter,
) -> list[JsonValue]:
    data_root, database = _paths(request)
    release_path = Path(_required_text(request, "release_path")).resolve()
    expected = _required_text(request, "expected_catalog_fingerprint").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ProtocolError("Identidade esperada do catálogo inválida.")

    emitter.emit("progress", value=0, message="Revalidando o Bases Plugin assinado…")
    release = BaseReleaseBundle(release_path, public_key_pem)
    catalog = release.fetch_catalog()
    actual = catalog_fingerprint(catalog)
    if not hmac.compare_digest(actual, expected):
        raise UpdateError(
            "O Bases Plugin mudou desde a validação. Valide o arquivo novamente."
        )

    job_lock = _acquire_job_lock(data_root)
    marker: Path | None = None
    try:
        marker = _write_pending_marker(data_root, command="apply", fingerprint=actual)
        try:
            statuses = apply_catalog_release(
                catalog,
                data_root,
                database,
                release,
                progress=lambda value, message: emitter.emit(
                    "progress", value=value, message=message
                ),
            )
        except Exception as exc:
            if _apply_failure_is_safely_recovered(exc):
                marker.unlink(missing_ok=True)
            raise
        marker.unlink(missing_ok=True)
        return cast(list[JsonValue], [asdict(status) for status in statuses])
    finally:
        _release_job_lock(job_lock)


def _run_restore(
    request: Mapping[str, JsonValue], emitter: JsonLineEmitter
) -> dict[str, JsonValue]:
    data_root, database = _paths(request)
    if not data_root.is_dir() or not database.is_file():
        raise UpdateError(
            "A pasta de dados e o banco SQLite selecionados são incompatíveis."
        )
    if latest_restore_point(data_root, database) is None:
        raise UpdateError("Não existe versão anterior disponível para restauração.")
    job_lock = _acquire_job_lock(data_root)
    marker: Path | None = None
    try:
        marker = _write_pending_marker(data_root, command="restore", fingerprint=None)
        try:
            status = restore_latest(
                data_root,
                database,
                progress=lambda value, message: emitter.emit(
                    "progress", value=value, message=message
                ),
            )
        except Exception as exc:
            if isinstance(exc, _UpdateLockBusy):
                marker.unlink(missing_ok=True)
            raise
        marker.unlink(missing_ok=True)
        return cast(dict[str, JsonValue], asdict(status))
    finally:
        _release_job_lock(job_lock)


def run_request(
    request: Mapping[str, JsonValue],
    public_key_pem: str,
    emitter: JsonLineEmitter,
) -> JsonValue:
    """Execute one validated request and return its JSON-compatible payload."""

    command = _validate_request(request)
    if command == "validate":
        return _run_validate(request, public_key_pem, emitter)
    if command == "apply":
        return _run_apply(request, public_key_pem, emitter)
    return _run_restore(request, emitter)


def _public_key(arguments: argparse.Namespace) -> str:
    raw_path = arguments.public_key_file
    if raw_path is None:
        return PUBLISHER_PUBLIC_KEY_PEM
    if not isinstance(raw_path, Path):
        raise ProtocolError("Caminho da chave pública de teste inválido.")
    path: Path = raw_path
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ProtocolError("Não foi possível ler a chave pública de teste.") from exc
    if not payload or len(payload) > 32 * 1024:
        raise ProtocolError("Chave pública de teste com tamanho inválido.")
    try:
        return payload.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProtocolError("Chave pública de teste deve usar ASCII.") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """Read exactly one request from stdin and emit protocol-v1 JSONL events."""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--public-key-file", type=Path)
    arguments = parser.parse_args(argv)
    emitter = JsonLineEmitter(sys.stdout)
    emitter.emit("started", pid=os.getpid())
    heartbeat = Heartbeat(emitter)
    heartbeat.start()
    try:
        request = _read_request(sys.stdin.buffer)
        public_key_pem = _public_key(arguments)
        result = run_request(request, public_key_pem, emitter)
        emitter.emit("result", payload=result)
        return 0
    except Exception as exc:
        emitter.emit("error", message=str(exc) or exc.__class__.__name__)
        return 1
    finally:
        heartbeat.close()


if __name__ == "__main__":  # pragma: no cover - exercised through the bootstrap
    raise SystemExit(main())
