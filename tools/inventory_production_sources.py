"""Inventaria as fontes locais que poderão formar o catálogo de produção.

O relatório não lê conteúdo de CPF/CNPJ/CAR e não transmite arquivos. Ele
registra somente nomes relativos, tamanhos e a divisão necessária para que cada
ativo permaneça abaixo do limite de 2 GiB do GitHub Release.

Prontidão técnica não equivale a autorização de publicação. O pacote
Sicor recebe um portão separado de proteção de dados porque espelhá-lo cria
uma nova custódia, ainda que os arquivos de origem sejam microdados públicos.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

GITHUB_RELEASE_ASSET_LIMIT = 2 * 1024 * 1024 * 1024
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
ENVIRONMENTAL = {
    "embargos": "ambientais/embargos.gpkg",
    "terras_indigenas": "ambientais/terras_indigenas.gpkg",
    "territorios_quilombolas": "ambientais/territorios_quilombolas.gpkg",
    "unidades_conservacao": "ambientais/unidades_conservacao.gpkg",
    "florestas_publicas": "ambientais/florestas_publicas.gpkg",
    "desmatamento_pos_2020": "ambientais/desmatamento_pos_2020.gpkg",
}
SICOR = {
    "mutuarios": "sicor/SICOR_MUTUARIOS_CONTRAT.gz",
    "propriedades": "sicor/SICOR_PROPRIEDADES_CONTRAT.gz",
    "operacoes": "sicor/SICOR_OPERACAO_BASICA_CONTRAT.gz",
    "complementos": "sicor/SICOR_COMPLEMENTO_OPERACAO_BASICA_CONTRAT.gz",
    "glebas_legado": "sicor/SICOR_GLEBAS_CONTRAT.gz",
    "glebas_2020": "sicor/SICOR_GLEBAS_WKT_2020.gz",
    "glebas_2021": "sicor/SICOR_GLEBAS_WKT_2021.gz",
    "glebas_2022": "sicor/SICOR_GLEBAS_WKT_2022.gz",
    "glebas_2023": "sicor/SICOR_GLEBAS_WKT_2023.gz",
    "glebas_2024": "sicor/SICOR_GLEBAS_WKT_2024.gz",
    "glebas_2025": "sicor/SICOR_GLEBAS_WKT_2025.gz",
    "glebas_2026": "sicor/SICOR_GLEBAS_WKT_2026.gz",
}


def _source(root: Path, relative: str) -> dict[str, object]:
    path = root / Path(relative)
    size = path.stat().st_size if path.is_file() else None
    return {
        "path": relative.replace("\\", "/"),
        "present": path.is_file(),
        "size_bytes": size,
        "fits_github_release": size is not None and size < GITHUB_RELEASE_ASSET_LIMIT,
    }


def inventory(data_root: Path, mte_source: Path | None = None) -> dict[str, object]:
    root = data_root.resolve()
    packages: list[dict[str, object]] = []
    sicor_sources = [
        _source(root, relative) | {"payload": name} for name, relative in SICOR.items()
    ]
    sicor_total = sum(int(item["size_bytes"] or 0) for item in sicor_sources)
    sicor_complete = all(bool(item["present"]) for item in sicor_sources)
    packages.append(
        {
            "id": "sicor_operacoes_car",
            "strategy": "import_sicor",
            "provides": ["sicor_operacoes_car", "sicor_geometrias"],
            "official_source": "https://www.bcb.gov.br/estabilidadefinanceira/tabelas-credito-rural-proagro",
            "distribution_preference": "download_from_official_source",
            "contains_potential_personal_data": True,
            "publication_authorization": "required_before_mirroring",
            "sources": sicor_sources,
            "combined_source_bytes": sicor_total,
            "combined_sources_fit_github_release": (
                sicor_total < GITHUB_RELEASE_ASSET_LIMIT if sicor_complete else None
            ),
        }
    )

    mma_candidates = (
        sorted((root / "mma").glob("*.zip")) if (root / "mma").is_dir() else []
    )
    mma = (
        mma_candidates[-1]
        if mma_candidates
        else root / "mma" / "PUBLICACAO_MMA_A_DEFINIR.zip"
    )
    packages.append(
        {
            "id": "mma_mcr",
            "strategy": "import_mma_mcr",
            "provides": ["mma_mcr"],
            "sources": [_source(root, mma.relative_to(root).as_posix())],
        }
    )
    if mte_source is None:
        default_mte = "normativos/cadastro_empregadores_trabalho_escravo.csv"
        mte_entry = _source(root, default_mte)
    else:
        resolved = mte_source.resolve()
        mte_entry = {
            "path": str(resolved),
            "present": resolved.is_file(),
            "size_bytes": resolved.stat().st_size if resolved.is_file() else None,
            "fits_github_release": resolved.is_file()
            and resolved.stat().st_size < GITHUB_RELEASE_ASSET_LIMIT,
        }
    packages.append(
        {
            "id": "mte",
            "strategy": "import_mte",
            "provides": ["mte"],
            "sources": [mte_entry],
        }
    )

    for uf in UFS:
        identifier = f"sicar_imoveis_{uf.lower()}"
        relative = f"car/{uf}/{uf}_AREA_IMOVEL.gpkg"
        packages.append(
            {
                "id": identifier,
                "strategy": "replace_file",
                "provides": [identifier],
                "target": relative,
                "sources": [_source(root, relative)],
            }
        )
    for identifier, relative in ENVIRONMENTAL.items():
        packages.append(
            {
                "id": identifier,
                "strategy": "replace_file",
                "provides": [identifier],
                "target": relative,
                "sources": [_source(root, relative)],
            }
        )

    missing = [
        package["id"]
        for package in packages
        if not all(source["present"] for source in package["sources"])
    ]
    missing_sources = [
        source["path"]
        for package in packages
        for source in package["sources"]
        if not source["present"]
    ]
    oversized_sources = [
        source["path"]
        for package in packages
        for source in package["sources"]
        if source["present"] and not source["fits_github_release"]
    ]
    oversized_packages = [
        package["id"]
        for package in packages
        if package.get("combined_sources_fit_github_release") is False
    ]
    technically_ready = not missing and not oversized_sources and not oversized_packages
    publication_blockers: list[dict[str, str]] = [
        {
            "package": "sicor_operacoes_car",
            "reason": "Definir consumo da fonte oficial ou aprovar formalmente o espelhamento dos microdados.",
        }
    ]
    if missing:
        publication_blockers.append(
            {
                "package": ", ".join(sorted(set(str(item) for item in missing))),
                "reason": "Obter e validar todas as fontes oficiais atualmente exigidas pelo inventário.",
            }
        )
    return {
        "schema_version": 1,
        "data_root_included": False,
        "logical_bases": 11,
        "planned_packages": len(packages),
        "github_release_asset_limit_bytes": GITHUB_RELEASE_ASSET_LIMIT,
        # Compatibilidade com o validador estrutural. Este campo significa
        # somente que os arquivos existem e cabem nos limites técnicos.
        "ready": technically_ready,
        "technically_ready": technically_ready,
        "ready_for_publication": False,
        "publication_blockers": publication_blockers,
        "missing_packages": missing,
        "missing_sources": missing_sources,
        "oversized_sources": oversized_sources,
        "oversized_packages": oversized_packages,
        "packages": packages,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--mte-source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = inventory(arguments.data_root, arguments.mte_source)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "logical_bases",
                    "planned_packages",
                    "technically_ready",
                    "ready_for_publication",
                    "publication_blockers",
                    "missing_packages",
                    "missing_sources",
                    "oversized_sources",
                    "oversized_packages",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
