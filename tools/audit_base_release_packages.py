"""Audita o conjunto completo de pacotes técnicos de um Bases Plugin."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from qgis_plugin_microcredito.domain.base_catalog import (
    BASE_DEFINITIONS,
    definition_for,
)

UFS = (
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
)
ENVIRONMENTAL_IDS = {
    item.identifier for item in BASE_DEFINITIONS if item.relative_path is not None
}
EXPECTED_PACKAGE_IDS = {
    "sicor_operacoes_car",
    "mma_mcr",
    "mte",
    *ENVIRONMENTAL_IDS,
    *(f"sicar_imoveis_{uf.lower()}" for uf in UFS),
}
EXPECTED_LOGICAL_IDS = {item.identifier for item in BASE_DEFINITIONS}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(name: str) -> str:
    candidate = PurePosixPath(name.replace("\\", "/"))
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in ("", ".") for part in candidate.parts)
    ):
        raise ValueError(f"Membro ZIP inseguro: {name}")
    return candidate.as_posix()


def _logical_ids(identifier: str, provides: list[str]) -> set[str]:
    if identifier.startswith("sicar_imoveis_"):
        return {"sicar_imoveis"}
    return set(provides)


def _require_payload_suffixes(
    path: Path,
    payload_members: dict[str, str],
    expected_payloads: set[str],
    allowed_suffixes: set[str],
) -> None:
    if set(payload_members) != expected_payloads:
        raise ValueError(f"Payloads incompatíveis com a estratégia: {path.name}")
    for payload_name, member in payload_members.items():
        suffix = PurePosixPath(member).suffix.lower()
        if suffix not in allowed_suffixes:
            expected = ", ".join(sorted(allowed_suffixes))
            raise ValueError(
                f"Formato de payload incompatível em {path.name}/{payload_name}; "
                f"esperado: {expected}."
            )


def _audit_package(path: Path) -> dict[str, object]:
    payload_members: dict[str, str] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            entries: dict[str, zipfile.ZipInfo] = {}
            for entry in archive.infolist():
                name = _safe_member(entry.filename)
                if name in entries:
                    raise ValueError(f"Nome duplicado em {path.name}: {name}")
                if entry.is_dir() or entry.flag_bits & 0x1:
                    raise ValueError(f"Entrada inválida em {path.name}: {name}")
                entries[name] = entry
            package_entry = entries.get("package.json")
            if package_entry is None:
                raise ValueError(f"Pacote sem package.json: {path.name}")
            manifest = json.loads(archive.read(package_entry).decode("utf-8"))
            if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
                raise ValueError(f"Manifesto incompatível: {path.name}")
            identifier = manifest.get("id")
            version = manifest.get("version")
            strategy = manifest.get("strategy")
            provides = manifest.get("provides")
            payloads = manifest.get("payloads")
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", identifier
            ):
                raise ValueError(f"Id inválido: {path.name}")
            if not isinstance(version, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", version
            ):
                raise ValueError(f"Versão inválida: {path.name}")
            if not isinstance(provides, list) or not provides:
                raise ValueError(f"Pacote sem bases atendidas: {path.name}")
            if not isinstance(payloads, dict) or not payloads:
                raise ValueError(f"Pacote sem payload: {path.name}")
            members = set()
            extracted_bytes = 0
            for payload_name, member in payloads.items():
                if not isinstance(payload_name, str) or not isinstance(member, str):
                    raise ValueError(f"Payload inválido: {path.name}")
                member = _safe_member(member)
                payload_entry = entries.get(member)
                if payload_entry is None or not member.startswith("payload/"):
                    raise ValueError(f"Payload ausente: {path.name}/{payload_name}")
                if payload_entry.file_size <= 0:
                    raise ValueError(f"Payload vazio: {path.name}/{payload_name}")
                payload_members[payload_name] = member
                members.add(member)
                extracted_bytes += payload_entry.file_size
            if set(entries) != {"package.json", *members}:
                raise ValueError(f"Conteúdo não declarado: {path.name}")
            if archive.testzip() is not None:
                raise ValueError(f"CRC inválido: {path.name}")
    except (
        OSError,
        zipfile.BadZipFile,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise ValueError(f"ZIP inválido: {path.name}") from exc

    expected_provides = {
        "import_sicor": {"sicor_operacoes_car", "sicor_geometrias"},
        "import_mma_mcr": {"mma_mcr"},
        "import_mte": {"mte"},
    }.get(str(strategy))
    if strategy == "replace_file":
        definition = definition_for(identifier)
        if (
            definition is None
            or definition.relative_path is None
            or manifest.get("target") != definition.relative_path
            or provides != [identifier]
            or set(payloads) != {"file"}
        ):
            raise ValueError(f"Destino ou cobertura divergente: {path.name}")
        _require_payload_suffixes(path, payload_members, {"file"}, {".gpkg"})
    elif expected_provides is None or set(provides) != expected_provides:
        raise ValueError(f"Estratégia ou cobertura divergente: {path.name}")
    elif strategy == "import_mma_mcr":
        _require_payload_suffixes(path, payload_members, {"file"}, {".csv", ".gz"})
    elif strategy == "import_mte":
        _require_payload_suffixes(path, payload_members, {"file"}, {".csv"})
    elif strategy == "import_sicor":
        required = {"mutuarios", "propriedades", "operacoes", "complementos"}
        geometry = {
            name
            for name in payload_members
            if re.fullmatch(r"glebas(?:_[A-Za-z0-9_.-]+)?", name)
        }
        if not required.issubset(payload_members) or not geometry:
            raise ValueError(f"Pacote Sicor incompleto: {path.name}")
        _require_payload_suffixes(
            path,
            payload_members,
            required | geometry,
            {".csv", ".gz"},
        )
    return {
        "id": identifier,
        "file": path.name,
        "path": str(path.resolve()),
        "version": version,
        "strategy": strategy,
        "provides": provides,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "extracted_bytes": extracted_bytes,
        "logical_ids": sorted(_logical_ids(identifier, provides)),
        "target": manifest.get("target"),
        "foreign_feature_count": manifest.get("foreign_feature_count", 0),
    }


def audit(directory: Path) -> dict[str, object]:
    paths = sorted(directory.resolve().glob("*.zip"))
    packages = [_audit_package(path) for path in paths]
    identifiers = [str(item["id"]) for item in packages]
    duplicate_ids = sorted(
        identifier
        for identifier in set(identifiers)
        if identifiers.count(identifier) > 1
    )
    if duplicate_ids:
        raise ValueError(f"Pacotes duplicados: {', '.join(duplicate_ids)}")
    found = set(identifiers)
    missing = sorted(EXPECTED_PACKAGE_IDS - found)
    extra = sorted(found - EXPECTED_PACKAGE_IDS)
    if missing or extra:
        raise ValueError(
            f"Conjunto incompleto; ausentes={missing or 'nenhum'}; extras={extra or 'nenhum'}."
        )
    logical: set[str] = set()
    total_size_bytes = 0
    total_extracted_bytes = 0
    for package in packages:
        logical_ids = package["logical_ids"]
        size_bytes = package["size_bytes"]
        extracted_bytes = package["extracted_bytes"]
        if (
            not isinstance(logical_ids, list)
            or not all(isinstance(value, str) for value in logical_ids)
            or not isinstance(size_bytes, int)
            or not isinstance(extracted_bytes, int)
        ):
            raise ValueError("Relatório interno de pacote inválido.")
        logical.update(logical_ids)
        total_size_bytes += size_bytes
        total_extracted_bytes += extracted_bytes
    if logical != EXPECTED_LOGICAL_IDS:
        raise ValueError("Os pacotes não cobrem exatamente as 11 bases lógicas.")
    return {
        "schema_version": 1,
        "approved": True,
        "technical_packages": len(packages),
        "logical_bases": len(logical),
        "total_size_bytes": total_size_bytes,
        "total_extracted_bytes": total_extracted_bytes,
        "logical_ids": sorted(logical),
        "packages": packages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = audit(arguments.directory)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "approved": report["approved"],
                "technical_packages": report["technical_packages"],
                "logical_bases": report["logical_bases"],
                "total_size_bytes": report["total_size_bytes"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
