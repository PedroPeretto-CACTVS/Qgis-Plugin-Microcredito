"""Reconstrói pacotes legados com o manifesto vigente, sem alterar payloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from installer.update_package import _identifier, build_update_package


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Nome de payload inválido.")
    candidate = PurePosixPath(value.replace("\\", "/"))
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in ("", ".") for part in candidate.parts)
    ):
        raise ValueError("Payload fora da pasta permitida.")
    return candidate.as_posix()


def _extract_payloads(
    source: Path, directory: Path
) -> tuple[dict[str, object], dict[str, Path]]:
    with zipfile.ZipFile(source) as archive:
        entries: dict[str, zipfile.ZipInfo] = {}
        for entry in archive.infolist():
            name = _safe_member(entry.filename)
            if name in entries:
                raise ValueError(f"Nome duplicado em {source.name}: {name}")
            if entry.is_dir() or entry.flag_bits & 0x1:
                raise ValueError(f"Entrada inválida em {source.name}: {name}")
            entries[name] = entry
        package_entry = entries.get("package.json")
        if package_entry is None:
            raise ValueError(f"Pacote sem manifesto: {source.name}")
        manifest = json.loads(archive.read(package_entry).decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError(f"Manifesto inválido: {source.name}")
        payload_members = manifest.get("payloads")
        if not isinstance(payload_members, dict) or not payload_members:
            raise ValueError(f"Pacote sem payloads: {source.name}")
        for name in payload_members:
            if not isinstance(name, str):
                raise ValueError(f"Nome de payload inválido: {source.name}")
            _identifier(name, "Nome de payload")
        payloads: dict[str, Path] = {}
        expected = {"package.json"}
        for name, raw_member in payload_members.items():
            member = _safe_member(raw_member)
            payload_entry = entries.get(member)
            if payload_entry is None or not member.startswith("payload/"):
                raise ValueError(f"Payload ausente: {source.name}/{name}")
            expected.add(member)
            suffix = PurePosixPath(member).suffix
            destination = directory / f"{name}{suffix}"
            if not destination.resolve().is_relative_to(directory.resolve()):
                raise ValueError("Payload fora da pasta permitida.")
            with (
                archive.open(payload_entry) as input_stream,
                destination.open("xb") as output,
            ):
                shutil.copyfileobj(input_stream, output, length=1024 * 1024)
            if destination.stat().st_size != payload_entry.file_size:
                raise ValueError(f"Payload truncado: {source.name}/{name}")
            payloads[name] = destination
        if set(entries) != expected:
            raise ValueError(f"Conteúdo não declarado: {source.name}")
        if archive.testzip() is not None:
            raise ValueError(f"CRC inválido: {source.name}")
    return manifest, payloads


def upgrade_package(
    source: Path, destination: Path, work_root: Path
) -> dict[str, object]:
    old_hash = _sha256(source)
    with tempfile.TemporaryDirectory(prefix="rebuild-", dir=work_root) as temporary:
        manifest, payloads = _extract_payloads(source, Path(temporary))
        if (
            manifest.get("schema_version") == 1
            and source.resolve() == destination.resolve()
        ):
            return {
                "file": destination.name,
                "status": "already_current",
                "sha256": old_hash,
                "size_bytes": source.stat().st_size,
            }
        target = manifest.get("target")
        if target is not None and not isinstance(target, str):
            raise ValueError(f"Destino inválido: {source.name}")
        raw_provides = manifest.get("provides") or ()
        if not isinstance(raw_provides, (list, tuple)) or not all(
            isinstance(item, str) for item in raw_provides
        ):
            raise ValueError(f"Lista provides inválida: {source.name}")
        provides = tuple(str(item) for item in raw_provides)
        raw_scopes = manifest.get("payload_scopes") or {}
        if not isinstance(raw_scopes, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_scopes.items()
        ):
            raise ValueError(f"Escopos de payload inválidos: {source.name}")
        payload_scopes = {str(key): str(value) for key, value in raw_scopes.items()}
        raw_foreign_count = manifest.get("foreign_feature_count", 0)
        if not isinstance(raw_foreign_count, int):
            raise ValueError(f"Contagem de feições inválida: {source.name}")
        result = build_update_package(
            str(manifest.get("id")),
            str(manifest.get("version")),
            str(manifest.get("strategy")),
            payloads,
            destination,
            target=target,
            provides=provides,
            payload_scopes=payload_scopes,
            foreign_feature_count=raw_foreign_count,
        )
    return {
        "file": destination.name,
        "status": "rebuilt",
        "previous_sha256": old_hash,
        "sha256": result["sha256"],
        "size_bytes": result["size_bytes"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--work-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    directory = arguments.directory.resolve()
    work_root = arguments.work_directory.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    results = [
        upgrade_package(path, path, work_root)
        for path in sorted(directory.glob("*.zip"))
    ]
    report = {
        "schema_version": 1,
        "packages": len(results),
        "rebuilt": sum(item["status"] == "rebuilt" for item in results),
        "already_current": sum(item["status"] == "already_current" for item in results),
        "results": results,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "packages": report["packages"],
                "rebuilt": report["rebuilt"],
                "already_current": report["already_current"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
