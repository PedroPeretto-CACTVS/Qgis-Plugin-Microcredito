"""Opening the analysis should not load the same cadastral file twice."""

from __future__ import annotations

from pathlib import Path
from time import sleep

import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

from qgis.PyQt.QtWidgets import QDialog, QTableWidget
from test_pre_analysis_window import analysis_window as analysis_window
from test_pre_analysis_window import button_named, interact_with_pre_analysis

from plugin import car_source, plugin
from qgis_plugin_microcredito.application.local_data_paths import (
    default_local_data_paths,
)


def test_first_open_reuses_exported_cadastral_attributes_with_slow_storage(
    analysis_window: plugin.SearchWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_layer = car_source.QgsVectorLayer
    cadastral = default_local_data_paths().car / "MT_perimetros.geojson"

    def slow_provider(source, *args, **kwargs):
        # Simulate storage latency at the external OGR/QGIS provider boundary.
        if Path(source) == cadastral:
            sleep(0.75)
        return original_layer(source, *args, **kwargs)

    monkeypatch.setattr(car_source, "QgsVectorLayer", slow_provider)

    def read_fiscal_rule(dialog: QDialog) -> None:
        table = dialog.findChild(QTableWidget, "preAnalysisTable")
        rows = [
            row
            for row in range(table.rowCount())
            if table.item(row, 0).text() == "Limite territorial da agricultura familiar"
        ]
        assert len(rows) == 1
        # Fixture area 123 ha / official municipal module 80 ha = 1.5375 modules.
        assert "1.5375 módulo(s)" in table.item(rows[0], 2).text()
        button_named(dialog, "Fechar sem alterar").click()

    elapsed = interact_with_pre_analysis(analysis_window, read_fiscal_rule)
    assert 0.75 <= elapsed < 1.4, elapsed


def test_null_cadastral_area_keeps_the_mma_fallback_in_the_pre_analysis(
    analysis_window: plugin.SearchWindow,
) -> None:
    import json
    from datetime import date, timedelta

    from test_pre_analysis_window import CAR

    from database.session import connect

    paths = default_local_data_paths()
    cadastral = paths.car / "MT_perimetros.geojson"
    payload = json.loads(cadastral.read_text("utf-8"))
    payload["features"][0]["properties"]["num_area"] = None
    cadastral.write_text(json.dumps(payload), encoding="utf-8")
    connection = connect(paths.database)
    connection.execute(
        "INSERT INTO importacao "
        "(id,tipo,arquivo,sha256,total_linhas,linhas_validas,escopo,ativo,validade_ate) "
        "VALUES (1,'mma_mcr','synthetic.csv',?,1,1,'nacional',1,?)",
        ("a" * 64, (date.today() + timedelta(days=10)).isoformat()),
    )
    connection.execute(
        "INSERT INTO mma_mcr (importacao_id,car_original,car_normalizado,area_total_ha) "
        "VALUES (1,?,?, '123')",
        (CAR, CAR.replace("-", "")),
    )
    connection.commit()
    connection.close()

    def read_fiscal_rule(dialog: QDialog) -> None:
        table = dialog.findChild(QTableWidget, "preAnalysisTable")
        row = next(
            row
            for row in range(table.rowCount())
            if table.item(row, 0).text() == "Limite territorial da agricultura familiar"
        )
        assert "1.5375 módulo(s)" in table.item(row, 2).text()
        button_named(dialog, "Fechar sem alterar").click()

    interact_with_pre_analysis(analysis_window, read_fiscal_rule)
