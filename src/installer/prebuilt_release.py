"""Package publisher-prepared files for verified copy installation."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from installer.base_release import _validate_release_filename
from installer.verify import file_sha256
from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
    DATA_FILES,
    MANIFEST_MEMBER,
    SOURCE_CATALOG_MEMBER,
    SOURCE_SIGNATURE_MEMBER,
    PrebuiltReleaseBundle,
    validate_prebuilt_metadata,
)
from qgis_plugin_microcredito.infrastructure.updates import (
    MAX_CATALOG_BYTES,
    MAX_SIGNATURE_BYTES,
)


def build_prebuilt_release(
    candidate: Path, destination: Path, public_key_pem: str
) -> dict[str, object]:
    """Build a new complete file; no new digital-signature ceremony is required."""
    if destination.exists() or destination.is_symlink():
        raise ValueError("O destino deve ser novo.")
    if candidate.is_symlink() or candidate.is_junction():
        raise ValueError("A pasta candidata não pode ser um link.")
    expected = {
        *DATA_FILES,
        "snapshot.candidate.json",
        SOURCE_CATALOG_MEMBER,
        SOURCE_SIGNATURE_MEMBER,
    }
    actual = set()
    for path in candidate.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("A pasta candidata contém links.")
        if path.is_file():
            actual.add(path.relative_to(candidate).as_posix())
    if actual != expected:
        raise ValueError("A pasta candidata contém arquivos ausentes ou adicionais.")
    candidate_manifest = candidate / "snapshot.candidate.json"
    if not 0 < candidate_manifest.stat().st_size <= MAX_CATALOG_BYTES:
        raise ValueError("Manifesto candidato acima do limite.")
    manifest: dict[str, Any] = json.loads(candidate_manifest.read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "bases-plugin-prebuilt-candidate"
    ):
        raise ValueError("Formato de candidato pré-montado inválido.")
    manifest["format"] = "bases-plugin-prebuilt"
    manifest["issued_at"] = manifest.get("prepared_at")
    manifest.pop("status", None)
    manifest["verification"] = "integrity"
    if not isinstance(manifest["issued_at"], str):
        raise ValueError("Data de preparação inválida.")
    _validate_release_filename(destination, manifest["issued_at"])
    source = candidate / SOURCE_CATALOG_MEMBER
    signature = candidate / SOURCE_SIGNATURE_MEMBER
    if (
        not 0 < source.stat().st_size <= MAX_CATALOG_BYTES
        or not 0 < signature.stat().st_size <= MAX_SIGNATURE_BYTES
    ):
        raise ValueError("Metadados de origem ausentes ou acima do limite.")
    validate_prebuilt_metadata(
        json.dumps(manifest).encode(),
        source.read_bytes(),
        signature.read_bytes(),
        public_key_pem,
    )
    for name, entry in manifest["files"].items():
        path = candidate / name
        if (
            path.stat().st_size != entry["size_bytes"]
            or file_sha256(path) != entry["sha256"]
        ):
            raise ValueError(f"O candidato foi alterado após a preparação: {name}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".prebuilt-", suffix=".part", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            archive.writestr(
                MANIFEST_MEMBER,
                json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode(),
            )
            for name in (SOURCE_CATALOG_MEMBER, SOURCE_SIGNATURE_MEMBER):
                archive.write(candidate / name, name)
            for name in sorted(DATA_FILES):
                archive.write(candidate / name, f"data/{name}")
        verified = PrebuiltReleaseBundle(temporary, public_key_pem)
        if destination.exists() or destination.is_symlink():
            raise ValueError("O destino deve ser novo.")
        temporary.rename(destination)
        return {
            "arquivo": str(destination),
            "sha256": file_sha256(destination),
            "size_bytes": destination.stat().st_size,
            "files": len(DATA_FILES),
            "fingerprint": verified.fingerprint,
        }
    finally:
        temporary.unlink(missing_ok=True)
