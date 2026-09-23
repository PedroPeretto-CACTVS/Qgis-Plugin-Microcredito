"""Monta um pacote de atualização sem assinar nem transmitir dados.

A assinatura é aplicada ao catálogo pelo processo central, nunca por um
computador de analista e nunca com uma chave privada presente neste repositório.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

STRATEGIES = ("replace_file", "import_mma_mcr", "import_mte", "import_sicor")


def _identifier(value: str, field: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value):
        raise ValueError(f"{field} inválido.")
    return value


def _target(value: str) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ValueError("Destino fora da pasta de dados.")
    return candidate.as_posix()


def _payload_map(values: list[str]) -> dict[str, Path]:
    payloads = {}
    for value in values:
        if "=" not in value:
            raise ValueError("Cada --payload deve usar NOME=CAMINHO.")
        name, text_path = value.split("=", 1)
        _identifier(name, "Nome de payload")
        source = Path(text_path).resolve()
        if name in payloads or not source.is_file():
            raise ValueError(f"Payload inválido: {name}.")
        payloads[name] = source
    if not payloads:
        raise ValueError("Informe ao menos um --payload.")
    return payloads


def _value_map(values: list[str], field: str) -> dict[str, str]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Cada {field} deve usar NOME=VALOR.")
        name, text = value.split("=", 1)
        _identifier(name, f"Nome de {field}")
        if name in result or not re.fullmatch(r"[A-Za-z0-9_.:-]{3,100}", text):
            raise ValueError(f"{field} inválido para {name}.")
        result[name] = text
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_update_package(
    identifier: str,
    version: str,
    strategy: str,
    payloads: dict[str, Path],
    destination: Path,
    *,
    target: str | None = None,
    provides: tuple[str, ...] | None = None,
    payload_scopes: dict[str, str] | None = None,
    foreign_feature_count: int = 0,
) -> dict[str, object]:
    identifier, version = (
        _identifier(identifier, "Id"),
        _identifier(version, "Versão"),
    )
    if strategy not in STRATEGIES:
        raise ValueError("Estratégia inválida.")
    if strategy == "replace_file":
        if target is None or set(payloads) != {"file"}:
            raise ValueError(
                "replace_file exige --target e um único --payload file=CAMINHO."
            )
        target = _target(target)
    elif target is not None:
        raise ValueError("Somente replace_file aceita --target.")
    if foreign_feature_count < 0 or foreign_feature_count > 1000:
        raise ValueError("--foreign-feature-count deve estar entre 0 e 1000.")
    if foreign_feature_count and not identifier.startswith("sicar_imoveis_"):
        raise ValueError(
            "Exceções de UF só são permitidas para pacote estadual do SICAR."
        )
    provides = provides or (identifier,)
    provides = tuple(_identifier(value, "Base atendida") for value in provides)
    if len(set(provides)) != len(provides) or identifier not in provides:
        raise ValueError(
            "A lista de bases atendidas deve ser única e conter o id do pacote."
        )
    payload_scopes = payload_scopes or {}
    if not set(payload_scopes).issubset(payloads):
        raise ValueError("Há escopo definido para payload inexistente.")
    if strategy == "import_sicor":
        permitted = {"mutuarios", "propriedades", "operacoes", "complementos"}
        glebas = {
            name
            for name in payloads
            if re.fullmatch(r"glebas(?:_[A-Za-z0-9_.-]+)?", name)
        }
        if not {"mutuarios", "propriedades"}.issubset(payloads) or not set(
            payloads
        ).issubset(permitted | glebas):
            raise ValueError(
                "import_sicor exige mutuarios/propriedades e aceita somente "
                "payloads Sicor conhecidos."
            )
        if len(glebas) > 1 and not glebas.issubset(payload_scopes):
            raise ValueError(
                "Cada arquivo de geometria Sicor exige --payload-scope próprio."
            )
    elif payload_scopes:
        raise ValueError("Somente import_sicor aceita escopos por payload.")
    payload_members: dict[str, str] = {}
    manifest: dict[str, object] = {
        "id": identifier,
        "version": version,
        "strategy": strategy,
        "provides": list(provides),
        "payloads": payload_members,
    }
    if payload_scopes:
        manifest["payload_scopes"] = dict(sorted(payload_scopes.items()))
    if target:
        manifest["target"] = target
    if foreign_feature_count:
        manifest["foreign_feature_count"] = foreign_feature_count
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name, source in sorted(payloads.items()):
                member = f"payload/{name}/{source.name}"
                payload_members[name] = member
                compression = (
                    zipfile.ZIP_STORED
                    if source.suffix.lower() in (".gz", ".zip")
                    else zipfile.ZIP_DEFLATED
                )
                archive.write(source, member, compress_type=compression)
            archive.writestr(
                "package.json",
                json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                compress_type=zipfile.ZIP_DEFLATED,
            )
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("O pacote gerado não passou na verificação ZIP.")
            if json.loads(archive.read("package.json")) != manifest:
                raise ValueError("Manifesto divergente no pacote gerado.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    digest = _file_sha256(destination)
    return {
        "arquivo": str(destination),
        "sha256": digest,
        "size_bytes": destination.stat().st_size,
        "manifest": manifest,
    }
