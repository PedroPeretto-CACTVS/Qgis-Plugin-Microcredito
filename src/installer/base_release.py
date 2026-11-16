"""Monta a publicação offline escolhida pelo usuário no plugin QGIS."""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from datetime import date
from pathlib import Path
from typing import cast

from qgis_plugin_microcredito.infrastructure.updates import (
    MAX_CATALOG_BYTES,
    MAX_SIGNATURE_BYTES,
    _parse_catalog,
    verify_catalog_signature,
)

_RELEASE_FILENAME = re.compile(
    r"bases-plugin-(?P<day>\d{2})-(?P<month>\d{2})-(?P<year>\d{4})\.carbases"
)


def _validate_release_filename(destination: Path, issued_at: str) -> None:
    match = _RELEASE_FILENAME.fullmatch(destination.name)
    if match is None:
        raise ValueError(
            "Nome de publicação inválido; use bases-plugin-DD-MM-AAAA.carbases."
        )
    try:
        release_date = date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError as exc:
        raise ValueError(
            "Nome de publicação inválido; use bases-plugin-DD-MM-AAAA.carbases."
        ) from exc
    catalog_date = date.fromisoformat(issued_at[:10])
    if release_date != catalog_date:
        raise ValueError(
            "A data no nome da publicação deve coincidir com a emissão do catálogo."
        )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_base_release(
    catalog_path: Path,
    signature_path: Path,
    packages: dict[str, Path],
    destination: Path,
    public_key_pem: str,
) -> dict[str, object]:
    """Agrupa somente artefatos já assinados e confere tudo novamente."""
    catalog_path = catalog_path.resolve()
    signature_path = signature_path.resolve()
    if not catalog_path.is_file() or not signature_path.is_file():
        raise ValueError("Informe catalog.json e catalog.json.sig existentes.")
    catalog_payload = catalog_path.read_bytes()
    signature = signature_path.read_bytes()
    if not 0 < len(catalog_payload) <= MAX_CATALOG_BYTES:
        raise ValueError("Tamanho do catálogo inválido.")
    if not 0 < len(signature) <= MAX_SIGNATURE_BYTES:
        raise ValueError("Tamanho da assinatura inválido.")
    verify_catalog_signature(catalog_payload, signature, public_key_pem)
    catalog = _parse_catalog(catalog_payload, allow_bundle_urls=True)
    catalog_document = cast(dict[str, object], json.loads(catalog_payload))
    declared_issued_at = cast(str, catalog_document["issued_at"])
    _validate_release_filename(destination, declared_issued_at)
    expected = {package.identifier for package in catalog.packages}
    if set(packages) != expected:
        raise ValueError("Informe exatamente os pacotes declarados pelo catálogo.")
    package_by_id = {package.identifier: package for package in catalog.packages}
    resolved: dict[str, Path] = {}
    for identifier, source in packages.items():
        path = source.resolve()
        descriptor = package_by_id[identifier]
        if not path.is_file():
            raise ValueError(f"Pacote ausente: {identifier}.")
        if path.stat().st_size != descriptor.size_bytes:
            raise ValueError(f"Tamanho divergente no pacote {identifier}.")
        if _file_sha256(path) != descriptor.sha256:
            raise ValueError(f"SHA-256 divergente no pacote {identifier}.")
        resolved[identifier] = path

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            archive.writestr(
                "catalog.json", catalog_payload, compress_type=zipfile.ZIP_DEFLATED
            )
            archive.writestr(
                "catalog.json.sig", signature, compress_type=zipfile.ZIP_STORED
            )
            for identifier, path in sorted(resolved.items()):
                archive.write(
                    path,
                    f"packages/{identifier}.zip",
                    compress_type=zipfile.ZIP_STORED,
                )
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("A publicação não passou na verificação ZIP.")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "arquivo": str(destination),
        "sha256": _file_sha256(destination),
        "size_bytes": destination.stat().st_size,
        "packages": len(resolved),
        "issued_at": catalog.issued_at,
        "channel": catalog.channel,
    }
