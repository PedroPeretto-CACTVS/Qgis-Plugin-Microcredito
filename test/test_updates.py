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

from database.schema import SCHEMA_VERSION, initialize
from database.session import connect
from qgis_plugin_microcredito.application.query_service import (
    find_slave_labor_by_documents,
)
from qgis_plugin_microcredito.infrastructure.downloads import validate_geopackage
from qgis_plugin_microcredito.infrastructure.updates import (
    TEST_PUBLISHER_PUBLIC_KEY_PEM,
    BaseReleaseBundle,
    Catalog,
    CatalogClient,
    CatalogPackage,
    LocalRestorer,
    LocalUpdater,
    UpdateError,
    _acquire_update_lock,
    _companion_signature_url,
    _parse_catalog,
    _release_update_lock,
    _SecureHttpsRedirectHandler,
    apply_catalog_release,
    compare_catalog,
    ensure_not_updating,
    latest_restore_point,
    local_inventory,
    restore_latest,
    update_lock_path,
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

    def _write_geopackage(self, path, identifiers):
        path.parent.mkdir(parents=True, exist_ok=True)
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
            """)
            connection.executemany(
                "INSERT INTO AREA_IMOVEL VALUES(?, x'00')",
                ((identifier,) for identifier in identifiers),
            )
            connection.commit()
        finally:
            connection.close()

        return path

    def _write_release_bundle(
        self,
        path: Path,
        catalog_payload: bytes,
        packages: dict[str, bytes],
    ) -> Path:
        with zipfile.ZipFile(path, "w", allowZip64=True) as archive:
            archive.writestr("catalog.json", catalog_payload)
            archive.writestr("catalog.json.sig", b"assinatura-teste")
            for identifier, content in packages.items():
                archive.writestr(f"packages/{identifier}.zip", content)
        return path

    def test_local_release_bundle_verifies_every_embedded_package(self):
        package = _package(
            {
                "schema_version": 1,
                "id": "mte",
                "version": "2026.10.06",
                "strategy": "import_mte",
                "provides": ["mte"],
                "payloads": {"file": "payload/mte.csv"},
            },
            {"payload/mte.csv": b"conteudo-oficial"},
        )
        catalog_payload = json.dumps(
            {
                "schema_version": 1,
                "issued_at": "2026-10-15T12:00:00-03:00",
                "expires_at": "2027-10-15T12:00:00-03:00",
                "packages": [
                    {
                        "id": "mte",
                        "label": "Cadastro MTE",
                        "version": "2026.10.06",
                        "strategy": "import_mte",
                        "url": "carbases://packages/mte.zip",
                        "sha256": hashlib.sha256(package).hexdigest(),
                        "size_bytes": len(package),
                        "validity_until": "2027-04-05",
                    }
                ],
            }
        ).encode()
        release_path = self._write_release_bundle(
            self.root / "bases-2026-10.carbases",
            catalog_payload,
            {"mte": package},
        )

        with patch(
            "qgis_plugin_microcredito.infrastructure.updates.verify_catalog_signature"
        ) as verify:
            release = BaseReleaseBundle(release_path, TEST_PUBLISHER_PUBLIC_KEY_PEM)
            catalog = release.fetch_catalog()
            destination = self.root / "downloaded.zip"
            release.download_package(
                catalog.packages[0].url,
                destination,
                catalog.packages[0].size_bytes,
                catalog.packages[0].sha256,
            )

        verify.assert_called_once_with(
            catalog_payload, b"assinatura-teste", TEST_PUBLISHER_PUBLIC_KEY_PEM
        )
        self.assertEqual(destination.read_bytes(), package)

    def test_catalog_release_bootstraps_missing_data_root_from_valid_bundle(self):
        csv = (
            "ID;Ano da acao fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;"
            "Decisao administrativa de procedencia;Inclusao no Cadastro de Empregadores\n"
            "1;2026;MT;Empresa Teste;12.345.678/0001-90;Endereco;2;0111-2/01;2026-01-01;2026-02-01\n"
        ).encode("cp1252")
        package = _package(
            {
                "schema_version": 1,
                "id": "mte",
                "version": "2026.10.06",
                "strategy": "import_mte",
                "provides": ["mte"],
                "payloads": {"file": "payload/mte.csv"},
            },
            {"payload/mte.csv": csv},
        )
        catalog_payload = json.dumps(
            {
                "schema_version": 3,
                "issued_at": "2026-10-23T12:00:00-03:00",
                "expires_at": "2027-10-23T12:00:00-03:00",
                "publication": {
                    "channel": "homologacao",
                    "prepared_by": "Equipe de Dados",
                    "change_reference": "BOOTSTRAP-001",
                },
                "packages": [
                    {
                        "id": "mte",
                        "label": "Cadastro de Empregadores — MTE",
                        "version": "2026.10.06",
                        "strategy": "import_mte",
                        "provides": ["mte"],
                        "source_date": "2026-10-06",
                        "source_reference": "Cadastro de Empregadores — MTE",
                        "source_evidence": {
                            "official_page_url": "https://www.gov.br/trabalho-e-emprego/",
                            "official_artifact_url": "https://www.gov.br/trabalho-e-emprego/mte.csv",
                            "checked_at": "2026-10-23T11:30:00-03:00",
                        },
                        "compatibility": {
                            "minimum_plugin_version": "0.9.5",
                            "maximum_plugin_version": "0.9.5",
                            "database_schema_version": SCHEMA_VERSION,
                            "package_manifest_schema_version": 1,
                        },
                        "url": "carbases://packages/mte.zip",
                        "sha256": hashlib.sha256(package).hexdigest(),
                        "size_bytes": len(package),
                        "validity_until": "2027-04-05",
                    }
                ],
            }
        ).encode()
        release_path = self._write_release_bundle(
            self.root / "bootstrap.carbases",
            catalog_payload,
            {"mte": package},
        )
        data_root = self.root / "fixed-data"
        database = data_root / "car_microcredito.db"
        self.assertFalse(data_root.exists())

        with patch(
            "qgis_plugin_microcredito.infrastructure.updates.verify_catalog_signature"
        ):
            release = BaseReleaseBundle(release_path, TEST_PUBLISHER_PUBLIC_KEY_PEM)
        final_progress_was_locked = []

        def observe_progress(_value: int, message: str) -> None:
            if message != "Bases Plugin aplicado e validado.":
                return
            try:
                ensure_not_updating(data_root)
            except UpdateError:
                final_progress_was_locked.append(True)

        statuses = apply_catalog_release(
            release.fetch_catalog(),
            data_root,
            database,
            release,
            progress=observe_progress,
        )

        self.assertEqual([status.identifier for status in statuses], ["mte"])
        self.assertEqual(final_progress_was_locked, [True])
        self.assertTrue(database.is_file())
        connection = connect(database, readonly=True)
        try:
            self.assertEqual(
                len(find_slave_labor_by_documents(connection, ["12.345.678/0001-90"])),
                1,
            )
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                SCHEMA_VERSION,
            )
        finally:
            connection.close()

        prepared_root = self.root / "fixed-data-with-lock-file"
        prepared_lock = update_lock_path(prepared_root)
        prepared_lock.parent.mkdir(parents=True)
        prepared_lock.touch()
        prepared_database = prepared_root / "car_microcredito.db"

        prepared_statuses = apply_catalog_release(
            release.fetch_catalog(),
            prepared_root,
            prepared_database,
            release,
        )

        self.assertEqual(
            [status.identifier for status in prepared_statuses],
            ["mte"],
        )
        self.assertTrue(prepared_database.is_file())

    def test_failed_bootstrap_release_removes_database_and_installed_markers(self):
        csv = (
            "ID;Ano da acao fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;"
            "Decisao administrativa de procedencia;Inclusao no Cadastro de Empregadores\n"
            "1;2026;MT;Empresa Teste;12.345.678/0001-90;Endereco;2;0111-2/01;2026-01-01;2026-02-01\n"
        ).encode("cp1252")
        mte_package = _package(
            {
                "schema_version": 1,
                "id": "mte",
                "version": "2026.10.06",
                "strategy": "import_mte",
                "provides": ["mte"],
                "payloads": {"file": "payload/mte.csv"},
            },
            {"payload/mte.csv": csv},
        )
        invalid_sicar_package = _package(
            {
                "schema_version": 1,
                "id": "id-divergente",
                "version": "2026.10.23",
                "strategy": "replace_file",
                "provides": ["sicar_imoveis_ac"],
                "target": "car/AC/AC_AREA_IMOVEL.gpkg",
                "payloads": {"file": "payload/AC_AREA_IMOVEL.gpkg"},
            },
            {"payload/AC_AREA_IMOVEL.gpkg": b"conteudo-invalido"},
        )

        def descriptor(
            identifier: str,
            label: str,
            version: str,
            strategy: str,
            package: bytes,
            **extra: object,
        ) -> dict[str, object]:
            return {
                "id": identifier,
                "label": label,
                "version": version,
                "strategy": strategy,
                "provides": [identifier],
                "source_date": "2026-10-23",
                "source_reference": label,
                "source_evidence": {
                    "official_page_url": "https://www.gov.br/fonte-oficial/",
                    "official_artifact_url": "https://www.gov.br/fonte-oficial/arquivo",
                    "checked_at": "2026-10-23T11:30:00-03:00",
                },
                "compatibility": {
                    "minimum_plugin_version": "0.9.5",
                    "maximum_plugin_version": "0.9.5",
                    "database_schema_version": SCHEMA_VERSION,
                    "package_manifest_schema_version": 1,
                },
                "url": f"carbases://packages/{identifier}.zip",
                "sha256": hashlib.sha256(package).hexdigest(),
                "size_bytes": len(package),
                **extra,
            }

        catalog_payload = json.dumps(
            {
                "schema_version": 3,
                "issued_at": "2026-10-23T12:00:00-03:00",
                "expires_at": "2027-10-23T12:00:00-03:00",
                "publication": {
                    "channel": "homologacao",
                    "prepared_by": "Equipe de Dados",
                    "change_reference": "BOOTSTRAP-ROLLBACK-001",
                },
                "packages": [
                    descriptor(
                        "mte",
                        "Cadastro de Empregadores — MTE",
                        "2026.10.06",
                        "import_mte",
                        mte_package,
                        validity_until="2027-04-05",
                    ),
                    descriptor(
                        "sicar_imoveis_ac",
                        "SICAR/AC",
                        "2026.10.23",
                        "replace_file",
                        invalid_sicar_package,
                        target="car/AC/AC_AREA_IMOVEL.gpkg",
                    ),
                ],
            }
        ).encode()
        release_path = self._write_release_bundle(
            self.root / "bootstrap-rollback.carbases",
            catalog_payload,
            {
                "mte": mte_package,
                "sicar_imoveis_ac": invalid_sicar_package,
            },
        )
        data_root = self.root / "fixed-data-rollback"
        database = data_root / "car_microcredito.db"

        with patch(
            "qgis_plugin_microcredito.infrastructure.updates.verify_catalog_signature"
        ):
            release = BaseReleaseBundle(release_path, TEST_PUBLISHER_PUBLIC_KEY_PEM)
        with self.assertRaisesRegex(UpdateError, "restauradas"):
            apply_catalog_release(release.fetch_catalog(), data_root, database, release)

        self.assertFalse(database.exists())
        self.assertFalse((data_root / "car" / "AC" / "AC_AREA_IMOVEL.gpkg").exists())
        self.assertIsNone(latest_restore_point(data_root, database))
        registry_path = data_root / ".atualizacoes" / "estado.json"
        self.assertFalse(registry_path.exists())

        older_mte = self._package_descriptor(
            "mte",
            "import_mte",
            mte_package,
            version="2026.10.06",
            validity_until="2027-04-05",
            catalog_issued_at="2026-10-22T12:00:00-03:00",
        )
        older_catalog = Catalog(
            "2026-10-22T12:00:00-03:00",
            "2027-10-22T12:00:00-03:00",
            (older_mte,),
        )
        statuses = apply_catalog_release(
            older_catalog,
            data_root,
            database,
            self._client({older_mte.url: mte_package}),
        )

        self.assertEqual([status.identifier for status in statuses], ["mte"])
        self.assertTrue(database.is_file())

    def test_release_without_applicable_pending_package_does_not_create_database(self):
        archive = b"pacote-nao-baixado"
        package = self._package_descriptor(
            "mte",
            "import_mte",
            archive,
            version="2026.10.06",
            validity_until="2027-04-05",
            minimum_plugin_version="99.0.0",
            maximum_plugin_version="99.0.0",
            database_schema_version=SCHEMA_VERSION,
            package_manifest_schema_version=1,
        )
        catalog = Catalog(
            "2026-10-23T15:00:00+00:00",
            "2027-10-23T15:00:00+00:00",
            (package,),
        )
        data_root = self.root / "fixed-data-incompatible"
        database = data_root / "car_microcredito.db"

        statuses = apply_catalog_release(
            catalog,
            data_root,
            database,
            self._client({package.url: archive}),
        )

        self.assertEqual(statuses, [])
        self.assertFalse(data_root.exists())
        self.assertFalse(database.exists())

    def test_failed_bootstrap_preserves_recovery_database_when_rollback_fails(self):
        first_archive = _package(
            {
                "id": "primeira",
                "version": "2026.10.23",
                "strategy": "replace_file",
                "target": "normativos/primeira.txt",
                "payloads": {"file": "payload/primeira.txt"},
            },
            {"payload/primeira.txt": b"primeira"},
        )
        invalid_archive = _package(
            {
                "id": "id-divergente",
                "version": "2026.10.23",
                "strategy": "replace_file",
                "target": "normativos/segunda.txt",
                "payloads": {"file": "payload/segunda.txt"},
            },
            {"payload/segunda.txt": b"segunda"},
        )
        first = self._package_descriptor(
            "primeira",
            "replace_file",
            first_archive,
            version="2026.10.23",
            target="normativos/primeira.txt",
        )
        invalid = self._package_descriptor(
            "segunda",
            "replace_file",
            invalid_archive,
            version="2026.10.23",
            target="normativos/segunda.txt",
        )
        catalog = Catalog(
            "2026-10-23T15:00:00+00:00",
            "2027-10-23T15:00:00+00:00",
            (first, invalid),
        )
        data_root = self.root / "fixed-data-double-failure"
        database = data_root / "car_microcredito.db"

        with (
            patch.object(
                LocalRestorer,
                "_restore_point",
                autospec=True,
                side_effect=UpdateError("falha simulada no rollback"),
            ),
            self.assertRaisesRegex(UpdateError, "nem todas as bases"),
        ):
            apply_catalog_release(
                catalog,
                data_root,
                database,
                self._client({first.url: first_archive, invalid.url: invalid_archive}),
            )

        self.assertTrue(database.is_file())
        connection = connect(database, readonly=True)
        try:
            self.assertEqual(
                connection.execute("PRAGMA quick_check").fetchone()[0], "ok"
            )
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                SCHEMA_VERSION,
            )
        finally:
            connection.close()

    def test_release_with_incompatible_and_pending_packages_is_not_partially_applied(
        self,
    ):
        incompatible_archive = b"pacote-incompativel"
        pending_archive = b"pacote-compativel"
        incompatible = self._package_descriptor(
            "incompativel",
            "replace_file",
            incompatible_archive,
            version="2026.10.23",
            target="normativos/incompativel.txt",
            minimum_plugin_version="99.0.0",
            maximum_plugin_version="99.0.0",
            database_schema_version=SCHEMA_VERSION,
            package_manifest_schema_version=1,
        )
        pending = self._package_descriptor(
            "compativel",
            "replace_file",
            pending_archive,
            version="2026.10.23",
            target="normativos/compativel.txt",
        )
        catalog = Catalog(
            "2026-10-23T15:00:00+00:00",
            "2027-10-23T15:00:00+00:00",
            (incompatible, pending),
        )
        data_root = self.root / "fixed-data-partially-incompatible"
        database = data_root / "car_microcredito.db"

        with self.assertRaisesRegex(UpdateError, "inaplicável"):
            apply_catalog_release(
                catalog,
                data_root,
                database,
                self._client(
                    {
                        incompatible.url: incompatible_archive,
                        pending.url: pending_archive,
                    }
                ),
            )

        self.assertFalse(data_root.exists())
        self.assertFalse(database.exists())

    def test_bundle_url_is_accepted_only_inside_signed_offline_release(self):
        payload = json.dumps(
            {
                "schema_version": 1,
                "issued_at": "2026-10-15T12:00:00-03:00",
                "expires_at": "2027-10-15T12:00:00-03:00",
                "packages": [
                    {
                        "id": "mte",
                        "label": "Cadastro MTE",
                        "version": "2026.10.06",
                        "strategy": "import_mte",
                        "url": "carbases://packages/mte.zip",
                        "sha256": "a" * 64,
                        "size_bytes": 123,
                        "validity_until": "2027-04-05",
                    }
                ],
            }
        ).encode()

        with self.assertRaisesRegex(UpdateError, "HTTPS"):
            _parse_catalog(payload)
        catalog = _parse_catalog(payload, allow_bundle_urls=True)
        self.assertEqual(catalog.packages[0].url, "carbases://packages/mte.zip")

    def test_bundle_url_must_match_the_declared_package(self):
        payload = json.dumps(
            {
                "schema_version": 1,
                "issued_at": "2026-10-15T12:00:00-03:00",
                "expires_at": "2027-10-15T12:00:00-03:00",
                "packages": [
                    {
                        "id": "mte",
                        "label": "Cadastro MTE",
                        "version": "2026.10.06",
                        "strategy": "import_mte",
                        "url": "carbases://packages/outro.zip",
                        "sha256": "a" * 64,
                        "size_bytes": 123,
                        "validity_until": "2027-04-05",
                    }
                ],
            }
        ).encode()

        with self.assertRaisesRegex(UpdateError, "Bases Plugin"):
            _parse_catalog(payload, allow_bundle_urls=True)

    def test_local_release_bundle_rejects_missing_or_unlisted_packages(self):
        catalog_payload = json.dumps(
            {
                "schema_version": 1,
                "issued_at": "2026-10-15T12:00:00-03:00",
                "expires_at": "2027-10-15T12:00:00-03:00",
                "packages": [
                    {
                        "id": "mte",
                        "label": "Cadastro MTE",
                        "version": "2026.10.06",
                        "strategy": "import_mte",
                        "url": "https://publisher.example/mte.zip",
                        "sha256": "a" * 64,
                        "size_bytes": 123,
                        "validity_until": "2027-04-05",
                    }
                ],
            }
        ).encode()
        missing = self._write_release_bundle(
            self.root / "missing.carbases", catalog_payload, {}
        )
        extra = self._write_release_bundle(
            self.root / "extra.carbases",
            catalog_payload,
            {"mte": b"x", "nao-assinado": b"y"},
        )

        with patch(
            "qgis_plugin_microcredito.infrastructure.updates.verify_catalog_signature"
        ):
            with self.assertRaisesRegex(UpdateError, "pacotes declarados"):
                BaseReleaseBundle(missing, TEST_PUBLISHER_PUBLIC_KEY_PEM)
            with self.assertRaisesRegex(UpdateError, "conteúdo não declarado"):
                BaseReleaseBundle(extra, TEST_PUBLISHER_PUBLIC_KEY_PEM)

    def test_catalog_release_restores_packages_and_preserves_preexisting_history(self):
        prior_backups = {
            self.root / ".h/manual/20260101/sentinel.db": b"old manual backup",
            self.root / ".h/unknown/partial/restore.json": b"{incomplete metadata",
        }
        for path, content in prior_backups.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        first_target = self.root / "normativos" / "primeira.txt"
        second_target = self.root / "normativos" / "segunda.txt"
        first_target.parent.mkdir(parents=True)
        first_target.write_text("primeira-antiga", encoding="utf-8")
        second_target.write_text("segunda-antiga", encoding="utf-8")
        first_archive = _package(
            {
                "id": "primeira",
                "version": "2026.10.15",
                "strategy": "replace_file",
                "target": "normativos/primeira.txt",
                "payloads": {"file": "payload/primeira.txt"},
            },
            {"payload/primeira.txt": b"primeira-nova"},
        )
        second_archive = _package(
            {
                "id": "id-divergente",
                "version": "2026.10.15",
                "strategy": "replace_file",
                "target": "normativos/segunda.txt",
                "payloads": {"file": "payload/segunda.txt"},
            },
            {"payload/segunda.txt": b"segunda-nova"},
        )
        catalog = Catalog(
            "2026-10-15T15:00:00+00:00",
            "2027-10-15T15:00:00+00:00",
            (
                self._package_descriptor(
                    "primeira",
                    "replace_file",
                    first_archive,
                    version="2026.10.15",
                    target="normativos/primeira.txt",
                ),
                self._package_descriptor(
                    "segunda",
                    "replace_file",
                    second_archive,
                    version="2026.10.15",
                    target="normativos/segunda.txt",
                ),
            ),
        )
        client = self._client(
            {
                catalog.packages[0].url: first_archive,
                catalog.packages[1].url: second_archive,
            }
        )

        with self.assertRaisesRegex(UpdateError, "restauradas"):
            apply_catalog_release(catalog, self.root, self.database, client)

        self.assertEqual(first_target.read_text(encoding="utf-8"), "primeira-antiga")
        self.assertEqual(second_target.read_text(encoding="utf-8"), "segunda-antiga")

        for path, content in prior_backups.items():
            self.assertTrue(path.is_file(), str(path))
            self.assertEqual(path.read_bytes(), content)
        self.assertIsNone(latest_restore_point(self.root, self.database))

    def test_catalog_release_rolls_back_multiple_prior_packages_to_one_checkpoint(self):
        targets = [
            self.root / "normativos" / "primeira.txt",
            self.root / "normativos" / "segunda.txt",
            self.root / "normativos" / "terceira.txt",
        ]
        targets[0].parent.mkdir(parents=True)
        for index, target in enumerate(targets, start=1):
            target.write_text(f"antiga-{index}", encoding="utf-8")
        archives = [
            _package(
                {
                    "id": identifier if index < 3 else "id-divergente",
                    "version": "2026.10.15",
                    "strategy": "replace_file",
                    "target": f"normativos/{identifier}.txt",
                    "payloads": {"file": f"payload/{identifier}.txt"},
                },
                {f"payload/{identifier}.txt": f"nova-{index}".encode()},
            )
            for index, identifier in enumerate(
                ("primeira", "segunda", "terceira"), start=1
            )
        ]
        descriptors = tuple(
            self._package_descriptor(
                identifier,
                "replace_file",
                archive,
                version="2026.10.15",
                target=f"normativos/{identifier}.txt",
            )
            for identifier, archive in zip(
                ("primeira", "segunda", "terceira"), archives, strict=True
            )
        )
        catalog = Catalog(
            "2026-10-15T15:00:00+00:00",
            "2027-10-15T15:00:00+00:00",
            descriptors,
        )
        client = self._client(
            {
                package.url: archive
                for package, archive in zip(descriptors, archives, strict=True)
            }
        )

        with self.assertRaisesRegex(UpdateError, "restauradas"):
            apply_catalog_release(catalog, self.root, self.database, client)

        self.assertEqual(
            [target.read_text(encoding="utf-8") for target in targets],
            ["antiga-1", "antiga-2", "antiga-3"],
        )
        self.assertIsNone(latest_restore_point(self.root, self.database))

    def test_catalog_release_restores_package_that_fails_after_file_promotion(self):
        targets = [
            self.root / "normativos" / "primeira.txt",
            self.root / "normativos" / "segunda.txt",
        ]
        targets[0].parent.mkdir(parents=True)
        for index, target in enumerate(targets, start=1):
            target.write_text(f"antiga-{index}", encoding="utf-8")
        archives = [
            _package(
                {
                    "id": identifier,
                    "version": "2026.10.15",
                    "strategy": "replace_file",
                    "target": f"normativos/{identifier}.txt",
                    "payloads": {"file": f"payload/{identifier}.txt"},
                },
                {f"payload/{identifier}.txt": f"nova-{index}".encode()},
            )
            for index, identifier in enumerate(("primeira", "segunda"), start=1)
        ]
        descriptors = tuple(
            self._package_descriptor(
                identifier,
                "replace_file",
                archive,
                version="2026.10.15",
                target=f"normativos/{identifier}.txt",
            )
            for identifier, archive in zip(
                ("primeira", "segunda"), archives, strict=True
            )
        )
        catalog = Catalog(
            "2026-10-15T15:00:00+00:00",
            "2027-10-15T15:00:00+00:00",
            descriptors,
        )
        client = self._client(
            {
                package.url: archive
                for package, archive in zip(descriptors, archives, strict=True)
            }
        )
        original_record = LocalUpdater._record_installation

        def record_or_fail(updater, package):
            if package.identifier == "segunda":
                raise OSError("falha simulada no registro")
            return original_record(updater, package)

        with (
            patch.object(
                LocalUpdater,
                "_record_installation",
                autospec=True,
                side_effect=record_or_fail,
            ),
            self.assertRaisesRegex(UpdateError, "restauradas"),
        ):
            apply_catalog_release(catalog, self.root, self.database, client)

        self.assertEqual(
            [target.read_text(encoding="utf-8") for target in targets],
            ["antiga-1", "antiga-2"],
        )
        self.assertIsNone(latest_restore_point(self.root, self.database))

    def test_catalog_release_restores_database_when_later_package_fails(self):
        csv = (
            "ID;Ano da acao fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;"
            "Decisao administrativa de procedencia;Inclusao no Cadastro de Empregadores\n"
            "1;2026;MT;Empresa Teste;12.345.678/0001-90;Endereco;2;0111-2/01;2026-01-01;2026-02-01\n"
        ).encode("cp1252")
        mte_archive = _package(
            {
                "id": "mte",
                "version": "2026.10.15",
                "strategy": "import_mte",
                "payloads": {"file": "payload/mte.csv"},
            },
            {"payload/mte.csv": csv},
        )
        invalid_archive = _package(
            {
                "id": "id-divergente",
                "version": "2026.10.15",
                "strategy": "replace_file",
                "target": "normativos/invalida.txt",
                "payloads": {"file": "payload/invalida.txt"},
            },
            {"payload/invalida.txt": b"invalida"},
        )
        mte = self._package_descriptor(
            "mte",
            "import_mte",
            mte_archive,
            version="2026.10.15",
            validity_until="2030-01-01",
        )
        invalid = self._package_descriptor(
            "invalida",
            "replace_file",
            invalid_archive,
            version="2026.10.15",
            target="normativos/invalida.txt",
        )
        catalog = Catalog(
            "2026-10-15T15:00:00+00:00",
            "2027-10-15T15:00:00+00:00",
            (mte, invalid),
        )
        client = self._client({mte.url: mte_archive, invalid.url: invalid_archive})

        with self.assertRaisesRegex(UpdateError, "restauradas"):
            apply_catalog_release(catalog, self.root, self.database, client)

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
        self.assertIsNone(latest_restore_point(self.root, self.database))

    def _replace_file_catalog(
        self, issued_at: str, version: str, archive: bytes
    ) -> Catalog:
        document = {
            "schema_version": 1,
            "issued_at": issued_at,
            "expires_at": "2027-09-01T00:00:00Z",
            "packages": [
                {
                    "id": "fonte_teste",
                    "label": "Fonte teste",
                    "version": version,
                    "strategy": "replace_file",
                    "url": "https://publisher.example/fonte-teste.zip",
                    "sha256": hashlib.sha256(archive).hexdigest(),
                    "size_bytes": len(archive),
                    "target": "normativos/fonte.txt",
                }
            ],
        }
        return _parse_catalog(json.dumps(document).encode())

    def test_catalog_signature_is_verified_and_tampering_is_rejected(self):
        payload = b'{"schema_version":1}'
        verify_catalog_signature(payload, TEST_SIGNATURE, TEST_PUBLISHER_PUBLIC_KEY_PEM)
        with self.assertRaises(UpdateError):
            verify_catalog_signature(
                payload + b" ", TEST_SIGNATURE, TEST_PUBLISHER_PUBLIC_KEY_PEM
            )

    def test_stale_update_lock_file_does_not_block_operations(self):
        lock_path = update_lock_path(self.root)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("2026-01-01T00:00:00+00:00", encoding="utf-8")

        ensure_not_updating(self.root)

    def test_update_lock_blocks_only_while_held_by_a_process(self):
        lock = _acquire_update_lock(self.root)
        try:
            with self.assertRaisesRegex(UpdateError, "andamento"):
                ensure_not_updating(self.root)
            with self.assertRaisesRegex(UpdateError, "andamento"):
                _acquire_update_lock(self.root)
        finally:
            _release_update_lock(lock)

        self.assertTrue(update_lock_path(self.root).exists())
        ensure_not_updating(self.root)

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

    def test_older_catalog_is_not_offered_or_applied(self):
        target = self.root / "normativos" / "fonte.txt"
        target.parent.mkdir()
        target.write_text("versao atual", encoding="utf-8")
        archive = _package(
            {
                "id": "fonte_teste",
                "version": "2026.08.01",
                "strategy": "replace_file",
                "target": "normativos/fonte.txt",
                "payloads": {"file": "payload/fonte.txt"},
            },
            {"payload/fonte.txt": b"versao antiga"},
        )
        catalog = self._replace_file_catalog(
            "2026-09-01T00:00:00Z", "2026.08.01", archive
        )
        registry = self.root / ".atualizacoes" / "estado.json"
        registry.parent.mkdir()
        registry.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "latest_catalog_issued_at": "2026-09-20T00:00:00+00:00",
                    "packages": {
                        "fonte_teste": {
                            "version": "2026.09.20",
                            "catalog_issued_at": "2026-09-20T00:00:00+00:00",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        status = compare_catalog(catalog, self.root, self.database)[0]

        self.assertEqual(status.state, "inaplicavel")
        self.assertIn("anterior", status.detail)
        with self.assertRaisesRegex(UpdateError, "anterior"):
            LocalUpdater(
                self.root,
                self.database,
                self._client({catalog.packages[0].url: archive}),
            ).apply(catalog.packages[0])
        self.assertEqual(target.read_text(encoding="utf-8"), "versao atual")

    def test_install_records_catalog_date_without_rolling_it_back_on_restore(self):
        target = self.root / "normativos" / "fonte.txt"
        target.parent.mkdir()
        target.write_text("versao anterior", encoding="utf-8")
        archive = _package(
            {
                "id": "fonte_teste",
                "version": "2026.09.20",
                "strategy": "replace_file",
                "target": "normativos/fonte.txt",
                "payloads": {"file": "payload/fonte.txt"},
            },
            {"payload/fonte.txt": b"versao nova"},
        )
        catalog = self._replace_file_catalog(
            "2026-09-20T00:00:00Z", "2026.09.20", archive
        )
        LocalUpdater(
            self.root,
            self.database,
            self._client({catalog.packages[0].url: archive}),
        ).apply(catalog.packages[0])

        registry_path = self.root / ".atualizacoes" / "estado.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        expected = "2026-09-20T00:00:00+00:00"
        self.assertEqual(registry["latest_catalog_issued_at"], expected)
        self.assertEqual(
            registry["packages"]["fonte_teste"]["catalog_issued_at"], expected
        )

        restore_latest(self.root, self.database)
        restored_registry = json.loads(registry_path.read_text(encoding="utf-8"))
        self.assertEqual(restored_registry["latest_catalog_issued_at"], expected)

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

    def test_schema_three_requires_official_evidence_and_runtime_compatibility(self):
        document = {
            "schema_version": 3,
            "issued_at": "2026-10-14T12:00:00-03:00",
            "expires_at": "2026-11-14T12:00:00-03:00",
            "publication": {
                "channel": "homologacao",
                "prepared_by": "Equipe de Dados",
                "change_reference": "MUD-2026-002",
            },
            "packages": [
                {
                    "id": "sicar_imoveis_ac",
                    "label": "SICAR/AC",
                    "version": "2026.10.14",
                    "strategy": "replace_file",
                    "provides": ["sicar_imoveis_ac"],
                    "source_date": "2026-10-14",
                    "source_reference": "SICAR — extração estadual AC",
                    "source_evidence": {
                        "official_page_url": "https://www.gov.br/agricultura/sicar",
                        "official_artifact_url": "https://example.gov.br/sicar/ac.gpkg",
                        "checked_at": "2026-10-14T11:30:00-03:00",
                    },
                    "compatibility": {
                        "minimum_plugin_version": "0.9.5",
                        "maximum_plugin_version": "0.9.5",
                        "database_schema_version": SCHEMA_VERSION,
                        "package_manifest_schema_version": 1,
                    },
                    "url": "https://publisher.example/sicar-ac.zip",
                    "sha256": "a" * 64,
                    "size_bytes": 123,
                    "target": "car/AC/AC_AREA_IMOVEL.gpkg",
                }
            ],
        }

        catalog = _parse_catalog(json.dumps(document).encode())
        package = catalog.packages[0]

        self.assertEqual(catalog.schema_version, 3)
        self.assertEqual(package.minimum_plugin_version, "0.9.5")
        self.assertEqual(package.maximum_plugin_version, "0.9.5")
        self.assertEqual(package.database_schema_version, SCHEMA_VERSION)
        self.assertEqual(package.package_manifest_schema_version, 1)
        self.assertEqual(
            package.official_page_url, "https://www.gov.br/agricultura/sicar"
        )
        self.assertEqual(package.source_checked_at, "2026-10-14T14:30:00+00:00")

        document["packages"][0]["source_evidence"]["official_page_url"] = (
            "http://example.gov.br/sicar"
        )
        with self.assertRaisesRegex(UpdateError, "URL oficial"):
            _parse_catalog(json.dumps(document).encode())

    def test_incompatible_schema_three_package_is_neither_offered_nor_downloaded(self):
        document = {
            "schema_version": 3,
            "issued_at": "2026-10-14T12:00:00-03:00",
            "expires_at": "2026-11-14T12:00:00-03:00",
            "publication": {
                "channel": "homologacao",
                "prepared_by": "Equipe de Dados",
                "change_reference": "MUD-2026-003",
            },
            "packages": [
                {
                    "id": "sicar_imoveis_ac",
                    "label": "SICAR/AC",
                    "version": "2026.10.14",
                    "strategy": "replace_file",
                    "provides": ["sicar_imoveis_ac"],
                    "source_date": "2026-10-14",
                    "source_reference": "SICAR — extração estadual AC",
                    "source_evidence": {
                        "official_page_url": "https://www.gov.br/agricultura/sicar",
                        "checked_at": "2026-10-14T11:30:00-03:00",
                    },
                    "compatibility": {
                        "minimum_plugin_version": "99.0.0",
                        "maximum_plugin_version": "99.0.0",
                        "database_schema_version": SCHEMA_VERSION,
                        "package_manifest_schema_version": 1,
                    },
                    "url": "https://publisher.example/sicar-ac.zip",
                    "sha256": "a" * 64,
                    "size_bytes": 123,
                    "target": "car/AC/AC_AREA_IMOVEL.gpkg",
                }
            ],
        }
        catalog = _parse_catalog(json.dumps(document).encode())

        status = compare_catalog(catalog, self.root, self.database)[0]

        self.assertEqual(status.state, "inaplicavel")
        self.assertIn("incompatível", status.detail.lower())

        def unexpected_download(_url, _maximum):
            raise AssertionError("Pacote incompatível não pode ser baixado.")

        client = CatalogClient(
            "https://publisher.example/catalog.json",
            TEST_PUBLISHER_PUBLIC_KEY_PEM,
            fetcher=unexpected_download,
        )
        with self.assertRaisesRegex(UpdateError, "incompatível"):
            LocalUpdater(self.root, self.database, client).apply(catalog.packages[0])

        compatibility = document["packages"][0]["compatibility"]
        compatibility["minimum_plugin_version"] = "0.9.5"
        compatibility["maximum_plugin_version"] = "0.9.5"
        compatibility["database_schema_version"] = SCHEMA_VERSION + 1
        database_incompatible = _parse_catalog(json.dumps(document).encode())

        database_status = compare_catalog(
            database_incompatible, self.root, self.database
        )[0]

        self.assertEqual(database_status.state, "inaplicavel")
        self.assertIn("esquema", database_status.detail.lower())
        with self.assertRaisesRegex(UpdateError, "esquema"):
            LocalUpdater(self.root, self.database, client).apply(
                database_incompatible.packages[0]
            )

    def test_schema_three_rejects_legacy_package_manifest_before_promotion(self):
        archive = _package(
            {
                "id": "fonte_teste",
                "version": "2026.10.14",
                "strategy": "replace_file",
                "provides": ["fonte_teste"],
                "target": "normativos/fonte.txt",
                "payloads": {"file": "payload/fonte.txt"},
            },
            {"payload/fonte.txt": b"conteudo"},
        )
        package = self._package_descriptor(
            "fonte_teste",
            "replace_file",
            archive,
            version="2026.10.14",
            target="normativos/fonte.txt",
            source_date="2026-10-14",
            source_reference="Fonte oficial de teste",
            minimum_plugin_version="0.9.5",
            maximum_plugin_version="0.9.5",
            database_schema_version=SCHEMA_VERSION,
            package_manifest_schema_version=1,
        )

        with self.assertRaisesRegex(UpdateError, "manifesto diverge"):
            LocalUpdater(
                self.root,
                self.database,
                self._client({package.url: archive}),
            ).apply(package)

        self.assertFalse((self.root / "normativos" / "fonte.txt").exists())

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

    def test_sicar_restore_preserves_each_backed_up_foreign_feature_count(self):
        target_relative = "car/AL/AL_AREA_IMOVEL.gpkg"
        target = self._write_geopackage(
            self.root / target_relative, ("AL-ANTERIOR", "PE-EXCECAO")
        )
        published = self._write_geopackage(
            self.root / "publicado.gpkg",
            ("AL-PUBLICADO", "PE-EXCECAO", "SP-EXCECAO"),
        )
        archive = _package(
            {
                "id": "sicar_imoveis_al",
                "version": "2026.09.21",
                "strategy": "replace_file",
                "target": target_relative,
                "foreign_feature_count": 2,
                "payloads": {"file": "payload/AL_AREA_IMOVEL.gpkg"},
            },
            {"payload/AL_AREA_IMOVEL.gpkg": published.read_bytes()},
        )
        package = self._package_descriptor(
            "sicar_imoveis_al",
            "replace_file",
            archive,
            target=target_relative,
            foreign_feature_count=2,
        )
        LocalUpdater(
            self.root, self.database, self._client({package.url: archive})
        ).apply(package)
        self.assertTrue(
            validate_geopackage(target, uf="AL", expected_foreign_features=2)
        )

        point = latest_restore_point(self.root, self.database)
        metadata_path = self.root / ".h" / Path(point.restore_id) / "restore.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["foreign_feature_count"], 1)
        metadata.pop("foreign_feature_count")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        restore_latest(self.root, self.database)
        self.assertTrue(
            validate_geopackage(target, uf="AL", expected_foreign_features=1)
        )

        undo = latest_restore_point(self.root, self.database)
        undo_metadata = json.loads(
            (self.root / ".h" / Path(undo.restore_id) / "restore.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(undo_metadata["foreign_feature_count"], 2)
        restore_latest(self.root, self.database)
        self.assertTrue(
            validate_geopackage(target, uf="AL", expected_foreign_features=2)
        )

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

    def test_restore_migrates_older_database_before_promotion(self):
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
        connection = sqlite3.connect(backup)
        try:
            connection.execute("DROP TABLE incra_modulo_fiscal")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
            connection.commit()
        finally:
            connection.close()

        restore_latest(self.root, self.database)

        connection = connect(self.database, readonly=True)
        try:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
            )
            self.assertGreater(
                connection.execute(
                    "SELECT COUNT(*) FROM incra_modulo_fiscal"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()

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
