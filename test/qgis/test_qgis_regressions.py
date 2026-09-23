import pytest

pytest.importorskip("qgis.core")
pytestmark = pytest.mark.qgis

import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtWidgets import QMessageBox

from database.schema import initialize
from database.session import connect
from plugin import batch_window, car_document_window, plugin
from plugin.analysis import (
    AnalysisCancelled,
    EnvironmentalAnalyzer,
    EnvironmentalSource,
    analyze_layer,
)
from plugin.evidence import collect_database_evidence
from plugin.report import (
    _format_area_ha,
    _visible_map_entries,
    write_batch_report,
    write_report,
)
from plugin.worker import EnvironmentalWorker
from qgis_plugin_microcredito.application.import_service import import_file


class Iface:
    @staticmethod
    def mainWindow():
        return None


TEST_DIRECTORIES = []


class QgisRegressionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(".test-data") / uuid4().hex
        self.root.mkdir(parents=True)
        TEST_DIRECTORIES.append(self.root.resolve())

    def tearDown(self):
        pass  # O pool OGR pode manter arquivos abertos até QgsApplication.exitQgis.

    def layer(self, polygons, crs="EPSG:3857"):
        layer = QgsVectorLayer(f"Polygon?crs={crs}", "test", "memory")
        for wkt in polygons:
            feature = QgsFeature()
            if wkt:
                feature.setGeometry(QgsGeometry.fromWkt(wkt))
            layer.dataProvider().addFeatures([feature])
        layer.updateExtents()
        return layer

    def source(self, path=None):
        return EnvironmentalSource(
            "teste",
            "Fonte de teste",
            path or self.root / "test.gpkg",
            "https://example.test/base",
        )

    def geojson(self, path, null=False):
        feature = {
            "type": "Feature",
            "properties": {},
            "geometry": None
            if null
            else {
                "type": "Polygon",
                "coordinates": [
                    [[-50, -10], [-49.99, -10], [-49.99, -10.01], [-50, -10]]
                ],
            },
        }
        path.write_text(
            json.dumps({"type": "FeatureCollection", "features": [feature]}),
            encoding="utf-8",
        )
        return path

    def test_unique_area_counts_overlap_once(self):
        wkt = "POLYGON ((0 0,100 0,100 100,0 100,0 0))"
        target, layer = self.layer([wkt]), self.layer([wkt, wkt])
        result = analyze_layer(target, self.source(), layer)
        self.assertEqual(result["quantidade"], 2, result)
        self.assertAlmostEqual(
            result["soma_areas_ocorrencias_ha"],
            2 * result["area_sobreposta_ha"],
            delta=0.0002,
        )

    def test_invalid_or_missing_target_part_is_inconclusive(self):
        valid = "POLYGON ((0 0,10 0,10 10,0 0))"
        for extra in (None, "POLYGON ((0 0,10 10,0 10,10 0,0 0))"):
            result = analyze_layer(
                self.layer([valid, extra]), self.source(), self.layer([valid])
            )
            self.assertEqual(result["resultado"], "inconclusivo")

    def test_repairable_candidate_source_is_repaired_and_reported(self):
        target = self.layer(["POLYGON ((0 0,20 0,20 20,0 20,0 0))"])
        result = analyze_layer(
            target, self.source(), self.layer(["POLYGON ((0 0,10 10,0 10,10 0,0 0))"])
        )
        self.assertEqual(result["resultado"], "ocorrencia_para_analise", result)
        self.assertEqual(len(result["geometrias_reparadas"]), 1)

    def test_unrepairable_candidate_source_is_inconclusive(self):
        target = self.layer(["POLYGON ((0 0,20 0,20 20,0 20,0 0))"])
        result = analyze_layer(
            target, self.source(), self.layer(["POLYGON ((1 1,1 1,1 1,1 1))"])
        )
        self.assertEqual(result["resultado"], "inconclusivo")

    def test_null_source_feature_is_not_reported_clear(self):
        source_path = self.geojson(self.root / "null.geojson", null=True)
        target = self.geojson(self.root / "target.geojson")
        result = EnvironmentalAnalyzer([self.source(source_path)]).analyze(target)
        self.assertEqual(result["resultado_geral"], "inconclusivo")

    def test_boundary_contact_is_not_area_overlap(self):
        target = self.layer(["POLYGON ((0 0,10 0,10 10,0 10,0 0))"])
        layer = self.layer(["POLYGON ((10 0,20 0,20 10,10 10,10 0))"])
        result = analyze_layer(target, self.source(), layer)
        self.assertEqual(result["area_sobreposta_ha"], 0)
        self.assertEqual(len(result["contatos_borda"]), 1)

    def test_map_focus_transforms_car_extent_to_canvas_crs(self):
        target = self.layer(
            ["POLYGON ((-50 -10,-49.99 -10,-49.99 -10.01,-50 -10.01,-50 -10))"],
            "EPSG:4326",
        )
        canvas = QgsMapCanvas()
        canvas.resize(800, 600)
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        extent = plugin.focused_extent(
            target,
            canvas.mapSettings().destinationCrs(),
            QgsProject.instance().transformContext(),
        )
        canvas.setExtent(extent)
        self.assertGreater(extent.width(), 1000)
        self.assertLess(extent.width(), 2000)
        self.assertLess(extent.xMinimum(), -5_000_000)
        self.assertAlmostEqual(
            canvas.extent().center().x(), extent.center().x(), delta=1
        )
        canvas.deleteLater()

    def test_worker_returns_same_result_and_closes(self):
        target = self.geojson(self.root / "target.geojson")
        source_path = self.geojson(self.root / "source.geojson")
        sources = [self.source(source_path)]
        expected = EnvironmentalAnalyzer(sources).analyze(target)
        worker = EnvironmentalWorker(sources)
        try:
            self.assertEqual(worker.analyze(target), expected)
            self.assertEqual(worker.analyze(target), expected)
        finally:
            worker.close()
        self.assertFalse(worker.isRunning())

    def analysis(self):
        return {
            "car": "MT-TESTE",
            "ambiental": {
                "resultado_geral": "sem_ocorrencia_identificada",
                "camadas": [],
            },
            "documentos_consultados_mte": ["12345678901"],
            "documentos_proprietario_possuidor": ["12345678901"],
            "operacao": {"arquivo": str(self.root.resolve())},
            "documentos_associados": [{"arquivo": str(self.root.resolve())}],
            "evidencia_geometria": {
                "arquivo": str(self.root.resolve()),
                "sha256": "abcd",
            },
            "importacoes_sicor_mma": [
                {
                    "arquivo": str(self.root.resolve()),
                    "sha256": "efgh",
                    "tipo": "glebas",
                }
            ],
        }

    def test_mte_documents_include_initial_search_and_owner_without_duplicates(self):
        associated = [{"documento_normalizado": "12345678901"}]
        self.assertEqual(
            plugin.documents_for_mte(
                associated, "123.456.789-01", "98.765.432/0001-10", "inválido"
            ),
            ["12345678901", "98765432000110"],
        )

    def test_car_document_lookup_displays_complete_documents(self):
        window = car_document_window.CarDocumentWindow(Iface(), plugin._load_core)
        window.results = [
            {
                "documento_normalizado": "12345678901",
                "tipo_vinculo": "documento_na_propriedade",
            },
            {
                "documento_normalizado": "11222333000144",
                "tipo_vinculo": "mutuario_da_operacao",
            },
        ]
        window._fill_table()
        self.assertEqual(window.table.item(0, 1).text(), "123.456.789-01")
        self.assertEqual(window.table.item(1, 1).text(), "11.222.333/0001-44")
        window.close()

    def test_map_legend_uses_unique_intersection_area_from_analysis(self):
        analysis = {
            "mapa_legenda": [
                {
                    "code": "embargos",
                    "label": "Embargos ambientais",
                    "color": "#D41159",
                },
                {
                    "code": "desmatamento_pos_2020",
                    "label": "PRODES",
                    "color": "#FF7A00",
                },
            ],
            "ambiental": {
                "area_car_ha": 10.0,
                "camadas": [
                    {
                        "codigo": "embargos",
                        "fonte": "Embargos ambientais",
                        "area_sobreposta_ha": 0,
                    },
                    {
                        "codigo": "desmatamento_pos_2020",
                        "fonte": "PRODES",
                        "area_sobreposta_ha": 1.655,
                    },
                ],
            },
        }
        entries = _visible_map_entries(analysis)
        self.assertEqual(entries[0]["area_sobreposta_ha"], 0)
        self.assertEqual(entries[1]["area_sobreposta_ha"], 1.655)
        self.assertEqual(_format_area_ha(entries[1]["area_sobreposta_ha"]), "1,655 ha")

    def test_overlap_percentage_uses_total_car_area_and_handles_invalid_area(self):
        from plugin.report import _format_percentage, _overlap_percentage

        self.assertAlmostEqual(_overlap_percentage(1.655, 10), 16.55)
        self.assertEqual(_format_percentage(_overlap_percentage(1.655, 10)), "16,55%")
        self.assertEqual(_format_percentage(_overlap_percentage(1, 0)), "Não informado")

    def test_legacy_mte_rows_are_described_as_consulted_but_not_homologated(self):
        database = self.root / "mte_legado.db"
        connection = connect(database)
        initialize(connection)
        connection.execute(
            """INSERT INTO trabalho_escravo
               (identificador_fonte, documento_original, documento_normalizado,
                empregador, fonte_url, arquivo_fonte)
               VALUES ('1', '12345678901', '12345678901', 'Teste',
                       'https://mte.example/lista.csv', 'lista.csv')"""
        )
        connection.commit()
        evidence = collect_database_evidence(connection)
        connection.close()
        self.assertEqual(evidence["mte_fonte"]["total_registros"], 1)
        self.assertEqual(
            evidence["mte_fonte"]["fonte_url"], "https://mte.example/lista.csv"
        )
        self.assertIn("validade administrativa", evidence["mte_fonte"]["problema"])

    def test_report_missing_sources_inconclusive_and_previous_preserved(self):
        private_geometry = self.root / "internal.geojson"
        private_geometry.write_text(
            '{"properties":{"ref_bacen":"RESERVADO"}}', encoding="utf-8"
        )
        analysis = {
            **self.analysis(),
            "geometria_empreendimento": str(private_geometry),
        }
        first, audit = write_report(analysis, self.root / "same.pdf")
        self.assertFalse(list(first.parent.glob("*.geojson")))
        self.assertTrue(private_geometry.is_file())
        original = first.read_bytes()
        second, _ = write_report(self.analysis(), self.root / "same.pdf")
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        payload = json.loads(audit.read_text(encoding="utf-8"))
        self.assertEqual(payload["resultado_geral"], "inconclusivo")
        self.assertEqual(payload["geometria_sha256"], "abcd")
        self.assertNotIn(str(self.root.resolve()), audit.read_text(encoding="utf-8"))
        self.assertTrue(first.parent.name.startswith("analise_"))
        self.assertFalse(
            any(path.name.startswith(".r_") for path in self.root.iterdir())
        )

    def test_report_refuses_missing_owner_document(self):
        analysis = {
            **self.analysis(),
            "documentos_proprietario_possuidor": [],
        }
        with self.assertRaisesRegex(ValueError, "proprietário/possuidor"):
            write_report(analysis, self.root / "missing-owner.pdf")
        self.assertFalse((self.root / "missing-owner.pdf").exists())

    def test_report_paginates_large_mte_document_list_and_preserves_full_json(self):
        documents = [f"{number:011d}" for number in range(785)]
        analysis = {**self.analysis(), "documentos_consultados_mte": documents}
        pdf, audit = write_report(analysis, self.root / "many_documents.pdf")
        self.assertTrue(pdf.is_file())
        payload = json.loads(audit.read_text(encoding="utf-8"))
        self.assertEqual(payload["documentos_consultados_mte"], documents)

    def test_failed_pdf_does_not_publish_partial_bundle(self):
        before = set(self.root.iterdir())
        with patch(
            "plugin.report._document", side_effect=RuntimeError("falha simulada")
        ):
            with self.assertRaises(RuntimeError):
                write_report(self.analysis(), self.root / "broken.pdf")
        self.assertEqual(set(self.root.iterdir()), before)

    def test_all_failed_batch_still_publishes_audit(self):
        failures = [
            {
                "linha": 2,
                "documento": "12345678901",
                "car": "MT-TESTE",
                "erro": "Sem polígono",
            }
        ]
        pdf, audit = write_batch_report(
            [], self.root / "failures.pdf", failures, {"estado": "concluido_com_falhas"}
        )
        self.assertTrue(pdf.is_file())
        payload = json.loads(audit.read_text(encoding="utf-8"))
        self.assertEqual(payload["falhas"], failures)
        self.assertEqual(payload["quantidade_analises"], 0)

    def test_stale_selected_operation_never_supplies_other_car_geometry(self):
        database = self.root / "dados" / "test.db"
        connection = connect(database)
        initialize(connection)
        source = self.root / "properties.csv"
        source.write_text(
            "REF_BACEN;NU_ORDEM;CD_CAR\n1;1;MT-AAA\n2;1;MT-BBB\n", encoding="utf-8"
        )
        import_file(connection, "propriedades", source)
        connection.close()
        window = plugin.SearchWindow(Iface())
        window.db_path.setText(str(database))
        window.results = [
            {
                "car_original": "MT-AAA",
                "car_normalizado": "MTAAA",
                "ref_bacen": "1",
                "nu_ordem": "1",
            }
        ]
        window._fill_table()
        window.table.selectRow(0)
        window.car.setText("MT-BBB")
        window.owner_document.setText("12345678901")
        functions = list(plugin._load_core())
        calls = []
        functions[3] = lambda connection, ref, order: (
            calls.append(ref) or {"features": []}
        )
        with (
            patch.object(plugin, "_load_core", return_value=tuple(functions)),
            patch.object(window, "_car_geometry", return_value=None),
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "critical") as error,
        ):
            window.analyze_selected("interferences")
        self.assertFalse(error.called, error.call_args)
        self.assertEqual(calls, ["2"])
        window.close()

    def write_sheet(self, path, cars):
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        headers = [
            "CPF_CNPJ",
            "CAR",
            "PROPRIETARIO_POSSUIDOR",
            "FONTE_RECURSOS",
            "LINHA_CREDITO",
            "REFERENCIA_INTERNA",
            "OBSERVACAO",
        ]
        rows = [headers] + [
            ["12345678901", car, "", "AUTO", "Pronaf B", "", ""] for car in cars
        ]
        xml_rows = []
        for number, values in enumerate(rows, 1):
            cells = "".join(
                f'<c r="{chr(65 + i)}{number}" t="inlineStr"><is><t>{v}</t></is></c>'
                for i, v in enumerate(values)
            )
            xml_rows.append(f'<row r="{number}">{cells}</row>')
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                "xl/workbook.xml",
                f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Consultas" sheetId="1" r:id="r1"/></sheets></workbook>',
            )
            z.writestr(
                "xl/_rels/workbook.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
            )
            z.writestr(
                "xl/worksheets/sheet1.xml",
                f"<worksheet {ns}><sheetData>{''.join(xml_rows)}</sheetData></worksheet>",
            )
        return path

    def batch(self):
        database = self.root / "dados" / "test.db"
        db = connect(database)
        initialize(db)
        db.close()
        car_dir = self.root / "car"
        car_dir.mkdir()
        window = batch_window.BatchWindow(Iface(), plugin._load_core)
        window.db_path.setText(str(database))
        window.car_base_path.setText(str(car_dir))
        window.output_path.setText(str(self.root / "out"))
        window.include_maps.setChecked(False)
        return window

    def test_batch_clear_query_preserves_configured_directories(self):
        window = self.batch()
        database = window.db_path.text()
        car_base = window.car_base_path.text()
        output = window.output_path.text()
        window.xlsx_path.setText(
            str(self.write_sheet(self.root / "batch.xlsx", ["MT-AAA"]))
        )
        self.assertTrue(window.validate_spreadsheet())
        window.tasks = [{"car": "MT-AAA"}]
        window.progress.setValue(70)

        window._clear_query()

        self.assertEqual(window.xlsx_path.text(), "")
        self.assertEqual(
            (window.rows, window.tasks, window.table.rowCount()), ([], [], 0)
        )
        self.assertEqual(window.progress.value(), 0)
        self.assertEqual(
            (
                window.db_path.text(),
                window.car_base_path.text(),
                window.output_path.text(),
            ),
            (database, car_base, output),
        )
        self.assertIn("Consulta limpa", window.status.text())
        window.close()

    def test_batch_rejects_unwritable_report_destination_with_clear_message(self):
        window = self.batch()
        blocked = self.root / "arquivo_em_vez_de_pasta"
        blocked.write_text("bloqueado", encoding="utf-8")
        with self.assertRaisesRegex(PermissionError, "Pasta dos relatórios"):
            window._prepare_output_directory(blocked)
        window.close()

    def test_environmental_analysis_honors_cancellation(self):
        with self.assertRaisesRegex(AnalysisCancelled, "cancelado pelo usuário"):
            EnvironmentalAnalyzer([]).analyze(
                self.root / "inexistente.geojson", cancel_check=lambda: True
            )

    def test_batch_revalidates_selected_spreadsheet(self):
        window = self.batch()
        first = self.write_sheet(self.root / "first.xlsx", ["MT-AAA"])
        second = self.write_sheet(self.root / "second.xlsx", ["MT-BBB"])
        window.xlsx_path.setText(str(first))
        self.assertTrue(window.validate_spreadsheet())
        window.xlsx_path.setText(str(second))
        with (
            patch.object(
                window, "_build_analysis", side_effect=ValueError("Sem polígono")
            ),
            patch.object(
                batch_window,
                "write_batch_report",
                return_value=(self.root / "x.pdf", self.root / "x.json"),
            ) as writer,
            patch.object(
                window, "_choose_final_output", side_effect=lambda current: current
            ),
            patch.object(batch_window.QDesktopServices, "openUrl", return_value=True),
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "critical") as error,
        ):
            window.process_batch()
        self.assertFalse(error.called, error.call_args)
        self.assertEqual(window.rows[0].car, "MT-BBB")
        self.assertEqual(writer.call_args.args[2][0]["car"], "MT-BBB")
        self.assertEqual(writer.call_args.args[3]["falhas"], 1)
        window.close()

    def test_cancelled_batch_accounts_for_remaining_tasks(self):
        window = self.batch()
        window.xlsx_path.setText(
            str(
                self.write_sheet(
                    self.root / "batch.xlsx", ["MT-AAA", "MT-BBB", "MT-CCC"]
                )
            )
        )

        def build(*args):
            window._request_cancel()
            return {
                **self.analysis(),
                "documento_lote": "12345678901",
                "car": "MT-AAA",
                "resultado_geral": "inconclusivo",
            }

        with (
            patch.object(window, "_build_analysis", side_effect=build),
            patch.object(
                batch_window,
                "write_batch_report",
                return_value=(self.root / "x.pdf", self.root / "x.json"),
            ) as writer,
            patch.object(
                window, "_choose_final_output", side_effect=lambda current: current
            ),
            patch.object(batch_window.QDesktopServices, "openUrl", return_value=True),
            patch.object(QMessageBox, "information"),
            patch.object(QMessageBox, "critical") as error,
        ):
            window.process_batch()
        self.assertFalse(error.called, error.call_args)
        summary = writer.call_args.args[3]
        self.assertEqual(
            (summary["analisados"], summary["cancelados"], summary["estado"]),
            (1, 2, "cancelado"),
        )
        window.close()


if __name__ == "__main__":
    unittest.main()
