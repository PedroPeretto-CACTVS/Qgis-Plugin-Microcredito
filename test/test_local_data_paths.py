from pathlib import Path

import pytest

from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)


def test_windows_bases_have_one_location_independent_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.chdir(tmp_path)
    paths = default_local_data_paths()
    expected = tmp_path / "Local" / "Cactvs" / "BasesPlugin"
    assert paths.root == expected
    assert paths.database == expected / "car_microcredito.db"
    assert paths.car == expected / "car"
    assert paths.environmental == expected / "ambientais"
    assert not expected.exists()
