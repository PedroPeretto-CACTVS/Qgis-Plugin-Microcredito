"""Consultations keep one coherent base edition throughout an operation."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from qgis_plugin_microcredito.infrastructure.base_access import (
    BaseAccessBusy,
    read_base_access,
)
from qgis_plugin_microcredito.infrastructure.updates import UpdateError


def _can_update_in_other_process(root: Path) -> bool:
    code = """
import sys
from qgis_plugin_microcredito.infrastructure.updates import UpdateError, ensure_not_updating
try:
    ensure_not_updating(sys.argv[1])
except UpdateError:
    sys.exit(23)
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", code, str(root)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode in {0, 23}, result.stderr
    return result.returncode == 0


def test_consultation_excludes_updates_until_operation_finishes(tmp_path: Path) -> None:
    with read_base_access(tmp_path):
        assert not _can_update_in_other_process(tmp_path)

    assert _can_update_in_other_process(tmp_path)


def test_interrupted_update_blocks_consultation_even_without_live_process(
    tmp_path: Path,
) -> None:
    marker = tmp_path / ".atualizacoes" / "external-update-pending.json"
    marker.parent.mkdir()
    marker.write_text('{"job_id": "interrompido"}', encoding="utf-8")

    with pytest.raises(UpdateError, match="verificação"):
        with read_base_access(tmp_path):
            pytest.fail(
                "Uma publicação de estado desconhecido não pode ser consultada."
            )

    assert marker.is_file()


def test_nested_consultation_keeps_outer_lease_until_error_unwinds(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="consulta interrompida"):
        with read_base_access(tmp_path):
            with read_base_access(tmp_path / "."):
                assert not _can_update_in_other_process(tmp_path)
            assert not _can_update_in_other_process(tmp_path)
            raise ValueError("consulta interrompida")

    assert _can_update_in_other_process(tmp_path)


def test_missing_bases_are_not_created_by_consultation_guard(tmp_path: Path) -> None:
    absent_root = tmp_path / "nao-instalado"

    with pytest.raises(UpdateError, match="ainda não foram instaladas"):
        with read_base_access(absent_root):
            pytest.fail("Não pode iniciar leitura sem uma instalação existente.")

    assert not absent_root.exists()


def test_other_thread_cannot_reenter_an_existing_read_lease(tmp_path: Path) -> None:
    def consult() -> None:
        with read_base_access(tmp_path):
            pytest.fail("Outra thread não pode herdar uma operação ativa.")

    with ThreadPoolExecutor(max_workers=1) as executor:
        with read_base_access(tmp_path):
            with pytest.raises(BaseAccessBusy, match="Aguarde"):
                executor.submit(consult).result(timeout=10)
