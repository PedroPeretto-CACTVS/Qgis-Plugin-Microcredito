"""Aplica e valida uma release Bases Plugin completa em raiz isolada."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import cast

from qgis_plugin_microcredito.infrastructure.updates import (
    BaseReleaseBundle,
    Catalog,
    CatalogClient,
    UpdateError,
    _parse_catalog,
    apply_catalog_release,
    compare_catalog,
)

EXPECTED_TECHNICAL_PACKAGES = 36
EXPECTED_SICAR_PACKAGES = 27
EXPECTED_ENVIRONMENTAL_PACKAGES = 6


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class DirectoryPackageClient:
    """Cliente local para homologar um candidato antes de sua aprovação."""

    def __init__(self, catalog: Catalog, audit_path: Path, package_root: Path) -> None:
        document = json.loads(audit_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("approved") is not True:
            raise ValueError("Auditoria de pacotes ausente ou não aprovada.")
        raw_packages = document.get("packages")
        if not isinstance(raw_packages, list):
            raise ValueError("Auditoria sem a lista de pacotes.")
        files: dict[str, Path] = {}
        for raw in raw_packages:
            if not isinstance(raw, dict):
                raise ValueError("Entrada inválida na auditoria.")
            identifier = raw.get("id")
            filename = raw.get("file")
            if not isinstance(identifier, str) or not isinstance(filename, str):
                raise ValueError("Pacote sem identificador ou arquivo auditado.")
            files[identifier] = (package_root / filename).resolve()
        expected = {item.identifier for item in catalog.packages}
        if set(files) != expected:
            raise ValueError("A auditoria não cobre exatamente o catálogo candidato.")
        self._sources = {
            (item.url, item.size_bytes, item.sha256): files[item.identifier]
            for item in catalog.packages
        }

    def download_package(
        self,
        url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        source = self._sources.get((url, expected_size, expected_sha256))
        if source is None or not source.is_file():
            raise UpdateError("Pacote candidato não pertence à auditoria aprovada.")
        if source.stat().st_size != expected_size or not hmac.compare_digest(
            _sha256(source), expected_sha256
        ):
            raise UpdateError("Pacote candidato diverge da auditoria aprovada.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with source.open("rb") as input_stream, destination.open("xb") as output:
            for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                output.write(block)
                total += len(block)
                if progress is not None:
                    progress(total, expected_size)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _database_counts(database: Path) -> dict[str, int]:
    queries = {
        "sicor_operacao": "SELECT COUNT(*) FROM sicor_operacao",
        "sicor_geometrias": "SELECT COUNT(*) FROM sicor_gleba_wkt",
        "mma_mcr": "SELECT COUNT(*) FROM mma_mcr",
        "mte": "SELECT COUNT(*) FROM trabalho_escravo",
    }
    connection = sqlite3.connect(database)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        counts = {
            name: int(connection.execute(query).fetchone()[0])
            for name, query in queries.items()
        }
    finally:
        connection.close()
    if version != 4:
        raise ValueError(f"Esquema inesperado depois da aplicação: {version}.")
    if any(value <= 0 for value in counts.values()):
        raise ValueError(f"Importação incompleta no banco isolado: {counts}.")
    return {"schema_version": version, **counts}


def homologate(
    catalog: Catalog,
    client: CatalogClient | BaseReleaseBundle,
    source_reference: Path,
    data_root: Path,
    database: Path,
    forbidden_roots: list[Path],
) -> dict[str, object]:
    root = data_root.resolve()
    db = database.resolve()
    if not root.is_dir() or not db.is_file() or not _inside(db, root):
        raise ValueError("A raiz isolada deve existir e conter o banco informado.")
    for forbidden in forbidden_roots:
        forbidden_root = forbidden.resolve()
        if root == forbidden_root or _inside(root, forbidden_root):
            raise ValueError(f"Raiz de homologação proibida: {root}.")

    if len(catalog.packages) != EXPECTED_TECHNICAL_PACKAGES:
        raise ValueError("A release não contém os 36 pacotes técnicos obrigatórios.")

    sicar = [item for item in catalog.packages if item.identifier.startswith("sicar_")]
    environmental = [
        item
        for item in catalog.packages
        if item.target is not None and item.target.startswith("ambientais/")
    ]
    if len(sicar) != EXPECTED_SICAR_PACKAGES:
        raise ValueError("A release não contém os 27 pacotes SICAR.")
    if len(environmental) != EXPECTED_ENVIRONMENTAL_PACKAGES:
        raise ValueError("A release não contém as seis camadas ambientais.")

    last_progress = -1

    def progress(value: int, message: str) -> None:
        nonlocal last_progress
        if value > last_progress:
            print(f"{value:3d}% {message}", flush=True)
            last_progress = value

    applied = apply_catalog_release(catalog, root, db, client, progress=progress)
    if len(applied) != EXPECTED_TECHNICAL_PACKAGES:
        raise ValueError(f"Foram aplicados somente {len(applied)} pacotes.")

    states = compare_catalog(catalog, root, db)
    unexpected_states = {
        item.identifier: item.state for item in states if item.state != "atual"
    }
    if unexpected_states:
        raise ValueError(f"Estados inesperados após aplicação: {unexpected_states}.")

    missing_targets = [
        item.target
        for item in catalog.packages
        if item.target is not None and not (root / item.target).is_file()
    ]
    if missing_targets:
        raise ValueError(f"Arquivos de base ausentes: {missing_targets}.")

    return {
        "approved": True,
        "source": str(source_reference.resolve()),
        "data_root": str(root),
        "database": str(db),
        "technical_packages": len(catalog.packages),
        "applied_packages": len(applied),
        "sicar_packages": len(sicar),
        "environmental_packages": len(environmental),
        "database_counts": _database_counts(db),
        "states": [asdict(item) for item in states],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--release", type=Path)
    source.add_argument("--catalog", type=Path)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--package-directory", type=Path)
    parser.add_argument("--forbid-root", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.release is not None:
        if arguments.public_key is None:
            parser.error("--public-key é obrigatório com --release.")
        public_key = arguments.public_key.read_text(encoding="ascii")
        release = BaseReleaseBundle(arguments.release, public_key)
        catalog = release.fetch_catalog()
        client: CatalogClient | BaseReleaseBundle = release
        source_reference = arguments.release
    else:
        if arguments.audit is None or arguments.package_directory is None:
            parser.error(
                "--audit e --package-directory são obrigatórios com --catalog."
            )
        catalog = _parse_catalog(arguments.catalog.read_bytes(), allow_bundle_urls=True)
        directory_client = DirectoryPackageClient(
            catalog, arguments.audit, arguments.package_directory
        )
        client = cast(CatalogClient, directory_client)
        source_reference = arguments.catalog
    result = homologate(
        catalog,
        client,
        source_reference,
        arguments.data_root,
        arguments.database,
        arguments.forbid_root,
    )
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
