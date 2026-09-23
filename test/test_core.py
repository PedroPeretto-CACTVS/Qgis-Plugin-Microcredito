from __future__ import annotations

import gzip
import re
import shutil
import sqlite3
import unittest
import uuid
import zipfile
from pathlib import Path

from database.schema import initialize
from plugin.batch import MAIN_HEADERS, read_xlsx_rows
from qgis_plugin_microcredito.application.geo_service import build_glebas_geojson
from qgis_plugin_microcredito.application.import_service import import_file
from qgis_plugin_microcredito.application.owner_documents import (
    require_owner_documents,
    validate_report_owner_documents,
)
from qgis_plugin_microcredito.application.query_service import (
    find_by_car,
    find_by_document,
    find_documents_by_car,
    find_mma_mcr_by_car,
    find_operation_context,
    find_slave_labor_by_documents,
)
from qgis_plugin_microcredito.domain.normalize import (
    format_document,
    mask_document,
    normalize_car,
    normalize_document,
)


class CoreTests(unittest.TestCase):
    def test_batch_template_has_required_headers(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "plugin"
            / "modelo_consulta_lote.xlsx"
        )
        rows = read_xlsx_rows(template)
        self.assertEqual(tuple(rows[0]), MAIN_HEADERS)
        with zipfile.ZipFile(template) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertEqual(len(re.findall(r"<(?:x:)?dataValidation(?:\s|>)", sheet)), 2)
        self.assertIn('sqref="D2:D500"', sheet)
        self.assertIn('sqref="E2:E500"', sheet)

    def setUp(self):
        self.root = Path(".test-data") / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        initialize(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.root)

    def _gz(self, name: str, content: str) -> Path:
        path = self.root / name
        with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
            stream.write(content)
        return path

    def test_normalization(self):
        self.assertEqual(normalize_document("123.456.789-01"), "12345678901")
        self.assertEqual(normalize_document("123"), "")
        self.assertEqual(normalize_car("MT-123.abc"), "MT123ABC")
        self.assertEqual(normalize_car("-1"), "")
        self.assertEqual(mask_document("123.456.789-01"), "***.***.***-01")
        self.assertEqual(format_document("123.456.789-01"), "123.456.789-01")
        self.assertEqual(format_document("11.222.333/0001-44"), "11.222.333/0001-44")

    def test_owner_document_gate_rejects_borrower_only(self):
        links = [
            {
                "documento_normalizado": "12345678901",
                "tipo_vinculo": "mutuario_da_operacao",
            }
        ]
        with self.assertRaisesRegex(ValueError, "proprietário/possuidor"):
            require_owner_documents(links)

    def test_owner_document_gate_accepts_direct_property_and_manual_documents(self):
        links = [
            {
                "documento_normalizado": "12345678901",
                "tipo_vinculo": "documento_na_propriedade",
            },
            {
                "documento_normalizado": "12345678901",
                "tipo_vinculo": "mutuario_da_operacao",
            },
            {
                "documento_normalizado": "11222333000144",
                "tipo_vinculo": "proprietario_possuidor_informado_manualmente",
            },
        ]
        self.assertEqual(
            require_owner_documents(links),
            ["12345678901", "11222333000144"],
        )
        self.assertEqual(
            validate_report_owner_documents(["123.456.789-01", "12345678901"]),
            ["12345678901"],
        )

    def test_report_owner_gate_rejects_missing_or_incomplete_documents(self):
        for values in ([], [""], ["***.***.***-91"], ["123"]):
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, "proprietário/possuidor"):
                    validate_report_owner_documents(values)

    def test_import_and_find_direct_and_operation_links(self):
        borrowers = self._gz(
            "mutuarios.gz",
            "REF_BACEN;CD_CPF_CNPJ;CD_TIPO_BENEFICIARIO\n10;123.456.789-01;1\n20;11.222.333/0001-44;2\n",
        )
        properties = self._gz(
            "propriedades.gz",
            "REF_BACEN;NU_ORDEM;CD_CNPJ_CPF;CD_CAR;CD_SNCR\n"
            "10;1;;MT-AAA;S1\n20;1;123.456.789-01;GO-BBB;S2\n",
        )
        import_file(self.db, "mutuarios", borrowers)
        import_file(self.db, "propriedades", properties)

        results = find_by_document(self.db, "12345678901")
        self.assertEqual({row["car_original"] for row in results}, {"MT-AAA", "GO-BBB"})
        self.assertEqual(
            {row["tipo_vinculo"] for row in results},
            {"documento_na_propriedade", "associacao_por_operacao"},
        )
        self.assertEqual(find_by_car(self.db, "mt aaa")[0]["sncr"], "S1")
        linked = find_documents_by_car(self.db, "MT-AAA")
        self.assertEqual(
            {row["documento_normalizado"] for row in linked}, {"12345678901"}
        )
        self.assertEqual(linked[0]["tipo_vinculo"], "mutuario_da_operacao")

        direct = find_documents_by_car(self.db, "GO-BBB")
        self.assertIn(
            "documento_na_propriedade", {row["tipo_vinculo"] for row in direct}
        )

    def test_sicor_sentinel_is_reported_as_missing_car(self):
        properties = self._gz(
            "sem_car.gz",
            "REF_BACEN;NU_ORDEM;CD_CNPJ_CPF;CD_CAR;CD_SNCR\n"
            "10;1;123.456.789-01;-1;S1\n",
        )
        import_file(self.db, "propriedades", properties)
        result = find_by_document(self.db, "12345678901")
        self.assertEqual(result[0]["car_normalizado"], "")
        self.assertEqual(result[0]["situacao_car"], "car_nao_informado_pelo_sicor")

    def test_same_file_is_not_imported_twice(self):
        borrowers = self._gz("mutuarios.gz", "REF_BACEN;CD_CPF_CNPJ\n10;12345678901\n")
        first = import_file(self.db, "mutuarios", borrowers)
        second = import_file(self.db, "mutuarios", borrowers)
        self.assertFalse(first.ignorado)
        self.assertTrue(second.ignorado)
        count = self.db.execute("SELECT COUNT(*) FROM sicor_mutuario").fetchone()[0]
        self.assertEqual(count, 1)

    def test_slave_labor_lookup_uses_normalized_document(self):
        self.db.execute(
            """INSERT INTO trabalho_escravo
               (identificador_fonte, documento_original, documento_normalizado,
                empregador, fonte_url, arquivo_fonte)
               VALUES ('1', '123.456.789-01', '12345678901', 'Teste', 'https://example.test', 'lista.csv')"""
        )
        rows = find_slave_labor_by_documents(self.db, ["123.456.789-01"])
        self.assertEqual(rows[0]["empregador"], "Teste")

    def test_import_operation_complement_and_gleba(self):
        operation = self._gz(
            "operacao.gz",
            "#REF_BACEN;NU_ORDEM;DT_EMISSAO;CD_ESTADO;CD_EMPREENDIMENTO;VL_AREA_FINANC\n"
            "10;1;2026-09-01;MT;ABC;2,50\n",
        )
        complement = self._gz(
            "complemento.gz",
            "#REF_BACEN;NU_ORDEM;REF_BACEN_EFETIVO;AGENCIA_IF;CD_IBGE_MUNICIPIO;NUM_CEDULA_IF\n"
            "10;1;9;1234;5100250;CED-1\n",
        )
        plots = self._gz(
            "glebas.gz",
            "#REF_BACEN;NU_ORDEM;NU_IDENTIFICADOR;NU_INDICE_GLEBA;NU_INDICE_PONTO;VL_LATITUDE;VL_LONGITUDE;ID_PONTO\n"
            "10;1;1;1;1;-12,10;-55,20;P1\n10;1;1;1;2;-12,20;-55,30;P2\n",
        )
        import_file(self.db, "operacoes", operation)
        import_file(self.db, "complementos", complement)
        import_file(self.db, "glebas", plots)
        context = find_operation_context(self.db, "10", "1")
        self.assertEqual(context["municipio_ibge"], "5100250")
        self.assertEqual(context["total_glebas"], 1)
        self.assertEqual(context["total_pontos"], 2)

    def test_build_gleba_geojson_closes_polygon(self):
        plots = self._gz(
            "poligono.gz",
            "#REF_BACEN;NU_ORDEM;NU_IDENTIFICADOR;NU_INDICE_GLEBA;NU_INDICE_PONTO;VL_LATITUDE;VL_LONGITUDE;ID_PONTO\n"
            "10;1;A;1;1;-12;-55;P1\n10;1;A;1;2;-12;-54;P2\n10;1;A;1;3;-13;-54;P3\n",
        )
        import_file(self.db, "glebas", plots)
        result = build_glebas_geojson(self.db, "10", "1")
        ring = result["features"][0]["geometry"]["coordinates"][0]
        self.assertEqual(ring[0], ring[-1])
        self.assertEqual(result["metadata"]["poligonos_validos"], 1)

    def test_imports_historical_wkt_gleba(self):
        plots = self._gz(
            "glebas_wkt_2020.gz",
            "#REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA\n"
            "510;2;0;POLYGON Z ((-63 -11 0,-62 -11 0,-62 -12 0,-63 -11 0))\n",
        )
        imported = import_file(self.db, "glebas", plots)
        self.assertEqual(imported.validas, 1)
        result = build_glebas_geojson(self.db, "510", "2")
        self.assertEqual(result["features"][0]["geometry"]["type"], "Polygon")
        self.assertEqual(
            result["features"][0]["geometry"]["coordinates"][0][0], [-63.0, -11.0]
        )
        self.assertEqual(
            result["features"][0]["properties"]["origem_geometria"], "sicor_glebas_wkt"
        )

    def test_missing_required_header_rolls_back(self):
        invalid = self._gz("invalid.gz", "OUTRO;CD_CAR\n10;CAR-1\n")
        with self.assertRaises(ValueError):
            import_file(self.db, "propriedades", invalid)
        count = self.db.execute("SELECT COUNT(*) FROM importacao").fetchone()[0]
        self.assertEqual(count, 0)

    def test_import_and_find_mma_mcr(self):
        mma = self.root / "mma.csv"
        mma.write_text(
            "cod_imovel;status_imo;condicao;uf;municipio;m_fiscal;julg_status;soma_desmat;dentro_criterio;criterio_aplicado;resultados;biomas\n"
            "MT-123-ABC;AT;Aguardando análise;MT;Cuiabá;5,2;Sem restricao;3,1;nao;CERRADO;supressao em 2022;CERRADO\n",
            encoding="utf-8",
        )
        import_file(self.db, "mma_mcr", mma)
        result = find_mma_mcr_by_car(self.db, "mt 123 abc")
        self.assertEqual(result[0]["municipio"], "Cuiabá")
        self.assertEqual(result[0]["dentro_criterio"], "nao")

    def test_legacy_database_migrates_to_mma_source(self):
        legacy = sqlite3.connect(":memory:")
        legacy.row_factory = sqlite3.Row
        legacy.execute(
            """CREATE TABLE importacao (
                id INTEGER PRIMARY KEY, tipo TEXT NOT NULL CHECK (
                    tipo IN ('mutuarios', 'propriedades', 'operacoes', 'complementos', 'glebas')
                ), arquivo TEXT NOT NULL, sha256 TEXT NOT NULL,
                importado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                total_linhas INTEGER NOT NULL DEFAULT 0,
                linhas_validas INTEGER NOT NULL DEFAULT 0,
                linhas_rejeitadas INTEGER NOT NULL DEFAULT 0,
                UNIQUE(tipo, sha256))"""
        )
        legacy.execute(
            "INSERT INTO importacao(tipo, arquivo, sha256) VALUES ('mutuarios', 'a', 'hash-a')"
        )
        initialize(legacy)
        legacy.execute(
            "INSERT INTO importacao(tipo, arquivo, sha256) VALUES ('mma_mcr', 'b', 'hash-b')"
        )
        self.assertEqual(
            legacy.execute("SELECT COUNT(*) FROM importacao").fetchone()[0], 2
        )
        legacy.close()


if __name__ == "__main__":
    unittest.main()
