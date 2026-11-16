from __future__ import annotations

import json
import zipfile
from pathlib import Path

from update_process_support import TEST_PUBLIC_KEY_PEM


def test_publisher_cli_builds_copy_release_without_a_new_signature(
    tmp_path: Path,
) -> None:
    from datetime import datetime

    from typer.testing import CliRunner

    from installer.cli import app
    from installer.prebuilt_bases import prepare_prebuilt_bases
    from prebuilt_support import write_complete_release

    source = write_complete_release(tmp_path / "source")
    candidate = tmp_path / "candidate"
    manifest = prepare_prebuilt_bases(source.release, candidate, TEST_PUBLIC_KEY_PEM)
    day = datetime.fromisoformat(
        json.loads(manifest.read_text())["prepared_at"]
    ).strftime("%d-%m-%Y")
    output = tmp_path / f"bases-plugin-{day}.carbases"
    result = CliRunner().invoke(
        app,
        [
            "prebuilt-release",
            "--candidate",
            str(candidate),
            "--output",
            str(output),
            "--public-key",
            str(source.public_key),
        ],
    )

    assert result.exit_code == 0, result.output
    with zipfile.ZipFile(output) as archive:
        assert json.loads(archive.read("prebuilt.json"))["verification"] == "integrity"
        assert "prebuilt.json.sig" not in archive.namelist()
