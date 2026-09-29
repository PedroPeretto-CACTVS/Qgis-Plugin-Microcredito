"""Vocabulário estruturado das fontes de recursos e linhas de crédito."""

from __future__ import annotations

RESOURCE_SOURCES = (
    ("FCO", "FCO — Fundo Constitucional do Centro-Oeste"),
    ("FNO", "FNO — Fundo Constitucional do Norte"),
    ("OGU", "OGU — Orçamento Geral da União"),
)

CREDIT_LINES = (
    "Pronaf B",
    "Pronaf B para mulheres",
    "Pronaf B agroecológico/orgânico",
    "Pronaf B quintais produtivos",
)

AUTOMATIC_RESOURCE_SOURCE = "AUTO"
FNO_STATES = frozenset({"AC", "AP", "AM", "PA", "RO", "RR", "TO"})
FCO_STATES = frozenset({"DF", "GO", "MT", "MS"})
BRAZIL_STATES = frozenset(
    {
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
    }
)


def normalize_resource_source(value: object) -> str:
    candidate = str(value or "").strip().upper()
    return candidate if candidate in {code for code, _ in RESOURCE_SOURCES} else ""


def normalize_resource_source_choice(value: object) -> str:
    """Aceita uma fonte manual ou o modo de sugestão automática."""
    candidate = str(value or "").strip().upper()
    if candidate == AUTOMATIC_RESOURCE_SOURCE:
        return candidate
    return normalize_resource_source(candidate)


def state_from_car(value: object) -> str:
    """Extrai a UF inicial de um código CAR sem afirmar sua validade cadastral."""
    compact = "".join(
        char for char in str(value or "").strip().upper() if char.isalnum()
    )
    state = compact[:2]
    return state if state in BRAZIL_STATES else ""


def suggest_resource_source(value: object) -> str:
    """Aplica o roteamento interno por UF; a sugestão ainda exige confirmação humana."""
    state = state_from_car(value)
    if state in FNO_STATES:
        return "FNO"
    if state in FCO_STATES:
        return "FCO"
    return "OGU" if state else ""


def resolve_resource_source(choice: object, car: object) -> tuple[str, str, str]:
    """Retorna fonte, modo de seleção e UF identificada no CAR."""
    selected = normalize_resource_source_choice(choice)
    state = state_from_car(car)
    if selected == AUTOMATIC_RESOURCE_SOURCE:
        return suggest_resource_source(car), "sugerida_pela_uf", state
    return normalize_resource_source(selected), "manual", state


def normalize_credit_line(value: object) -> str:
    candidate = " ".join(str(value or "").strip().split())
    by_name = {item.casefold(): item for item in CREDIT_LINES}
    return by_name.get(candidate.casefold(), "")
