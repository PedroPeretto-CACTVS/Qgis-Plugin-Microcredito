"""Package integrity checks equivalent to the retired Verificar pacote.ps1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from installer.constants import ENVIRONMENTAL, PLUGIN_VERSION, UFS


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(package_root: str | Path) -> None:
    root = Path(package_root).resolve()
    manifest_path = root / "MANIFESTO_SHA256.json"
    if not manifest_path.is_file():
        raise ValueError("Manifesto de integridade ausente.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root_prefix = str(root) + "/"
    for relative, expected in manifest.items():
        target = (root / relative).resolve()
        if not str(target).startswith(root_prefix) and target != root / relative:
            raise ValueError("Caminho fora do pacote no manifesto.")
        if not target.is_file():
            raise ValueError(f"Arquivo ausente: {relative}")
        if file_sha256(target) != str(expected).lower():
            raise ValueError(f"Arquivo alterado ou incompleto: {relative}")

    states = list((root / "arquivos" / "dados" / "car").rglob("*_AREA_IMOVEL.gpkg"))
    actual = tuple(sorted(path.stem.removesuffix("_AREA_IMOVEL") for path in states))
    if len(states) != 27 or set(actual) != set(UFS):
        raise ValueError("Conjunto de UFs incompleto ou duplicado.")
    for name in ENVIRONMENTAL:
        if not (root / "arquivos" / "dados" / "ambientais" / name).is_file():
            raise ValueError(f"Base ambiental ausente: {name}")
    metadata_files = list((root / "arquivos" / "plugin").rglob("metadata.txt"))
    if not metadata_files:
        raise ValueError("Plugin ausente.")
    text = metadata_files[0].read_text(encoding="utf-8")
    if f"version={PLUGIN_VERSION}" not in text:
        raise ValueError(f"Versao do plugin incorreta: esperado {PLUGIN_VERSION}")
