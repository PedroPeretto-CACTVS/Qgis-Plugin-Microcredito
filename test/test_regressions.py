import shutil
import sqlite3
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from cli.admin import main as cli_main
from database.schema import SCHEMA, configure_import, initialize
from database.session import connect
from plugin.batch import read_batch_xlsx
from qgis_plugin_microcredito.application.backup_service import (
    migrate_copy,
    snapshot_database,
)
from qgis_plugin_microcredito.application.geo_service import build_glebas_geojson
from qgis_plugin_microcredito.application.import_service import import_file
from qgis_plugin_microcredito.application.mte_service import HEADERS, import_mte
from qgis_plugin_microcredito.application.query_service import (
    find_by_document,
    find_mma_mcr_by_car,
)
from qgis_plugin_microcredito.domain.normalize import normalize_car
from qgis_plugin_microcredito.domain.policy import (
    CLEAR,
    INCONCLUSIVE,
    REVIEW,
    aggregate,
    compatible_operation,
    evaluate_lists,
    unique_operation,
)
from qgis_plugin_microcredito.infrastructure.downloads import (
    reconcile_features,
    validate_geopackage,
    validate_zip,
)

qgis_normalize_car = normalize_car


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(".test-data") / uuid4().hex
        self.root.mkdir(parents=True)
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        initialize(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.root)

    def file(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_missing_lists_never_clear(self):
        self.assertEqual(
            evaluate_lists([], [], {}, ["12345678901"]),
            {"mma_mcr": INCONCLUSIVE, "mte": INCONCLUSIVE},
        )

    def evidence(self):
        expiry = str(date.today() + timedelta(days=1))
        return {
            "mma_fonte": {"linhas_validas": 1, "sha256": "x", "validade_ate": expiry},
            "mte_fonte": {"total_registros": 1, "sha256": "y", "validade_ate": expiry},
        }

    def test_available_unmatched_lists_clear_only_their_stage(self):
        self.assertEqual(
            evaluate_lists([], [], self.evidence(), ["12345678901"]),
            {"mma_mcr": CLEAR, "mte": CLEAR},
        )
        self.assertEqual(aggregate([CLEAR, INCONCLUSIVE]), INCONCLUSIVE)

    def test_expired_and_unknown_values_inconclusive(self):
        evidence = self.evidence()
        evidence["mte_fonte"]["validade_ate"] = "2001-01-01"
        result = evaluate_lists(
            [{"status_imovel": "DESCONHECIDO", "dentro_criterio": "talvez"}],
            [],
            evidence,
            ["12345678901"],
        )
        self.assertEqual(set(result.values()), {INCONCLUSIVE})

    def test_occurrence_remains_visible_with_missing_other_source(self):
        evidence = self.evidence()
        result = evaluate_lists([{"status_imovel": "SU"}], [], evidence, [])
        self.assertEqual(aggregate(result.values()), REVIEW)
        self.assertEqual(result["mte"], INCONCLUSIVE)

    def test_wrong_car_and_ambiguous_operation_rejected(self):
        a = {"car_original": "MT-AAA", "ref_bacen": "1", "nu_ordem": "1"}
        self.assertFalse(compatible_operation(a, "MT-BBB"))
        with self.assertRaises(ValueError):
            unique_operation([a, {**a, "ref_bacen": "2"}], "MT-AAA")

    def test_old_mma_membership_disappears_on_replacement(self):
        first = self.file("a.csv", "CAR;STATUS_IMOVEL\nMT-AAA;SU\n")
        second = self.file("b.csv", "CAR;STATUS_IMOVEL\nMT-BBB;AT\n")
        import_file(self.db, "mma_mcr", first)
        import_file(self.db, "mma_mcr", second)
        self.assertEqual(find_mma_mcr_by_car(self.db, "MT-AAA"), [])
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM mma_mcr").fetchone()[0], 2
        )

    def test_bad_refresh_keeps_previous_active_edition(self):
        first = self.file("a.csv", "CAR;STATUS_IMOVEL\nMT-AAA;SU\n")
        bad = self.file("b.csv", "CAR;STATUS_IMOVEL\n-1;AT\n")
        import_file(self.db, "mma_mcr", first)
        with self.assertRaises(ValueError):
            import_file(self.db, "mma_mcr", bad)
        self.assertEqual(len(find_mma_mcr_by_car(self.db, "MT-AAA")), 1)

    def test_distinct_scopes_remain_active(self):
        for year in (2025, 2026):
            source = self.file(
                f"{year}.csv",
                f"REF_BACEN;CD_CNPJ_CPF;CD_CAR\n{year};12345678901;MT-{year}\n",
            )
            import_file(self.db, "propriedades", source, escopo=str(year))
        self.assertEqual(len(find_by_document(self.db, "12345678901")), 2)

    def test_incomplete_plot_does_not_become_complete(self):
        source = self.file(
            "p.csv",
            "REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA\n10;1;1;POLYGON ((1 1,2 1,2 2,1 1))\n10;1;2;POLYGON BROKEN\n",
        )
        import_file(self.db, "glebas", source)
        with self.assertRaises(ValueError):
            build_glebas_geojson(self.db, "10", "1")

    def test_overlapping_plot_editions_rejected(self):
        for scope, value in (("a", 1), ("b", 2)):
            source = self.file(
                f"{scope}.csv",
                f"REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA\n10;1;{value};POLYGON ((1 1,2 1,2 2,1 1))\n",
            )
            import_file(self.db, "glebas", source, escopo=scope)
        with self.assertRaises(ValueError):
            build_glebas_geojson(self.db, "10", "1")

    def test_mte_empty_bad_and_duplicate_do_not_erase_previous(self):
        header = ";".join(HEADERS) + "\n"
        row = "1;2026;MT;Teste;12345678901;Local;2;1;Procedente;2026-01-01\n"
        source = self.file("mte.csv", header + row)
        self.assertEqual(import_mte(self.db, source, validade_ate="2099-01-01"), 1)
        for text in (
            header,
            "INCOMPATIVEL\n",
            header + row + row,
            header + row.replace("12345678901", "123"),
        ):
            source.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                import_mte(self.db, source, validade_ate="2099-01-01")
            self.assertEqual(
                self.db.execute("SELECT COUNT(*) FROM trabalho_escravo").fetchone()[0],
                1,
            )

    def test_normalization_consistent(self):
        for value in ("-1", "0", "N/A", "", "MT-123.abc"):
            self.assertEqual(normalize_car(value), qgis_normalize_car(value))

    def test_readonly_rejects_writes_and_old_schema(self):
        path = self.root / "test.db"
        db = connect(path)
        initialize(db)
        db.close()
        db = connect(path, readonly=True)
        with self.assertRaises(sqlite3.OperationalError):
            db.execute("DELETE FROM importacao")
        db.close()
        old = self.root / "old.db"
        sqlite3.connect(old).close()
        with self.assertRaises(ValueError):
            connect(old, readonly=True)

    def test_snapshot_includes_uncheckpointed_wal(self):
        source = self.root / "wal.db"
        writer = sqlite3.connect(source)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE example(value)")
            writer.execute("INSERT INTO example VALUES ('confirmado')")
            writer.commit()
            destination = snapshot_database(source, self.root / "copy.db")
            reader = sqlite3.connect(destination)
            try:
                self.assertEqual(
                    reader.execute("SELECT value FROM example").fetchone()[0],
                    "confirmado",
                )
            finally:
                reader.close()
        finally:
            writer.close()

    def xlsx(self, cells):
        path = self.root / "query.xlsx"
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
        headers = [
            "CPF_CNPJ",
            "CAR",
            "PROPRIETARIO_POSSUIDOR",
            "REFERENCIA_INTERNA",
            "OBSERVACAO",
        ]
        first = "".join(
            f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{value}</t></is></c>'
            for i, value in enumerate(headers)
        )
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(
                "xl/workbook.xml",
                f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Notas" sheetId="1" r:id="r1"/><sheet name="Consultas" sheetId="2" r:id="r2"/></sheets></workbook>',
            )
            z.writestr(
                "xl/_rels/workbook.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>',
            )
            z.writestr(
                "xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData/></worksheet>"
            )
            z.writestr(
                "xl/worksheets/sheet2.xml",
                f'<worksheet {ns}><sheetData><row r="1">{first}</row><row r="8">{cells}</row></sheetData></worksheet>',
            )
        return path

    def test_sheet_name_and_physical_row_preserved(self):
        path = self.xlsx('<c r="A8" t="inlineStr"><is><t>01234567890</t></is></c>')
        row = read_batch_xlsx(path)[0]
        self.assertEqual((row.source_row, row.document), (8, "01234567890"))

    def test_scientific_document_rejected(self):
        path = self.xlsx('<c r="A8"><v>1.2345678901E+10</v></c>')
        with self.assertRaisesRegex(ValueError, "linha 8"):
            read_batch_xlsx(path)

    def test_truncated_and_duplicate_downloads_rejected(self):
        with self.assertRaises(ValueError):
            reconcile_features([1, 2], [{"id": 1}], "OBJECTID")
        with self.assertRaises(ValueError):
            reconcile_features([1, 2], [{"id": 1}, {"id": 1}], "OBJECTID")
        self.assertEqual(
            len(reconcile_features([1], [{"properties": {"OBJECTID": 1}}], "OBJECTID")),
            1,
        )

    def test_html_is_not_a_zip_and_sqlite_is_not_geopackage(self):
        html = self.file("not.zip", "<html>erro</html>")
        with self.assertRaises(zipfile.BadZipFile):
            validate_zip(html)
        fake = self.root / "fake.gpkg"
        sqlite3.connect(fake).close()
        with self.assertRaises(sqlite3.Error):
            validate_geopackage(fake)

    def test_migration_preserves_source_and_requires_activation(self):

        source = self.root / "legacy.db"
        old = sqlite3.connect(source)
        old.executescript(SCHEMA)
        old.execute(
            "INSERT INTO importacao(id,tipo,arquivo,sha256,total_linhas,linhas_validas) VALUES (1,'propriedades','origem','abc',1,1)"
        )
        old.execute(
            "INSERT INTO sicor_propriedade(importacao_id,ref_bacen,car_normalizado,documento_normalizado) VALUES (1,'1','MTABC','12345678901')"
        )
        old.commit()
        old.close()
        before = source.read_bytes()
        migrated = migrate_copy(source, self.root / "migrated.db")
        self.assertEqual(source.read_bytes(), before)
        db = connect(migrated)
        try:
            self.assertEqual(find_by_document(db, "12345678901"), [])
            configure_import(db, 1, "2026-nacional")
            self.assertEqual(len(find_by_document(db, "12345678901")), 1)
        finally:
            db.close()

    def test_sicor_command_rolls_back_whole_set(self):
        borrowers = self.file("borrow.csv", "REF_BACEN;CD_CPF_CNPJ\n1;12345678901\n")
        properties = self.file("wrong.csv", "OUTRO;CD_CAR\n1;MT-ABC\n")
        target = self.root / "transaction.db"
        result = cli_main(
            [
                "--db",
                str(target),
                "import-sicor",
                "--mutuarios",
                str(borrowers),
                "--propriedades",
                str(properties),
                "--escopo",
                "2026-nacional",
            ]
        )
        self.assertEqual(result, 2)
        db = connect(target, readonly=True)
        try:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM importacao").fetchone()[0], 0
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sicor_mutuario").fetchone()[0], 0
            )
        finally:
            db.close()

    def test_bulk_insert_crosses_chunk_boundary_without_losing_rows(self):
        source = self.file(
            "many.csv",
            "REF_BACEN;CD_CPF_CNPJ\n"
            + "".join(f"{n};12345678901\n" for n in range(2105)),
        )
        result = import_file(self.db, "mutuarios", source)
        self.assertEqual(result.validas, 2105)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM sicor_mutuario").fetchone()[0], 2105
        )


if __name__ == "__main__":
    unittest.main()
