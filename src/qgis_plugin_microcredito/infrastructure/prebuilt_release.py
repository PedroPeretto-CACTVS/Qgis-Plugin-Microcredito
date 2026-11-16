"""Read ready-to-copy bases with mandatory integrity, without a new signature."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import shutil
import stat
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from database.schema import SCHEMA_VERSION
from qgis_plugin_microcredito.domain.base_catalog import BASE_DEFINITIONS
from qgis_plugin_microcredito.infrastructure.downloads import UFS
from qgis_plugin_microcredito.infrastructure.updates import (
    MAX_CATALOG_BYTES,
    MAX_SIGNATURE_BYTES,
    PUBLISHER_PUBLIC_KEY_PEM,
    Catalog,
    UpdateError,
    _package_compatibility_error,
    _parse_catalog,
    verify_catalog_signature,
)

MANIFEST_MEMBER = "prebuilt.json"
SOURCE_CATALOG_MEMBER = "catalog.source.json"
SOURCE_SIGNATURE_MEMBER = "catalog.source.json.sig"
MAX_PREBUILT_BYTES = 512 * 1024**3
DATA_FILES = frozenset(
    {
        "car_microcredito.db",
        ".atualizacoes/estado.json",
        *(f"car/{uf}/{uf}_AREA_IMOVEL.gpkg" for uf in UFS),
        *(item.relative_path for item in BASE_DEFINITIONS if item.relative_path),
    }
)
EXPECTED_PACKAGE_IDS = frozenset(
    {
        "sicor_operacoes_car",
        "mma_mcr",
        "mte",
        *(f"sicar_imoveis_{uf.lower()}" for uf in UFS),
        *(item.identifier for item in BASE_DEFINITIONS if item.relative_path),
    }
)


def is_prebuilt_release(path: str | Path) -> bool:
    """Probe the explicit marker; malformed prebuilt archives must not fall back."""
    try:
        with zipfile.ZipFile(path) as archive:
            return MANIFEST_MEMBER in archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def _json_document(payload: bytes, label: str) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise UpdateError(f"{label} contém campos duplicados.")
            result[key] = value
        return result

    try:
        document = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"{label} inválido.") from exc
    if not isinstance(document, dict):
        raise UpdateError(f"{label} deve ser um objeto.")
    return document


def _entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = {}
    for entry in archive.infolist():
        name = entry.filename
        path = PurePosixPath(name)
        file_type = stat.S_IFMT(entry.external_attr >> 16)
        if (
            name in entries
            or "\\" in name
            or path.is_absolute()
            or path.as_posix() != name
            or ".." in path.parts
            or ":" in name
            or entry.is_dir()
            or entry.flag_bits & 1
            or file_type not in {0, stat.S_IFREG}
        ):
            raise UpdateError(
                "Bases pré-montadas contêm arquivo inseguro ou duplicado."
            )
        entries[name] = entry
    return entries


def _read_metadata(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    name: str,
    maximum: int,
) -> bytes:
    entry = entries.get(name)
    if entry is None or not 0 < entry.file_size <= maximum:
        raise UpdateError(f"Metadado ausente ou acima do limite: {name}.")
    return archive.read(entry)


def _validate_manifest(document: dict[str, Any], catalog: Catalog) -> None:
    if (
        type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
        or document.get("format") != "bases-plugin-prebuilt"
    ):
        raise UpdateError("Formato de bases pré-montadas incompatível.")
    if document.get("database_schema_version") != SCHEMA_VERSION:
        raise UpdateError("Esquema das bases pré-montadas incompatível.")
    if (
        catalog.schema_version != 3
        or {item.identifier for item in catalog.packages} != EXPECTED_PACKAGE_IDS
    ):
        raise UpdateError("As bases pré-montadas exigem catálogo v3 com os 36 pacotes.")
    for package in catalog.packages:
        reason = _package_compatibility_error(package)
        if reason:
            raise UpdateError(reason)
    expected_components = {
        identifier: {"package_id": package.identifier, "version": package.version}
        for package in catalog.packages
        for identifier in package.provides
    }
    if document.get("components") != expected_components:
        raise UpdateError("Componentes pré-montados divergem do catálogo de origem.")
    if document.get("channel") != catalog.channel:
        raise UpdateError("Canal pré-montado diverge da origem.")
    if (
        document.get("source_catalog_issued_at") != catalog.issued_at
        or document.get("source_catalog_expires_at") != catalog.expires_at
    ):
        raise UpdateError("Datas da origem divergem do catálogo.")
    try:
        issued = datetime.fromisoformat(document["issued_at"])
        if issued.tzinfo is None:
            raise ValueError("Fuso ausente")
        if issued < datetime.fromisoformat(catalog.issued_at) or issued > datetime.now(
            issued.tzinfo
        ):
            raise ValueError("Emissão incoerente")
    except (KeyError, TypeError, ValueError) as exc:
        raise UpdateError("Data da publicação pré-montada inválida.") from exc
    files = document.get("files")
    if not isinstance(files, dict) or set(files) != DATA_FILES:
        raise UpdateError(
            "A publicação deve conter exatamente os 35 arquivos de dados."
        )
    total = 0
    for descriptor in files.values():
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "size_bytes",
            "sha256",
        }:
            raise UpdateError("Descritor de arquivo pré-montado inválido.")
        size, digest = descriptor["size_bytes"], descriptor["sha256"]
        if (
            type(size) is not int
            or not 0 < size <= MAX_PREBUILT_BYTES
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise UpdateError("Tamanho ou hash de arquivo pré-montado inválido.")
        total += size
    if total > MAX_PREBUILT_BYTES:
        raise UpdateError("Conjunto pré-montado acima do limite de tamanho.")


def validate_prebuilt_metadata(
    manifest_payload: bytes,
    source_catalog: bytes,
    source_signature: bytes,
    public_key_pem: str,
) -> tuple[dict[str, Any], Catalog]:
    """Validate small release metadata before reading or compressing large data."""
    if (
        not 0 < len(manifest_payload) <= MAX_CATALOG_BYTES
        or not 0 < len(source_catalog) <= MAX_CATALOG_BYTES
        or not 0 < len(source_signature) <= MAX_SIGNATURE_BYTES
    ):
        raise UpdateError("Metadados pré-montados ausentes ou acima do limite.")
    manifest = _json_document(manifest_payload, "Manifesto pré-montado")
    verify_catalog_signature(source_catalog, source_signature, public_key_pem)
    catalog = _parse_catalog(source_catalog, allow_bundle_urls=True)
    if (
        manifest.get("source_catalog_sha256")
        != hashlib.sha256(source_catalog).hexdigest()
    ):
        raise UpdateError("Hash do catálogo de origem divergente.")
    _validate_manifest(manifest, catalog)
    return manifest, catalog


class PrebuiltReleaseBundle:
    """Validate complete snapshots; checksums do not authenticate derived data."""

    def __init__(
        self, path: str | Path, public_key_pem: str = PUBLISHER_PUBLIC_KEY_PEM
    ) -> None:
        self.path = Path(path).resolve()
        self.public_key_pem = public_key_pem
        try:
            with zipfile.ZipFile(self.path) as archive:
                self.manifest, self._catalog, entries = self._metadata(
                    archive, public_key_pem
                )
                for name, descriptor in self.manifest["files"].items():
                    entry = entries[f"data/{name}"]
                    self._copy_verified(archive, entry, descriptor, None)
                self.fingerprint = self._fingerprint(self.manifest)
        except UpdateError:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError, KeyError, TypeError) as exc:
            raise UpdateError(
                "Bases pré-montadas inválidas; nenhuma base foi instalada."
            ) from exc

    @staticmethod
    def _metadata(
        archive: zipfile.ZipFile, public_key_pem: str
    ) -> tuple[dict[str, Any], Catalog, dict[str, zipfile.ZipInfo]]:
        entries = _entries(archive)
        payload = _read_metadata(archive, entries, MANIFEST_MEMBER, MAX_CATALOG_BYTES)
        source = _read_metadata(
            archive, entries, SOURCE_CATALOG_MEMBER, MAX_CATALOG_BYTES
        )
        signature = _read_metadata(
            archive, entries, SOURCE_SIGNATURE_MEMBER, MAX_SIGNATURE_BYTES
        )
        manifest, catalog = validate_prebuilt_metadata(
            payload, source, signature, public_key_pem
        )
        expected = {
            MANIFEST_MEMBER,
            SOURCE_CATALOG_MEMBER,
            SOURCE_SIGNATURE_MEMBER,
            *(f"data/{name}" for name in DATA_FILES),
        }
        if set(entries) != expected:
            raise UpdateError(
                "Bases pré-montadas contêm arquivos ausentes ou adicionais."
            )
        for name, descriptor in manifest["files"].items():
            if entries[f"data/{name}"].file_size != descriptor["size_bytes"]:
                raise UpdateError(f"Tamanho divergente: {name}.")
        return manifest, catalog, entries

    @staticmethod
    def _fingerprint(manifest: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()

    def fetch_catalog(self) -> Catalog:
        """Return the source edition metadata, not a signature for the snapshot."""
        return self._catalog

    @staticmethod
    def _copy_verified(
        archive: zipfile.ZipFile,
        entry: zipfile.ZipInfo,
        descriptor: dict[str, Any],
        destination: Path | None,
    ) -> None:
        digest = hashlib.sha256()
        total = 0
        with archive.open(entry) as source:
            target = destination.open("xb") if destination else None
            try:
                for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
                    total += len(block)
                    if total > descriptor["size_bytes"]:
                        raise UpdateError(f"Tamanho divergente: {entry.filename}.")
                    digest.update(block)
                    if target:
                        target.write(block)
            finally:
                if target:
                    target.close()
        if total != descriptor["size_bytes"] or not hmac.compare_digest(
            digest.hexdigest(), descriptor["sha256"]
        ):
            raise UpdateError(f"Integridade divergente: {entry.filename}.")

    def extract_data(
        self, destination: Path, progress: Callable[[int, str], None] | None = None
    ) -> None:
        """Copy only data into a new private directory, verifying each byte again."""
        if destination.exists() or destination.is_symlink():
            raise UpdateError("O destino da cópia deve ser novo.")
        created = False
        try:
            with zipfile.ZipFile(self.path) as archive:
                manifest, _catalog, entries = self._metadata(
                    archive, self.public_key_pem
                )
                if self._fingerprint(manifest) != self.fingerprint:
                    raise UpdateError("O pacote pré-montado mudou desde a validação.")
                destination.mkdir(parents=True)
                created = True
                for index, (relative, descriptor) in enumerate(
                    manifest["files"].items(), 1
                ):
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._copy_verified(
                        archive, entries[f"data/{relative}"], descriptor, target
                    )
                    if progress:
                        progress(
                            int(index * 100 / len(DATA_FILES)),
                            f"Copiando bases prontas: {index}/{len(DATA_FILES)}",
                        )
        except Exception:
            if created:
                shutil.rmtree(destination)
            raise
