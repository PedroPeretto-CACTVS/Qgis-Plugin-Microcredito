"""Gera ZIPs do plugin QGIS a partir dos fontes atuais."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from installer.constants import PLUGIN_VERSION, repository_root

ROOT = repository_root()
PLUGIN_SOURCE = ROOT / "src" / "plugin"
LIB_PACKAGES = (
    ROOT / "src" / "qgis_plugin_microcredito",
    ROOT / "src" / "database",
)


def _collect_package(package_dir: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    parent = package_dir.parent
    for path in package_dir.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".typed"}:
            continue
        relative = path.relative_to(parent).as_posix()
        files[f"lib/{relative}"] = path.read_bytes()
    return files


def plugin_files(supreme: bool = False) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in PLUGIN_SOURCE.iterdir():
        if path.is_file() and path.suffix.lower() not in {".pyc"}:
            files[path.name] = path.read_bytes()
    for package in LIB_PACKAGES:
        files.update(_collect_package(package))
    if supreme:
        text = files["metadata.txt"].decode("utf-8")
        text = text.replace(
            "name=CAR Microcrédito", "name=CAR Microcrédito - Usuário Supremo"
        )
        files["metadata.txt"] = text.encode("utf-8")
        files["supreme_mode.txt"] = b"enabled\n"
        files["icon.svg"] = files["icon_option_car_check.svg"]
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files["manifesto_codigo.json"] = json.dumps(
        manifest, ensure_ascii=False, indent=2
    ).encode("utf-8")
    return files


def build(supreme: bool = False, destination: Path | None = None) -> Path:
    name = "car_microcredito_supremo_qgis" if supreme else "car_microcredito_qgis"
    destination = (
        Path(destination)
        if destination
        else ROOT / "dist" / f"{name}_{PLUGIN_VERSION}.zip"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = plugin_files(supreme)
    temporary = destination.with_suffix(".zip.part")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for relative, content in files.items():
                archive.writestr(name + "/" + relative, content)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip():
                raise ValueError("O ZIP gerado não passou na verificação.")
            for relative, content in files.items():
                if archive.read(name + "/" + relative) != content:
                    raise ValueError(f"Conteúdo divergente no pacote: {relative}")
        temporary.replace(destination)
        checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
        destination.with_suffix(".sha256.txt").write_text(
            checksum + "  " + destination.name + "\n", encoding="ascii"
        )
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build")
    parser.add_argument(
        "--variant", choices=("normal", "supremo", "all"), default="all"
    )
    parser.add_argument("--output-directory", type=Path, default=ROOT / "dist")
    args = parser.parse_args(argv)
    if args.variant in ("normal", "all"):
        print(
            build(
                destination=args.output_directory
                / f"car_microcredito_qgis_{PLUGIN_VERSION}.zip"
            )
        )
    if args.variant in ("supremo", "all"):
        print(
            build(
                supreme=True,
                destination=args.output_directory
                / f"car_microcredito_supremo_qgis_{PLUGIN_VERSION}.zip",
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
