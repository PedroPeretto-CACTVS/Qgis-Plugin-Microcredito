"""Prepare publisher-owned data snapshots from complete signed releases."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from database.schema import SCHEMA_VERSION
from installer.constants import ENVIRONMENTAL, PLUGIN_VERSION, UFS
from installer.verify import file_sha256
from qgis_plugin_microcredito.application.backup_service import snapshot_database
from qgis_plugin_microcredito.application.prebuilt_data import (
    validate_prebuilt_database,
)
from qgis_plugin_microcredito.infrastructure.downloads import validate_geopackage
from qgis_plugin_microcredito.infrastructure.updates import (
    BaseReleaseBundle,
    Catalog,
    apply_catalog_release,
    compare_catalog,
)


class SnapshotFile(TypedDict):
    sha256: str
    size_bytes: int


def _complete_catalog(catalog: Catalog) -> None:
    expected = {
        "sicor_operacoes_car",
        "mma_mcr",
        "mte",
        *(Path(name).stem for name in ENVIRONMENTAL),
        *(f"sicar_imoveis_{uf.lower()}" for uf in UFS),
    }
    if {package.identifier for package in catalog.packages} != expected:
        raise ValueError("A preparação exige os 36 pacotes de todas as 11 bases.")
    if catalog.schema_version != 3:
        raise ValueError("O catálogo deve conter evidências e compatibilidade v3.")


def _sicor_link_coverage(database: Path) -> dict[str, int]:
    """Count formal CAR links in this publication, never infer cadastral identity."""
    formal_car = (
        "length(p.car_normalizado) = 41 AND substr(p.car_normalizado, 1, 2) IN ("
        + ",".join("?" for _ in UFS)
        + ") AND p.car_normalizado GLOB ?"
    )
    parameters = (*UFS, "[A-Z][A-Z]" + "[0-9]" * 7 + "[0-9A-F]" * 32)
    with closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    ) as connection:
        connection.execute("PRAGMA query_only=ON")
        total, formal, unavailable = connection.execute(
            f"""SELECT COUNT(*), COALESCE(SUM({formal_car}), 0),
                       COALESCE(SUM(coalesce(p.car_normalizado, '') = ''), 0)
                  FROM ativo_sicor_propriedade p""",
            parameters,
        ).fetchone()
        direct_documents = borrower_documents = with_operation = usable = 0
        # The all-unavailable national edition needs no millions of link lookups.
        if formal:
            direct_documents, borrower_documents, with_operation, usable = (
                connection.execute(
                    f"""WITH properties AS (
                           SELECT length(coalesce(p.documento_normalizado, ''))
                                      IN (11, 14)
                                  AND p.documento_normalizado NOT GLOB '*[^0-9]*'
                                  AND p.documento_mascarado = 0 AS direct_document,
                                  EXISTS (SELECT 1 FROM ativo_sicor_mutuario m
                                           WHERE m.ref_bacen = p.ref_bacen
                                             AND length(m.documento_normalizado) IN (11, 14)
                                             AND m.documento_normalizado NOT GLOB '*[^0-9]*'
                                             AND m.documento_mascarado = 0) AS borrower_document,
                                  EXISTS (SELECT 1 FROM ativo_sicor_operacao o
                                           WHERE o.ref_bacen = p.ref_bacen
                                             AND o.nu_ordem = p.nu_ordem) AS with_operation
                             FROM ativo_sicor_propriedade p
                            WHERE {formal_car}
                       )
                       SELECT COALESCE(SUM(direct_document), 0),
                              COALESCE(SUM(borrower_document), 0),
                              COALESCE(SUM(with_operation), 0),
                              COALESCE(SUM((direct_document OR borrower_document)
                                           AND with_operation), 0)
                         FROM properties""",
                    parameters,
                ).fetchone()
            )
    coverage = {
        "active_properties": total,
        "properties_with_formal_car": formal,
        "properties_with_unavailable_car": unavailable,
        "properties_with_malformed_car": total - formal - unavailable,
        "formal_car_properties_with_direct_document": direct_documents,
        "formal_car_properties_with_borrower_document": borrower_documents,
        "formal_car_properties_with_compatible_operation": with_operation,
        "properties_with_usable_link": usable,
    }
    if not usable:
        raise ValueError(
            "Preparação bloqueada: nenhum vínculo CAR–documento com operação "
            f"compatível. Cobertura Sicor: {json.dumps(coverage, sort_keys=True)}."
        )
    return coverage


def _export_data(
    source: Path, destination: Path, catalog: Catalog
) -> dict[str, SnapshotFile]:
    database = source / "car_microcredito.db"
    validate_prebuilt_database(database)
    if any(
        status.state != "atual" for status in compare_catalog(catalog, source, database)
    ):
        raise ValueError("A preparação não comprovou todas as versões do catálogo.")
    destination.mkdir()
    snapshot_database(database, destination / database.name)
    # The deliverable must be a standalone SQLite file, with no WAL/SHM state.
    with closing(sqlite3.connect(destination / database.name)) as exported:
        exported.execute("PRAGMA journal_mode=DELETE")
    for package in catalog.packages:
        if package.strategy != "replace_file":
            continue
        relative = package.target
        if relative is None:
            raise ValueError("Pacote geográfico sem destino.")
        origin = source / relative
        target = destination / relative
        state = (
            package.identifier.removeprefix("sicar_imoveis_").upper()
            if package.identifier.startswith("sicar_imoveis_")
            else None
        )
        validate_geopackage(
            origin, state, expected_foreign_features=package.foreign_feature_count
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        origin.rename(target)
    registry = destination / ".atualizacoes" / "estado.json"
    registry.parent.mkdir()
    shutil.copyfile(source / ".atualizacoes" / "estado.json", registry)
    validate_prebuilt_database(destination / database.name)
    expected_files = {
        database.name,
        ".atualizacoes/estado.json",
        *(f"car/{uf}/{uf}_AREA_IMOVEL.gpkg" for uf in UFS),
        *(f"ambientais/{name}" for name in ENVIRONMENTAL),
    }
    actual_files = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("O conjunto pré-montado não contém os 35 arquivos esperados.")
    return {
        name: {
            "sha256": file_sha256(destination / name),
            "size_bytes": (destination / name).stat().st_size,
        }
        for name in sorted(expected_files)
    }


def prepare_prebuilt_bases(
    release_path: Path,
    destination: Path,
    public_key_pem: str,
    *,
    progress: Callable[[int, str], None] | None = None,
) -> Path:
    """Import once at the publisher and export an unsigned, complete candidate.

    Input is a signed release, never an analyst's active database. Its signature
    authenticates the source packages only: the derived candidate is delivered
    with mandatory integrity checks and still needs client homologation.
    """
    if destination.exists() or destination.is_symlink():
        raise ValueError("O destino deve ser novo; nenhuma base foi substituída.")
    # Authenticate and check coverage before creating any output scaffolding.
    original = BaseReleaseBundle(release_path, public_key_pem)
    _complete_catalog(original.fetch_catalog())
    destination = destination.absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".prebuilt-", dir=destination.parent
    ) as directory:
        work = Path(directory)
        if progress:
            progress(0, "Preparando cópia isolada da publicação assinada…")
        local_release = work / "source.carbases"
        shutil.copyfile(original.path, local_release)
        release = BaseReleaseBundle(local_release, public_key_pem)
        catalog = release.fetch_catalog()
        _complete_catalog(catalog)
        source = work / "imported"
        apply_catalog_release(
            catalog,
            source,
            source / "car_microcredito.db",
            release,
            progress=(lambda value, message: progress(int(value * 0.75), message))
            if progress
            else None,
        )
        if progress:
            progress(75, "Conferindo banco e cobertura das bases pré-montadas…")
        sicor_coverage = _sicor_link_coverage(source / "car_microcredito.db")
        candidate = work / "candidate"
        files = _export_data(source, candidate, catalog)
        with zipfile.ZipFile(local_release) as archive:
            catalog_payload = archive.read("catalog.json")
            (candidate / "catalog.source.json").write_bytes(catalog_payload)
            (candidate / "catalog.source.json.sig").write_bytes(
                archive.read("catalog.json.sig")
            )
        components = {
            identifier: {"package_id": package.identifier, "version": package.version}
            for package in catalog.packages
            for identifier in package.provides
        }
        manifest = {
            "schema_version": 1,
            "format": "bases-plugin-prebuilt-candidate",
            "status": "requires_client_homologation",
            "prepared_at": datetime.now(UTC).isoformat(),
            "source_catalog_issued_at": catalog.issued_at,
            "source_catalog_expires_at": catalog.expires_at,
            "source_catalog_sha256": file_sha256(candidate / "catalog.source.json"),
            "channel": catalog.channel,
            "database_schema_version": SCHEMA_VERSION,
            "built_with_plugin_version": PLUGIN_VERSION,
            "components": components,
            "sicor_link_coverage": {
                "criterion": "at_least_one_explicit_car_document_link_with_matching_operation",
                "unit": "active_property_rows",
                "minimum_required": 1,
                "full_coverage_required": False,
                "counts": sicor_coverage,
            },
            "files": files,
        }
        (candidate / "snapshot.candidate.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        if destination.exists() or destination.is_symlink():
            raise ValueError("O destino deve ser novo; nenhuma base foi substituída.")
        candidate.rename(destination)
    if progress:
        progress(
            100, "Candidato pré-montado preparado para verificação de integridade."
        )
    return destination / "snapshot.candidate.json"
