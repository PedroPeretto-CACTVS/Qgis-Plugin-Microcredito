from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import shutil
import sqlite3
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from database.schema import initialize
from database.session import connect
from qgis_plugin_microcredito.infrastructure.downloads import validate_geopackage
from qgis_plugin_microcredito.infrastructure.updates import (
    TEST_PUBLISHER_PUBLIC_KEY_PEM,
    CatalogClient,
    CatalogPackage,
    LocalUpdater,
    UpdateError,
    _companion_signature_url,
    _parse_catalog,
    _SecureHttpsRedirectHandler,
    latest_restore_point,
    local_inventory,
    restore_latest,
    verify_catalog_signature,
)

TEST_SIGNATURE = base64.b64decode(
    "gqVev9sd1BkAVYMvkxv5ezm4CuOwCucS4T+aS/2Kf1XV+WX2k4EWkaXJ92vRdXUuZ/xfvLSW7D66MTsFrjg3Mv+s++ZfaLNK/TeXxsa6wfFH1ywVH39InBuIIuu1tavcvIXLeTlaJgkgqw/TCPRqfanMK8zsWeC/vaPM8jxcH1dGSKBxfeZkMBICxSZ93LUOdTtl4va2LmBJDs7shSR8f4KAnd5w0V2SIi6ukj7SuLCt6O1AfYYO89cMG24QSafyp5cDE+joVPTgPBTCjrMlldtTMv2HlEEDqhArkGeRYsS75nBvX00x6rsqt2yZO5q08FSfhJdHhtuP2iIYRL94GA=="
)

CATALOG_PAYLOAD = (
    b'{"schema_version":1,"issued_at":"2026-09-01T00:00:00Z","expires_at":"2027-09-01T00:00:00Z",'
    b'"packages":[{"id":"mte","label":"Cadastro MTE","version":"2026.09.21","strategy":"import_mte",'
    b'"url":"https://publisher.example/mte.zip","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
    b'"size_bytes":123,"validity_until":"2027-01-01"}]}'
)
CATALOG_SIGNATURE = base64.b64decode(
    "zlo/i5K8FgP5iq7hd4VZsbH4jt1TBXHCp/6rP4FJvRx9Rgr/+K6zLEpKevb0pP+QzlQppnTmAFgYcqTN32Bu3LrpuVrhQjt/HG7nwaKehfmfSLxIZjNFBRPvYABLvOV/Rq5yvB0BUQDAIjXiD7Wtrm9H9DLLotmf2CrMafPdzxwSu7WnXczRHshGbyvD5qhb9z7XhzCdLE1uPGpXhJwCYf+FEoDzu8IsrhRJBN9Mh+fH7KMUr/nZheS0f0sxJpaPQ24/+n2wHLsQsGrPIHritsT7zymLTExpaBqgXq46JEsMyvpgPurqQTRU9F4XMbwiWmPzwugJr67i0/lLXesA8A=="
)


def _package(manifest: dict[str, object], payloads: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("package.json", json.dumps(manifest, sort_keys=True))
        for name, content in payloads.items():
            archive.writestr(name, content)
    return stream.getvalue()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(".test-data") / "updates" / uuid4().hex
        self.root.mkdir(parents=True)
        self.database = self.root / "car_microcredito.db"
        connection = connect(self.database)
        initialize(connection)
        connection.close()

    def tearDown(self):
        shutil.rmtree(self.root)

    def _client(self, content_by_url):
        def fetch(url, maximum):
            return content_by_url[url]

        return CatalogClient(
            "https://publisher.example/catalog.json",
            TEST_PUBLISHER_PUBLIC_KEY_PEM,
            fetcher=fetch,
        )

    def _package_descriptor(self, identifier, strategy, archive, **kwargs):
        version = kwargs.pop("version", "2026.09.21")
        return CatalogPackage(
            identifier=identifier,
            label=identifier,
            version=version,
            strategy=strategy,
            url=f"https://publisher.example/{identifier}.zip",
            sha256=hashlib.sha256(archive).hexdigest(),
            size_bytes=len(archive),
            **kwargs,
        )

    def test_catalog_signature_is_verified_and_tampering_is_rejected(self):
        payload = b'{"schema_version":1}'
        verify_catalog_signature(payload, TEST_SIGNATURE, TEST_PUBLISHER_PUBLIC_KEY_PEM)
        with self.assertRaises(UpdateError):
            verify_catalog_signature(
                payload + b" ", TEST_SIGNATURE, TEST_PUBLISHER_PUBLIC_KEY_PEM
            )

    def test_inventory_uses_regulatory_names_instead_of_raw_table_names(self):
        inventory = local_inventory(self.root, self.database)
        labels = [item.label for item in inventory]
        self.assertEqual(len(inventory), 11)
        self.assertTrue(any("Sicor/BCB" in label for label in labels))
        self.assertFalse(
            any(
                label
                in {"mutuarios", "propriedades", "operacoes", "complementos", "glebas"}
                for label in labels
            )
        )
        prodes = next(
            item for item in inventory if item.identifier == "desmatamento_pos_2020"
        )
        self.assertEqual(prodes.coverage, "Incompleta")
        self.assertIn("31/07/2019", prodes.label)

    def test_github_token_is_restricted_to_github_api(self):
        with self.assertRaisesRegex(UpdateError, "api.github.com"):
            CatalogClient(
                "https://publisher.example/catalog.json",
                TEST_PUBLISHER_PUBLIC_KEY_PEM,
                bearer_token="segredo",
            )

    def test_signature_url_keeps_github_branch_query(self):
        catalog = "https://api.github.com/repos/org/repo/contents/catalog.json?ref=codex%2Fteste"
        self.assertEqual(
            _companion_signature_url(catalog),
            "https://api.github.com/repos/org/repo/contents/catalog.json.sig?ref=codex%2Fteste",
        )

    def test_redirect_to_download_host_drops_authorization_header(self):
        request = urllib.request.Request(
            "https://api.github.com/repos/org/repo/releases/assets/1",
            headers={"Authorization": "Bearer segredo"},
        )
        redirected = _SecureHttpsRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://objects.githubusercontent.com/asset.zip",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_github_requests_use_bearer_token_without_logging_it(self):
        captured = {}

        class Response:
            headers = {}

            @staticmethod
            def geturl():
                return "https://api.github.com/repos/org/repo/contents/catalog.json"

            @staticmethod
            def close():
                pass

        class Opener:
            @staticmethod
            def open(request, timeout):
                captured["authorization"] = request.get_header("Authorization")
                captured["accept"] = request.get_header("Accept")
                return Response()

        client = CatalogClient(
            "https://api.github.com/repos/org/repo/contents/catalog.json",
            TEST_PUBLISHER_PUBLIC_KEY_PEM,
            bearer_token="segredo",
        )
        with patch(
            "qgis_plugin_microcredito.infrastructure.updates.urllib.request.build_opener",
            return_value=Opener(),
        ):
            response = client._open_https(client.catalog_url)
            response.close()
        self.assertEqual(captured["authorization"], "Bearer segredo")
        self.assertEqual(captured["accept"], "application/vnd.github.raw+json")

    def test_signed_catalog_is_parsed_before_an_update_can_be_offered(self):
        client = self._client(
            {
                "https://publisher.example/catalog.json": CATALOG_PAYLOAD,
                "https://publisher.example/catalog.json.sig": CATALOG_SIGNATURE,
            }
        )
        catalog = client.fetch_catalog()
        self.assertEqual(len(catalog.packages), 1)
        self.assertEqual(catalog.packages[0].identifier, "mte")
        self.assertEqual(catalog.packages[0].validity_until, "2027-01-01")

    def test_schema_two_requires_traceable_source_and_maps_known_target(self):
        document = {
            "schema_version": 2,
            "issued_at": "2026-09-01T00:00:00Z",
            "expires_at": "2027-09-01T00:00:00Z",
            "publication": {
                "channel": "producao",
                "prepared_by": "Equipe de Dados",
                "change_reference": "MUD-2026-001",
            },
            "packages": [
                {
                    "id": "sicar_imoveis_ac",
                    "label": "SICAR/AC",
                    "version": "2026.09.21",
                    "strategy": "replace_file",
                    "provides": ["sicar_imoveis_ac"],
                    "source_date": "2026-09-21",
                    "source_reference": "SICAR — extração estadual AC",
                    "url": "https://publisher.example/sicar-ac.zip",
                    "sha256": "a" * 64,
                    "size_bytes": 123,
                    "target": "car/AC/AC_AREA_IMOVEL.gpkg",
                }
            ],
        }
        catalog = _parse_catalog(json.dumps(document).encode())
        self.assertEqual(catalog.schema_version, 2)
        self.assertEqual(catalog.channel, "producao")
        self.assertEqual(catalog.packages[0].source_date, "2026-09-21")
        document["packages"][0]["target"] = "ambientais/embargos.gpkg"
        with self.assertRaisesRegex(UpdateError, "Destino não corresponde"):
            _parse_catalog(json.dumps(document).encode())

    def test_sicor_package_registers_both_logical_bases_and_multiple_geometry_editions(
        self,
    ):
        borrowers = gzip.compress(b"REF_BACEN;CD_CPF_CNPJ\n10;12345678901\n")
        properties = gzip.compress(
            b"REF_BACEN;NU_ORDEM;CD_CNPJ_CPF;CD_CAR\n10;1;;MT-AAA\n"
        )
        gleba_2025 = gzip.compress(
            b"REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA\n10;1;1;POLYGON ((-50 -10,-49 -10,-49 -11,-50 -10))\n"
        )
        gleba_2026 = gzip.compress(
            b"REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA\n10;1;2;POLYGON ((-51 -10,-50 -10,-50 -11,-51 -10))\n"
        )
        manifest = {
            "id": "sicor_operacoes_car",
            "version": "2026.09.21",
            "strategy": "import_sicor",
            "provides": ["sicor_operacoes_car", "sicor_geometrias"],
            "payloads": {
                "mutuarios": "payload/mutuarios.gz",
                "propriedades": "payload/propriedades.gz",
                "glebas_2025": "payload/glebas_2025.gz",
                "glebas_2026": "payload/glebas_2026.gz",
            },
            "payload_scopes": {
                "glebas_2025": "2025-nacional",
                "glebas_2026": "2026-nacional",
            },
        }
        archive = _package(
            manifest,
            {
                "payload/mutuarios.gz": borrowers,
                "payload/propriedades.gz": properties,
                "payload/glebas_2025.gz": gleba_2025,
                "payload/glebas_2026.gz": gleba_2026,
            },
        )
        package = self._package_descriptor(
            "sicor_operacoes_car",
            "import_sicor",
            archive,
            scope="2026-nacional",
            provides=("sicor_operacoes_car", "sicor_geometrias"),
            source_date="2026-09-21",
            source_reference="Sicor/BCB",
        )
        LocalUpdater(
            self.root, self.database, self._client({package.url: archive})
        ).apply(package)
        registry = json.loads(
            (self.root / ".atualizacoes" / "estado.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            registry["packages"]["sicor_operacoes_car"]["version"], "2026.09.21"
        )
        self.assertEqual(
            registry["packages"]["sicor_geometrias"]["version"], "2026.09.21"
        )
        connection = connect(self.database, readonly=True)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM ativo_sicor_gleba_wkt"
                ).fetchone()[0],
                2,
            )
        finally:
            connection.close()

    def test_partial_download_is_resumed_with_http_range(self):
        content = b"pacote grande de teste"
        destination = self.root / ".d" / "parcial.part"
        destination.parent.mkdir()
        destination.write_bytes(content[:7])
        requested_headers = {}

        class Response(io.BytesIO):
            status = 206
            headers = {
                "Content-Length": str(len(content) - 7),
                "Content-Range": f"bytes 7-{len(content) - 1}/{len(content)}",
            }

        client = CatalogClient(
            "https://publisher.example/catalog.json", TEST_PUBLISHER_PUBLIC_KEY_PEM
        )

        def open_https(url, extra_headers=None):
            requested_headers.update(extra_headers or {})
            return Response(content[7:])

        client._open_https = open_https
        client.download_package(
            "https://publisher.example/package.zip",
            destination,
            len(content),
            hashlib.sha256(content).hexdigest(),
        )
        self.assertEqual(requested_headers["Range"], "bytes=7-")
        self.assertEqual(destination.read_bytes(), content)

    def test_signed_sicar_exception_must_match_exact_foreign_feature_count(self):
        path = self.root / "AL_AREA_IMOVEL.gpkg"
        connection = sqlite3.connect(path)
        try:
            connection.executescript("""
                CREATE TABLE gpkg_contents(table_name TEXT, data_type TEXT);
                CREATE TABLE gpkg_geometry_columns(table_name TEXT, srs_id INTEGER);
                CREATE TABLE gpkg_spatial_ref_sys(srs_id INTEGER);
                CREATE TABLE AREA_IMOVEL(cod_imovel TEXT, geom BLOB);
                INSERT INTO gpkg_contents VALUES('AREA_IMOVEL','features');
                INSERT INTO gpkg_geometry_columns VALUES('AREA_IMOVEL',4674);
                INSERT INTO gpkg_spatial_ref_sys VALUES(4674);
                INSERT INTO AREA_IMOVEL VALUES('AL-VALIDO',x'00');
                INSERT INTO AREA_IMOVEL VALUES('PE-EXCECAO',x'00');
            """)
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ValueError, "diverge da exceção"):
            validate_geopackage(path, uf="AL")
        self.assertTrue(validate_geopackage(path, uf="AL", expected_foreign_features=1))

    def test_file_update_keeps_a_rollback_copy_and_records_version(self):
        target = self.root / "normativos" / "fonte.txt"
        target.parent.mkdir()
        target.write_text("versao anterior", encoding="utf-8")
        archive = _package(
            {
                "id": "fonte_teste",
                "version": "2026.09.21",
                "strategy": "replace_file",
                "target": "normativos/fonte.txt",
                "payloads": {"file": "payload/fonte.txt"},
            },
            {"payload/fonte.txt": b"versao assinada"},
        )
        package = self._package_descriptor(
            "fonte_teste", "replace_file", archive, target="normativos/fonte.txt"
        )
        result = LocalUpdater(
            self.root, self.database, self._client({package.url: archive})
        ).apply(package)
        self.assertEqual(result.state, "atual")
        self.assertEqual(target.read_text(encoding="utf-8"), "versao assinada")
        backups = list((self.root / ".h").rglob("fonte.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "versao anterior")
        registry = json.loads(
            (self.root / ".atualizacoes" / "estado.json").read_text(encoding="utf-8")
        )
        self.assertEqual(registry["packages"]["fonte_teste"]["version"], "2026.09.21")

    def test_mte_update_is_applied_to_a_staged_database_only_after_validation(self):
        csv = (
            "ID;Ano da acao fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;"
            "Decisao administrativa de procedencia;Inclusao no Cadastro de Empregadores\n"
            "1;2026;MT;Empresa Teste;12.345.678/0001-90;Endereco;2;0111-2/01;2026-01-01;2026-02-01\n"
        ).encode("cp1252")
        archive = _package(
            {
                "id": "mte",
                "version": "2026.09.21",
                "strategy": "import_mte",
                "payloads": {"file": "payload/mte.csv"},
            },
            {"payload/mte.csv": csv},
        )
        package = self._package_descriptor(
            "mte", "import_mte", archive, validity_until="2030-01-01"
        )
        LocalUpdater(
            self.root, self.database, self._client({package.url: archive})
        ).apply(package)
        connection = connect(self.database, readonly=True)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM trabalho_escravo").fetchone()[
                    0
                ],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT total_registros FROM mte_publicacao ORDER BY id DESC LIMIT 1"
                ).fetchone()[0],
                1,
            )
            source_reference = connection.execute(
                "SELECT arquivo_fonte FROM mte_publicacao ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
            self.assertTrue(source_reference.startswith("atualizacao-assinada:mte:"))
            self.assertNotIn(".u", source_reference)
        finally:
            connection.close()

    def test_checksum_failure_does_not_change_the_target(self):
        target = self.root / "fonte.txt"
        target.write_text("original", encoding="utf-8")
        archive = _package(
            {
                "id": "fonte",
                "version": "2026.09.21",
                "strategy": "replace_file",
                "target": "fonte.txt",
                "payloads": {"file": "payload/fonte.txt"},
            },
            {"payload/fonte.txt": b"nova"},
        )
        package = CatalogPackage(
            "fonte",
            "Fonte",
            "2026.09.21",
            "replace_file",
            "https://publisher.example/fonte.zip",
            "0" * 64,
            len(archive),
            target="fonte.txt",
        )
        with self.assertRaises(UpdateError):
            LocalUpdater(
                self.root, self.database, self._client({package.url: archive})
            ).apply(package)
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_file_update_can_be_restored_and_the_restore_can_be_undone(self):
        target = self.root / "normativos" / "fonte.txt"
        target.parent.mkdir()
        target.write_text("versao anterior", encoding="utf-8")
        archive = _package(
            {
                "id": "fonte_teste",
                "version": "2026.09.21",
                "strategy": "replace_file",
                "target": "normativos/fonte.txt",
                "payloads": {"file": "payload/fonte.txt"},
            },
            {"payload/fonte.txt": b"versao assinada"},
        )
        package = self._package_descriptor(
            "fonte_teste", "replace_file", archive, target="normativos/fonte.txt"
        )
        LocalUpdater(
            self.root, self.database, self._client({package.url: archive})
        ).apply(package)
        point = latest_restore_point(self.root, self.database)
        self.assertIsNotNone(point)
        self.assertFalse(point.legacy)

        progress = []
        restored = restore_latest(
            self.root,
            self.database,
            progress=lambda value, message: progress.append(value),
        )
        self.assertEqual(restored.state, "restaurada")
        self.assertEqual(target.read_text(encoding="utf-8"), "versao anterior")
        registry = json.loads(
            (self.root / ".atualizacoes" / "estado.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("fonte_teste", registry["packages"])
        self.assertEqual(progress[-1], 100)

        undo = latest_restore_point(self.root, self.database)
        self.assertEqual(undo.restore_version, "2026.09.21")
        restore_latest(self.root, self.database)
        self.assertEqual(target.read_text(encoding="utf-8"), "versao assinada")

    def test_database_update_can_be_restored_without_losing_the_replaced_state(self):
        csv = (
            "ID;Ano da acao fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;"
            "Decisao administrativa de procedencia;Inclusao no Cadastro de Empregadores\n"
            "1;2026;MT;Empresa Teste;12.345.678/0001-90;Endereco;2;0111-2/01;2026-01-01;2026-02-01\n"
        ).encode("cp1252")
        archive = _package(
            {
                "id": "mte",
                "version": "2026.09.21",
                "strategy": "import_mte",
                "payloads": {"file": "payload/mte.csv"},
            },
            {"payload/mte.csv": csv},
        )
        package = self._package_descriptor(
            "mte", "import_mte", archive, validity_until="2030-01-01"
        )
        updates = []
        LocalUpdater(
            self.root,
            self.database,
            self._client({package.url: archive}),
            progress=lambda value, message: updates.append(value),
        ).apply(package)
        self.assertEqual(updates[-1], 100)

        restore_latest(self.root, self.database)
        connection = connect(self.database, readonly=True)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM trabalho_escravo").fetchone()[
                    0
                ],
                0,
            )
        finally:
            connection.close()
        registry = json.loads(
            (self.root / ".atualizacoes" / "estado.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("mte", registry["packages"])

        restore_latest(self.root, self.database)
        connection = connect(self.database, readonly=True)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM trabalho_escravo").fetchone()[
                    0
                ],
                1,
            )
        finally:
            connection.close()
        registry = json.loads(
            (self.root / ".atualizacoes" / "estado.json").read_text(encoding="utf-8")
        )
        self.assertEqual(registry["packages"]["mte"]["version"], "2026.09.21")

    def test_legacy_090_database_backup_is_discovered_and_restored(self):
        csv = (
            "ID;Ano da acao fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;"
            "Decisao administrativa de procedencia;Inclusao no Cadastro de Empregadores\n"
            "1;2026;MT;Empresa Teste;12.345.678/0001-90;Endereco;2;0111-2/01;2026-01-01;2026-02-01\n"
        ).encode("cp1252")
        archive = _package(
            {
                "id": "mte",
                "version": "2026.09.21",
                "strategy": "import_mte",
                "payloads": {"file": "payload/mte.csv"},
            },
            {"payload/mte.csv": csv},
        )
        package = self._package_descriptor(
            "mte", "import_mte", archive, validity_until="2030-01-01"
        )
        LocalUpdater(
            self.root, self.database, self._client({package.url: archive})
        ).apply(package)
        point = latest_restore_point(self.root, self.database)
        (self.root / ".h" / Path(point.restore_id) / "restore.json").unlink()

        legacy = latest_restore_point(self.root, self.database)
        self.assertTrue(legacy.legacy)
        restore_latest(self.root, self.database)
        connection = connect(self.database, readonly=True)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM trabalho_escravo").fetchone()[
                    0
                ],
                0,
            )
        finally:
            connection.close()

    def test_corrupt_restore_copy_never_replaces_the_active_database(self):
        csv = (
            "ID;Ano da acao fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;"
            "Decisao administrativa de procedencia;Inclusao no Cadastro de Empregadores\n"
            "1;2026;MT;Empresa Teste;12.345.678/0001-90;Endereco;2;0111-2/01;2026-01-01;2026-02-01\n"
        ).encode("cp1252")
        archive = _package(
            {
                "id": "mte",
                "version": "2026.09.21",
                "strategy": "import_mte",
                "payloads": {"file": "payload/mte.csv"},
            },
            {"payload/mte.csv": csv},
        )
        package = self._package_descriptor(
            "mte", "import_mte", archive, validity_until="2030-01-01"
        )
        LocalUpdater(
            self.root, self.database, self._client({package.url: archive})
        ).apply(package)
        point = latest_restore_point(self.root, self.database)
        backup = self.root / ".h" / Path(point.restore_id) / self.database.name
        backup.write_bytes(b"not a sqlite database")

        with self.assertRaises(UpdateError):
            restore_latest(self.root, self.database)
        connection = connect(self.database, readonly=True)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM trabalho_escravo").fetchone()[
                    0
                ],
                1,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
