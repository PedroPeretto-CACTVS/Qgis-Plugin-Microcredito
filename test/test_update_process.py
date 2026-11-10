from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from qgis_plugin_microcredito.infrastructure.base_access import EXTERNAL_UPDATE_PENDING
from update_process_support import write_signed_release

ROOT = Path(__file__).parents[1]
WORKER = ROOT / "src" / "plugin" / "update_worker.py"


def _run_worker(
    request: dict[str, object], *, public_key: Path | None = None
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-X", "utf8", "-u", str(WORKER)]
    if public_key is not None:
        command.extend(("--public-key-file", str(public_key)))
    return subprocess.run(
        command,
        input=json.dumps(request),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        check=False,
        timeout=20,
    )


def _events(process: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    """Read operation events independently of optional liveness messages."""
    events = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    return [event for event in events if event["event"] != "heartbeat"]


def test_validate_invalid_release_reports_protocol_error_without_creating_database(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "bases"
    database = data_root / "car_microcredito.db"
    release = tmp_path / "invalido.carbases"
    release.write_bytes(b"nao-e-um-zip")

    process = _run_worker(
        {
            "protocol_version": 1,
            "command": "validate",
            "release_path": str(release),
            "data_root": str(data_root),
            "database": str(database),
        }
    )

    events = _events(process)
    assert process.returncode != 0
    assert events[0]["event"] == "started"
    assert events[-1]["event"] == "error"
    assert "Bases Plugin inválido" in str(events[-1]["message"])
    assert not database.exists()


def test_validate_signed_release_returns_catalog_statuses_and_stable_fingerprint(
    tmp_path: Path,
) -> None:
    fixture = write_signed_release(tmp_path / "publicação")
    data_root = tmp_path / "dados André"
    request = {
        "protocol_version": 1,
        "command": "validate",
        "release_path": str(fixture.release),
        "data_root": str(data_root),
        "database": str(data_root / "car_microcredito.db"),
    }

    first = _run_worker(request, public_key=fixture.public_key)
    second = _run_worker(request, public_key=fixture.public_key)

    first_events = _events(first)
    second_events = _events(second)
    assert first.returncode == second.returncode == 0
    assert [event["event"] for event in first_events] == [
        "started",
        "progress",
        "progress",
        "result",
    ]
    payload = first_events[-1]["payload"]
    assert isinstance(payload, dict)
    assert payload["catalog"]["packages"][0]["identifier"] == "fonte_teste"
    assert payload["statuses"][0]["state"] == "disponivel"
    assert len(payload["catalog_fingerprint"]) == 64
    assert (
        payload["catalog_fingerprint"]
        == second_events[-1]["payload"]["catalog_fingerprint"]
    )
    assert not data_root.exists()


def test_apply_revalidates_fingerprint_and_applies_signed_release_in_subprocess(
    tmp_path: Path,
) -> None:
    fixture = write_signed_release(tmp_path / "publicação")
    data_root = tmp_path / "dados André"
    database = data_root / "car_microcredito.db"
    request = {
        "protocol_version": 1,
        "command": "validate",
        "release_path": str(fixture.release),
        "data_root": str(data_root),
        "database": str(database),
    }
    validated = _run_worker(request, public_key=fixture.public_key)
    validated_payload = _events(validated)[-1]["payload"]
    assert isinstance(validated_payload, dict)

    rejected = _run_worker(
        {
            **request,
            "command": "apply",
            "expected_catalog_fingerprint": "0" * 64,
        },
        public_key=fixture.public_key,
    )

    assert rejected.returncode != 0
    assert "mudou desde a validação" in str(_events(rejected)[-1]["message"])
    assert not database.exists()
    assert not (data_root / fixture.target).exists()

    applied = _run_worker(
        {
            **request,
            "command": "apply",
            "expected_catalog_fingerprint": validated_payload["catalog_fingerprint"],
        },
        public_key=fixture.public_key,
    )

    applied_events = _events(applied)
    assert applied.returncode == 0, applied.stderr
    assert applied_events[-1]["event"] == "result"
    assert applied_events[-1]["payload"][0]["identifier"] == "fonte_teste"
    assert (data_root / fixture.target).read_bytes() == fixture.published_content
    assert database.is_file()
    assert not (data_root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING).exists()


def test_restore_runs_in_subprocess_and_restores_latest_component(
    tmp_path: Path,
) -> None:
    fixture = write_signed_release(tmp_path / "publicação")
    data_root = tmp_path / "dados André"
    database = data_root / "car_microcredito.db"
    target = data_root / fixture.target
    target.parent.mkdir(parents=True)
    target.write_text("versão anterior", encoding="utf-8")
    base_request = {
        "protocol_version": 1,
        "release_path": str(fixture.release),
        "data_root": str(data_root),
        "database": str(database),
    }
    validated = _run_worker(
        {**base_request, "command": "validate"}, public_key=fixture.public_key
    )
    fingerprint = _events(validated)[-1]["payload"]["catalog_fingerprint"]
    applied = _run_worker(
        {
            **base_request,
            "command": "apply",
            "expected_catalog_fingerprint": fingerprint,
        },
        public_key=fixture.public_key,
    )
    assert applied.returncode == 0, applied.stderr
    assert target.read_bytes() == fixture.published_content

    restored = _run_worker(
        {
            "protocol_version": 1,
            "command": "restore",
            "data_root": str(data_root),
            "database": str(database),
        }
    )

    restored_events = _events(restored)
    assert restored.returncode == 0, restored.stderr
    assert restored_events[-1]["event"] == "result"
    assert restored_events[-1]["payload"]["identifier"] == "fonte_teste"
    assert target.read_text(encoding="utf-8") == "versão anterior"
    assert not (data_root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING).exists()


def test_apply_preserves_pending_marker_and_refuses_mutation_after_interruption(
    tmp_path: Path,
) -> None:
    fixture = write_signed_release(tmp_path / "publicação")
    data_root = tmp_path / "dados"
    database = data_root / "car_microcredito.db"
    base_request = {
        "protocol_version": 1,
        "release_path": str(fixture.release),
        "data_root": str(data_root),
        "database": str(database),
    }
    validated = _run_worker(
        {**base_request, "command": "validate"}, public_key=fixture.public_key
    )
    fingerprint = _events(validated)[-1]["payload"]["catalog_fingerprint"]
    marker = data_root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING
    marker.parent.mkdir(parents=True)
    marker.write_text('{"state":"interrupted"}', encoding="utf-8")

    process = _run_worker(
        {
            **base_request,
            "command": "apply",
            "expected_catalog_fingerprint": fingerprint,
        },
        public_key=fixture.public_key,
    )

    assert process.returncode != 0
    assert "pendente de verificação" in str(_events(process)[-1]["message"])
    assert marker.is_file()
    assert not database.exists()
    assert not (data_root / fixture.target).exists()


def test_validate_refuses_mixed_statuses_while_interrupted_marker_exists(
    tmp_path: Path,
) -> None:
    fixture = write_signed_release(tmp_path / "publicação")
    data_root = tmp_path / "dados"
    database = data_root / "car_microcredito.db"
    marker = data_root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING
    marker.parent.mkdir(parents=True)
    marker.write_text('{"state":"interrupted"}', encoding="utf-8")

    process = _run_worker(
        {
            "protocol_version": 1,
            "command": "validate",
            "release_path": str(fixture.release),
            "data_root": str(data_root),
            "database": str(database),
        },
        public_key=fixture.public_key,
    )

    assert process.returncode != 0
    assert "pendente de verificação" in str(_events(process)[-1]["message"])
    assert marker.is_file()
    assert not database.exists()


def test_restore_failure_preserves_marker_for_explicit_recovery(tmp_path: Path) -> None:
    fixture = write_signed_release(tmp_path / "publicação")
    data_root = tmp_path / "dados"
    database = data_root / "car_microcredito.db"
    target = data_root / fixture.target
    target.parent.mkdir(parents=True)
    target.write_text("versão anterior", encoding="utf-8")
    base_request = {
        "protocol_version": 1,
        "release_path": str(fixture.release),
        "data_root": str(data_root),
        "database": str(database),
    }
    validated = _run_worker(
        {**base_request, "command": "validate"}, public_key=fixture.public_key
    )
    fingerprint = _events(validated)[-1]["payload"]["catalog_fingerprint"]
    applied = _run_worker(
        {
            **base_request,
            "command": "apply",
            "expected_catalog_fingerprint": fingerprint,
        },
        public_key=fixture.public_key,
    )
    assert applied.returncode == 0, applied.stderr
    backups = list((data_root / ".h").rglob("fonte_teste.txt"))
    assert len(backups) == 1
    backups[0].write_bytes(b"")

    restored = _run_worker(
        {
            "protocol_version": 1,
            "command": "restore",
            "data_root": str(data_root),
            "database": str(database),
        }
    )

    marker = data_root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING
    assert restored.returncode != 0
    assert "cópia anterior" in str(_events(restored)[-1]["message"])
    assert marker.is_file()
    assert target.read_bytes() == fixture.published_content


def test_request_above_public_limit_is_rejected_without_creating_database(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "dados"
    database = data_root / "car_microcredito.db"

    process = _run_worker(
        {
            "protocol_version": 1,
            "command": "validate",
            "release_path": str(tmp_path / "invalido.carbases"),
            "data_root": str(data_root),
            "database": str(database),
            "padding": "x" * (2 * 1024 * 1024),
        }
    )

    assert process.returncode != 0
    assert "acima do limite" in str(_events(process)[-1]["message"])
    assert not database.exists()


def test_apply_finishes_when_protocol_reader_disconnects(tmp_path: Path) -> None:
    fixture = write_signed_release(tmp_path / "publicação")
    data_root = tmp_path / "dados"
    database = data_root / "car_microcredito.db"
    request = {
        "protocol_version": 1,
        "command": "validate",
        "release_path": str(fixture.release),
        "data_root": str(data_root),
        "database": str(database),
    }
    validated = _run_worker(request, public_key=fixture.public_key)
    fingerprint = _events(validated)[-1]["payload"]["catalog_fingerprint"]
    command = [
        sys.executable,
        "-u",
        str(WORKER),
        "--public-key-file",
        str(fixture.public_key),
    ]

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ROOT,
    )
    assert process.stdout is not None
    assert json.loads(process.stdout.readline())["event"] == "started"
    process.stdout.close()
    assert process.stdin is not None
    process.stdin.write(
        json.dumps(
            {
                **request,
                "command": "apply",
                "expected_catalog_fingerprint": fingerprint,
            }
        ).encode()
    )
    process.stdin.close()

    returncode = process.wait(timeout=20)

    assert returncode == 0
    assert (data_root / fixture.target).read_bytes() == fixture.published_content
    assert database.is_file()
    assert not (data_root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING).exists()
