"""Vocabulário de bases orientado aos requisitos MCR, FNO e FCO.

Os nomes internos das tabelas continuam estáveis para não quebrar a importação,
mas nunca devem ser apresentados ao analista como se fossem requisitos de
conformidade. Esta camada faz a tradução e explicita a cobertura parcial.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class BaseDefinition:
    identifier: str
    label: str
    regulatory_basis: str
    coverage: str
    detail: str
    technical_components: tuple[str, ...] = ()
    relative_path: str | None = None
    state_directory: str | None = None


@dataclass(frozen=True)
class LocalBaseInventory:
    identifier: str
    label: str
    regulatory_basis: str
    local_version: str | None
    local_state: str
    coverage: str
    detail: str


BASE_DEFINITIONS = (
    BaseDefinition(
        "sicor_operacoes_car",
        "Operação de crédito e vínculos CPF/CNPJ–CAR — Sicor/BCB",
        "MCR; FNO/FCO rural",
        "Parcial",
        "Identifica operação, mutuário, imóvel e complemento. O vínculo não prova sozinho titularidade nem elegibilidade.",
        ("mutuarios", "propriedades", "operacoes", "complementos"),
    ),
    BaseDefinition(
        "sicor_geometrias",
        "Área financiada e geometria das glebas — Sicor/BCB",
        "MCR 2-9; FNO/FCO rural",
        "Parcial",
        "A gleba declarada não substitui a delimitação da área contínua efetivamente usada pela atividade financiada.",
        ("glebas",),
    ),
    BaseDefinition(
        "mma_mcr",
        "Impedimentos ambientais publicados para o crédito rural — MMA/MCR",
        "MCR 2-9",
        "Parcial",
        "A ocorrência exige conferência da publicação vigente, do motivo e das evidências ou exceções cabíveis.",
        ("mma_mcr",),
    ),
    BaseDefinition(
        "mte",
        "Impedimento social: Cadastro de Empregadores — MTE/MCR",
        "MCR 2-9",
        "Lista federal",
        "Consulta CPF/CNPJ no cadastro federal vigente. Não representa outras fontes ou decisões trabalhistas.",
        ("mte",),
    ),
    BaseDefinition(
        "sicar_imoveis",
        "Situação cadastral e geometria dos imóveis rurais — SICAR",
        "MCR; FNO/FCO rural",
        "Parcial",
        "A geometria local permite localizar o imóvel; a situação cadastral vigente ainda deve ser confirmada no SICAR.",
        state_directory="car",
    ),
    BaseDefinition(
        "embargos",
        "Embargos ambientais vigentes — Ibama (cobertura federal)",
        "MCR 2-9",
        "Parcial",
        "Confirmar vigência, atividade, alcance e exceções. A fonte federal não cobre sozinha órgãos estaduais e ICMBio.",
        relative_path="ambientais/embargos.gpkg",
    ),
    BaseDefinition(
        "terras_indigenas",
        "Terras indígenas: interferência e exceções — MCR",
        "MCR 2-9",
        "Parcial",
        "Confirmar delimitação oficial, área contínua da atividade, condição do beneficiário e documentos aplicáveis.",
        relative_path="ambientais/terras_indigenas.gpkg",
    ),
    BaseDefinition(
        "territorios_quilombolas",
        "Territórios quilombolas: interferência e exceções — MCR",
        "MCR 2-9",
        "Parcial",
        "Confirmar delimitação, área contínua, condição do beneficiário e exceções documentais.",
        relative_path="ambientais/territorios_quilombolas.gpkg",
    ),
    BaseDefinition(
        "unidades_conservacao",
        "Unidades de conservação: categoria e autorização — MCR",
        "MCR 2-9",
        "Parcial",
        "Verificar categoria, plano de manejo, população tradicional e autorização. Sobreposição não é reprovação automática.",
        relative_path="ambientais/unidades_conservacao.gpkg",
    ),
    BaseDefinition(
        "florestas_publicas",
        "Florestas públicas tipo B não destinadas — MCR",
        "MCR 2-9",
        "Parcial",
        "A camada local precisa ser filtrada por tipo B e ausência de destinação; outras florestas públicas não são impedimento automático.",
        relative_path="ambientais/florestas_publicas.gpkg",
    ),
    BaseDefinition(
        "desmatamento_pos_2020",
        "PRODES após 2020 — cobertura parcial da regra desde 31/07/2019",
        "MCR 2-9-17/18",
        "Incompleta",
        "A regra alcança supressões posteriores a 31/07/2019 e admite documentos específicos; a camada atual começa após 2020.",
        relative_path="ambientais/desmatamento_pos_2020.gpkg",
    ),
)

BASE_BY_ID = {item.identifier: item for item in BASE_DEFINITIONS}
SICAR_STATE_ID = re.compile(r"sicar_imoveis_([a-z]{2})$")


NON_DATABASE_REQUIREMENTS = (
    "CAR/CCIR, licenças, alvarás e outorgas, quando aplicáveis (FCO 2026)",
    "Projeto técnico e comprovação dos itens financiados (FCO 2026)",
    "Licença da atividade florestal, PMFS/POA e AUTEX/AUTEF, quando aplicáveis (FNO 2026)",
    "Garantias, fiscalização, assistência técnica e condições de liberação definidas pela instituição operadora",
    "Monitoramento remoto durante a operação, quando exigido pelo MCR",
)


def definition_for(identifier: str) -> BaseDefinition | None:
    definition = BASE_BY_ID.get(identifier)
    if definition is not None:
        return definition
    match = SICAR_STATE_ID.fullmatch(identifier)
    if match is None:
        return None
    uf = match.group(1).upper()
    parent = BASE_BY_ID["sicar_imoveis"]
    return BaseDefinition(
        identifier,
        f"Situação cadastral e geometria dos imóveis rurais — SICAR/{uf}",
        parent.regulatory_basis,
        parent.coverage,
        parent.detail,
        relative_path=f"car/{uf}/{uf}_AREA_IMOVEL.gpkg",
    )


def display_label(identifier: str, fallback: str) -> str:
    definition = definition_for(identifier)
    return (
        definition.label
        if definition
        else f"Pacote técnico não classificado: {fallback}"
    )


def _file_version(path: Path) -> str | None:
    try:
        modified = (
            datetime.fromtimestamp(path.stat().st_mtime)
            .astimezone()
            .isoformat(timespec="seconds")
        )
    except OSError:
        return None
    return f"arquivo local modificado em {modified}"


def _component_version(
    definition: BaseDefinition, versions: dict[str, str]
) -> tuple[str | None, str, str]:
    registered = versions.get(definition.identifier)
    found = {
        key: versions[key] for key in definition.technical_components if key in versions
    }
    if registered:
        return (
            registered,
            "Instalada",
            f"Pacote registrado; componentes técnicos: {', '.join(definition.technical_components)}.",
        )
    if len(found) == len(definition.technical_components):
        values = "; ".join(f"{key}: {value}" for key, value in found.items())
        return (
            f"{len(found)}/{len(definition.technical_components)} componentes locais",
            "Local sem versão publicada",
            values,
        )
    if found:
        missing = [key for key in definition.technical_components if key not in found]
        values = "; ".join(f"{key}: {value}" for key, value in found.items())
        return (
            f"{len(found)}/{len(definition.technical_components)} componentes locais",
            "Incompleta",
            f"{values}. Ausentes: {', '.join(missing)}.",
        )
    return None, "Ausente", "Nenhum componente técnico foi identificado no banco local."


def build_local_inventory(
    data_root: str | Path, versions: dict[str, str]
) -> list[LocalBaseInventory]:
    root = Path(data_root).resolve()
    result: list[LocalBaseInventory] = []
    known_version_keys: set[str] = set()
    for definition in BASE_DEFINITIONS:
        known_version_keys.add(definition.identifier)
        known_version_keys.update(definition.technical_components)
        version: str | None
        state: str
        technical_detail: str
        if definition.technical_components:
            version, state, technical_detail = _component_version(definition, versions)
        elif definition.relative_path:
            path = root / definition.relative_path
            version = versions.get(definition.identifier) or _file_version(path)
            state = "Instalada" if version else "Ausente"
            technical_detail = f"Arquivo local: {definition.relative_path}."
        elif definition.state_directory:
            files = sorted(
                (root / definition.state_directory).glob("*/*_AREA_IMOVEL.gpkg")
            )
            registered = versions.get(definition.identifier)
            registered_states = {
                key.rsplit("_", 1)[-1].upper(): value
                for key, value in versions.items()
                if SICAR_STATE_ID.fullmatch(key)
            }
            known_version_keys.update(
                f"sicar_imoveis_{uf.lower()}" for uf in registered_states
            )
            if registered:
                version, state = registered, "Instalada"
            elif len(registered_states) == 27:
                published = sorted(set(registered_states.values()))
                version = (
                    published[0]
                    if len(published) == 1
                    else "27/27 UF; versões publicadas diferentes"
                )
                state = "Instalada"
            elif registered_states:
                version = f"{len(registered_states)}/27 UF com versão publicada"
                state = "Incompleta"
            elif files:
                states = {path.parent.name.upper() for path in files}
                stamps = [
                    value for value in (_file_version(path) for path in files) if value
                ]
                version = f"{len(states)}/27 UF; {stamps[0] if stamps else 'data local não identificada'}"
                state = "Instalada" if len(states) == 27 else "Incompleta"
            else:
                version, state = None, "Ausente"
            technical_detail = (
                f"Arquivos estaduais identificados em {definition.state_directory}/; "
                f"{len(registered_states)} UF com versão assinada registrada."
            )
        else:  # pragma: no cover - toda definição atual possui uma origem local
            version, state, technical_detail = (
                None,
                "Ausente",
                "Origem local não configurada.",
            )
        result.append(
            LocalBaseInventory(
                definition.identifier,
                definition.label,
                definition.regulatory_basis,
                version,
                state,
                definition.coverage,
                f"{definition.detail} {technical_detail}",
            )
        )

    for identifier, version in sorted(versions.items()):
        if identifier in known_version_keys:
            continue
        result.append(
            LocalBaseInventory(
                identifier,
                f"Pacote técnico não classificado: {identifier}",
                "Não definido",
                version,
                "Revisar",
                "Não avaliada",
                "O identificador existe localmente, mas ainda não foi associado a um requisito MCR/FNO/FCO.",
            )
        )
    return result
