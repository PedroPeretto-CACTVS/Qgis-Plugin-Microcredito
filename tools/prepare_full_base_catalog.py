"""Gera o catálogo candidato offline a partir de 36 pacotes auditados."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from qgis_plugin_microcredito.domain.base_catalog import (
    BASE_DEFINITIONS,
    definition_for,
)

LOGICAL_IDS = {item.identifier for item in BASE_DEFINITIONS}


def _source_id(package_id: str) -> str:
    if package_id.startswith("sicar_imoveis_"):
        return "sicar_imoveis"
    return package_id


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} ausente.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} deve informar fuso horário.")
    return value


def prepare(
    audit_path: Path,
    evidence_path: Path,
) -> dict[str, object]:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if (
        audit.get("approved") is not True
        or audit.get("technical_packages") != 36
        or audit.get("logical_bases") != 11
    ):
        raise ValueError("A auditoria não aprovou o conjunto completo de bases.")
    sources = evidence.get("sources")
    if not isinstance(sources, dict) or set(sources) != LOGICAL_IDS:
        raise ValueError("A evidência deve cobrir exatamente as 11 bases lógicas.")
    issued_at = _timestamp(evidence.get("issued_at"), "issued_at")
    expires_at = _timestamp(evidence.get("expires_at"), "expires_at")
    publication = evidence.get("publication")
    compatibility = evidence.get("compatibility")
    if not isinstance(publication, dict) or not isinstance(compatibility, dict):
        raise ValueError("Publicação ou compatibilidade ausente.")

    packages = []
    for item in audit["packages"]:
        identifier = str(item["id"])
        source_id = _source_id(identifier)
        source = sources[source_id]
        if not isinstance(source, dict):
            raise ValueError(f"Evidência inválida para {source_id}.")
        checked_at = _timestamp(source.get("checked_at"), f"{source_id}.checked_at")
        source_date = source.get("source_date")
        source_reference = source.get("source_reference")
        official_page_url = source.get("official_page_url")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (source_date, source_reference, official_page_url)
        ):
            raise ValueError(f"Cadeia de evidências incompleta para {source_id}.")
        definition = definition_for(identifier)
        if definition is None:
            raise ValueError(f"Pacote sem definição funcional: {identifier}.")
        package = {
            "id": identifier,
            "label": definition.label,
            "version": item["version"],
            "strategy": item["strategy"],
            "provides": item["provides"],
            "source_date": source_date,
            "source_reference": source_reference,
            "source_evidence": {
                "official_page_url": official_page_url,
                "checked_at": checked_at,
            },
            "compatibility": compatibility,
            "url": f"carbases://packages/{identifier}.zip",
            "archive_path": item["path"],
        }
        artifact_url = source.get("official_artifact_url")
        if isinstance(artifact_url, str) and artifact_url.strip():
            package["source_evidence"]["official_artifact_url"] = artifact_url
        if item["strategy"] == "replace_file":
            package["target"] = item["target"]
            if item["foreign_feature_count"]:
                package["foreign_feature_count"] = item["foreign_feature_count"]
        if item["strategy"] in {"import_mma_mcr", "import_mte"}:
            validity_until = source.get("validity_until")
            if not isinstance(validity_until, str) or not validity_until:
                raise ValueError(f"Validade ausente para {source_id}.")
            package["validity_until"] = validity_until
        if item["strategy"] == "import_sicor":
            scope = source.get("scope")
            if not isinstance(scope, str) or not scope:
                raise ValueError("Escopo Sicor ausente.")
            package["scope"] = scope
        packages.append(package)

    priority = {"sicor_operacoes_car": 0, "mma_mcr": 1, "mte": 2}
    packages.sort(key=lambda item: (priority.get(str(item["id"]), 3), item["id"]))
    return {
        "schema_version": 3,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "publication": publication,
        "packages": packages,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    document = prepare(arguments.audit, arguments.evidence)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    packages = document["packages"]
    if not isinstance(packages, list):  # pragma: no cover - construído acima
        raise ValueError("Lista de pacotes inválida.")
    print(f"Catálogo completo preparado com {len(packages)} pacotes.")


if __name__ == "__main__":
    main()
