"""Small, genuinely signed complete release containing synthetic source data."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from database.schema import SCHEMA_VERSION
from installer.base_release import build_base_release
from installer.constants import ENVIRONMENTAL, UFS
from installer.update_package import build_update_package
from qgis_plugin_microcredito.application.mte_service import HEADERS
from update_process_support import TEST_PUBLIC_KEY_PEM, _sign

SYNTHETIC_CAR = "RR-0000000-00000000000000000000000000000000"
FIXTURE_VERSION = "2026.10.01-fixture"
FIXTURE_ISSUED_AT = "2026-10-01T12:00:00-03:00"


@dataclass(frozen=True)
class CompleteReleaseFixture:
    release: Path
    public_key: Path
    catalog: Path
    signature: Path
    packages: dict[str, Path]


def _write_geopackage(path: Path, uf: str | None = None) -> None:
    """Create structural GeoPackage fixtures, not a QGIS rendering fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT);
            CREATE TABLE gpkg_geometry_columns (table_name TEXT, srs_id INTEGER);
            CREATE TABLE gpkg_spatial_ref_sys (srs_id INTEGER);
            CREATE TABLE area (id INTEGER PRIMARY KEY, cod_imovel TEXT);
            INSERT INTO gpkg_contents VALUES ('area', 'features');
            INSERT INTO gpkg_geometry_columns VALUES ('area', 4674);
            INSERT INTO gpkg_spatial_ref_sys VALUES (4674);
            """
        )
        connection.execute(
            "INSERT INTO area VALUES (?, ?)",
            (1, f"{uf or 'RR'}-0000000-00000000000000000000000000000000"),
        )
        connection.commit()


def _write_csv(root: Path, name: str, content: str) -> Path:
    path = root / f"{name}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def write_complete_release(
    root: Path,
    *,
    property_car: str = SYNTHETIC_CAR,
    property_document: str = "00000000000",
    borrower_document: str = "00000000000",
    operation_key: tuple[str, str] = ("1", "1"),
    extra_property_cars: tuple[str, ...] = (),
) -> CompleteReleaseFixture:
    """Write 36 signed packages that can actually initialize an isolated root."""
    root.mkdir(parents=True, exist_ok=True)
    payload_root = root / "payloads"
    payload_root.mkdir()
    package_root = root / "packages"
    package_root.mkdir()
    packages: dict[str, Path] = {}
    descriptors: list[dict[str, object]] = []

    def add_package(
        identifier: str,
        strategy: str,
        payloads: dict[str, Path],
        *,
        target: str | None = None,
        provides: tuple[str, ...] | None = None,
    ) -> None:
        provided = provides or (identifier,)
        destination = package_root / f"{identifier}.zip"
        built = build_update_package(
            identifier,
            FIXTURE_VERSION,
            strategy,
            payloads,
            destination,
            target=target,
            provides=provided,
        )
        descriptor: dict[str, object] = {
            "id": identifier,
            "label": f"Fonte sintética {identifier}",
            "version": FIXTURE_VERSION,
            "strategy": strategy,
            "provides": list(provided),
            "source_date": "2026-10-01",
            "source_reference": f"fixture:{identifier}",
            "source_evidence": {
                "official_page_url": f"https://example.test/official/{identifier}",
                "official_artifact_url": f"https://example.test/official/{identifier}/data",
                "checked_at": "2026-10-01T11:00:00-03:00",
            },
            "compatibility": {
                "minimum_plugin_version": "0.9.5",
                "maximum_plugin_version": "0.9.5",
                "database_schema_version": SCHEMA_VERSION,
                "package_manifest_schema_version": 1,
            },
            "url": f"carbases://packages/{identifier}.zip",
            "sha256": built["sha256"],
            "size_bytes": built["size_bytes"],
        }
        if target is not None:
            descriptor["target"] = target
        if strategy in ("import_mma_mcr", "import_mte"):
            descriptor["validity_until"] = "2030-10-28"
        if strategy == "import_sicor":
            descriptor["scope"] = "2026-fixture-nacional"
        packages[identifier] = destination
        descriptors.append(descriptor)

    for uf in UFS:
        gpkg = payload_root / "car" / uf / f"{uf}_AREA_IMOVEL.gpkg"
        _write_geopackage(gpkg, uf)
        add_package(
            f"sicar_imoveis_{uf.lower()}",
            "replace_file",
            {"file": gpkg},
            target=f"car/{uf}/{uf}_AREA_IMOVEL.gpkg",
        )

    for filename in ENVIRONMENTAL:
        gpkg = payload_root / "ambientais" / filename
        _write_geopackage(gpkg)
        add_package(
            gpkg.stem,
            "replace_file",
            {"file": gpkg},
            target=f"ambientais/{filename}",
        )

    sicor_contents = {
        "mutuarios": f"REF_BACEN;CD_CPF_CNPJ\n1;{borrower_document}\n",
        "propriedades": (
            "REF_BACEN;NU_ORDEM;CD_CNPJ_CPF;CD_CAR\n"
            f"1;1;{property_document};{property_car}\n"
            + "".join(f"1;1;{property_document};{car}\n" for car in extra_property_cars)
        ),
        "operacoes": (
            "REF_BACEN;NU_ORDEM;DT_EMISSAO;CD_ESTADO\n"
            f"{operation_key[0]};{operation_key[1]};2026-10-01;RR\n"
        ),
        "complementos": "REF_BACEN;NU_ORDEM;CD_IBGE_MUNICIPIO\n1;1;0000000\n",
        "glebas": (
            "REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA\n"
            "1;1;1;POLYGON ((-50 -10,-49 -10,-49 -11,-50 -10))\n"
        ),
    }
    add_package(
        "sicor_operacoes_car",
        "import_sicor",
        {
            name: _write_csv(payload_root, name, content)
            for name, content in sicor_contents.items()
        },
        provides=("sicor_operacoes_car", "sicor_geometrias"),
    )
    add_package(
        "mma_mcr",
        "import_mma_mcr",
        {
            "file": _write_csv(
                payload_root,
                "mma_mcr",
                f"cod_imovel;status_imo;uf\n{SYNTHETIC_CAR};AT;RR\n",
            )
        },
    )
    add_package(
        "mte",
        "import_mte",
        {
            "file": _write_csv(
                payload_root,
                "mte",
                ";".join(HEADERS)
                + "\n1;2026;RR;Empregador sintetico;00000000000;Fixture;1;0000;"
                "2026-10-01;2026-10-01\n",
            )
        },
    )
    catalog = root / "catalog.json"
    catalog_bytes = json.dumps(
        {
            "schema_version": 3,
            "issued_at": FIXTURE_ISSUED_AT,
            "expires_at": "2030-10-28T12:00:00-03:00",
            "publication": {
                "channel": "homologacao",
                "prepared_by": "Fixture de testes",
                "change_reference": "PREBUILT-TEST-FIXTURE",
            },
            "packages": descriptors,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    catalog.write_bytes(catalog_bytes)
    signature = root / "catalog.json.sig"
    signature.write_bytes(_sign(catalog_bytes))
    public_key = root / "publicador-teste.pem"
    public_key.write_text(TEST_PUBLIC_KEY_PEM, encoding="ascii")
    release = root / "bases-plugin-01-10-2026.carbases"
    build_base_release(catalog, signature, packages, release, TEST_PUBLIC_KEY_PEM)
    return CompleteReleaseFixture(release, public_key, catalog, signature, packages)
