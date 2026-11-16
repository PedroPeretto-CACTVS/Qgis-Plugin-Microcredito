from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_smoke(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, "-s", "-B", str(ROOT / "tools" / script), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize(
    "script",
    (
        "qgis_base_release_smoke.py",
        "qgis_external_update_smoke.py",
        "qgis_fixed_root_workflow_smoke.py",
    ),
)
def test_smoke_requires_an_explicit_output_root_before_runtime_start(
    script: str,
) -> None:
    result = run_smoke(script)

    assert result.returncode == 2, result.stderr
    assert "--output-root" in result.stderr


@pytest.mark.parametrize("selection", ("escape", "existing", "source-tree"))
def test_smoke_refuses_unsafe_or_preexisting_output_before_runtime_start(
    tmp_path: Path, selection: str
) -> None:
    output = tmp_path / "evidence"
    run_id = "attempt"
    if selection == "escape":
        run_id = "../escaped"
        expected = "unsafe_run_id"
    elif selection == "existing":
        run = output / run_id
        run.mkdir(parents=True)
        (run / "keep.txt").write_text("previous evidence", encoding="utf-8")
        expected = "fresh_run_directory_required"
    else:
        output = ROOT / "smoke-output-must-not-be-created"
        expected = "output_inside_source_tree"

    result = run_smoke(
        "qgis_base_release_smoke.py",
        "--output-root",
        str(output),
        "--run-id",
        run_id,
    )

    assert result.returncode == 2, result.stderr
    assert expected in result.stderr
    if selection == "existing":
        assert (output / run_id / "keep.txt").read_text() == "previous evidence"
    else:
        assert not output.exists()
    assert not (tmp_path / "escaped").exists()
