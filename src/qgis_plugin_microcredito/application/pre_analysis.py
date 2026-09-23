"""Pré-análise normativa explicável para apoio à decisão técnica.

Este módulo não aprova nem recusa crédito. Ele traduz os resultados das fontes
consultadas em sinais preliminares, explicita as limitações e indica o que o
técnico ainda precisa confirmar.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter

POSSIBLE_IMPEDIMENT = "possivel_impedimento"
NO_INDICATION = "sem_indicio_impedimento"
INCONCLUSIVE = "inconclusivo"
TECHNICAL_REVIEW = "validacao_tecnica"

PRE_ANALYSIS_LABELS = {
    POSSIBLE_IMPEDIMENT: "Possível impedimento — decisão técnica necessária",
    NO_INDICATION: "Sem indício de impedimento nesta verificação",
    INCONCLUSIVE: "Verificação inconclusiva",
    TECHNICAL_REVIEW: "Validação técnica/documental necessária",
}

TECHNICAL_DECISIONS = (
    ("pendente", "Pendente de decisão técnica"),
    ("contratar", "Contratar"),
    ("contratar_condicionado", "Contratar com condicionantes"),
    ("nao_contratar", "Não contratar"),
    ("encaminhar", "Encaminhar para análise especializada"),
)

RULES_VERSION = "pre-analise-mcr-fno-fco-2026-09-22"


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _plain(value: object) -> str:
    text = str(value or "").strip().upper()
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


def _item(
    code: str,
    title: str,
    classification: str,
    understanding: str,
    rationale: str,
    action: str,
    reference: str = "",
) -> dict[str, object]:
    return {
        "codigo": code,
        "regra": title,
        "classificacao": classification,
        "classificacao_rotulo": PRE_ANALYSIS_LABELS[classification],
        "entendimento_regra": understanding,
        "fundamento_resultado": rationale,
        "providencia_tecnica": action,
        "referencia": reference,
    }


def _list_rule(code: str, outcome: str) -> dict[str, object]:
    if code == "mma_mcr":
        title = "Publicação MMA/MCR"
        understanding = (
            "A publicação identifica situações ambientais que podem restringir a operação de crédito rural. "
            "A correspondência exige conferência da situação atual do CAR, do critério publicado e dos documentos."
        )
        reference = "MCR 2-9 — impedimentos socioambientais"
        if outcome == "ocorrencia_para_analise":
            return _item(
                code,
                title,
                POSSIBLE_IMPEDIMENT,
                understanding,
                "O CAR consta na publicação válida consultada.",
                "Conferir situação, critério, julgamento, vigência e documentos de regularização antes de decidir.",
                reference,
            )
        if outcome == "sem_ocorrencia_identificada":
            return _item(
                code,
                title,
                NO_INDICATION,
                understanding,
                "O CAR não foi localizado na edição válida consultada; isso não comprova regularidade integral.",
                "Confirmar a versão da publicação e prosseguir com as demais verificações.",
                reference,
            )
        return _item(
            code,
            title,
            INCONCLUSIVE,
            understanding,
            "A disponibilidade, validade ou interpretação da publicação não foi comprovada.",
            "Atualizar a base ou conferir manualmente a fonte oficial antes da decisão.",
            reference,
        )

    title = "Cadastro de Empregadores — MTE"
    understanding = (
        "A presença do CPF/CNPJ no cadastro do MTE pode caracterizar restrição à concessão. "
        "É necessário confirmar identidade, vigência, alcance da ocorrência e regra aplicável."
    )
    reference = "MCR 2-9 — trabalho em condições análogas à escravidão"
    if outcome == "ocorrencia_para_analise":
        return _item(
            code,
            title,
            POSSIBLE_IMPEDIMENT,
            understanding,
            "Ao menos um CPF/CNPJ pesquisado foi localizado no cadastro válido consultado.",
            "Confirmar o vínculo do documento com a operação e a situação atual do registro.",
            reference,
        )
    if outcome == "sem_ocorrencia_identificada":
        return _item(
            code,
            title,
            NO_INDICATION,
            understanding,
            "Os CPF/CNPJ pesquisados não foram localizados na edição válida consultada.",
            "Confirmar se todos os responsáveis relevantes foram pesquisados.",
            reference,
        )
    return _item(
        code,
        title,
        INCONCLUSIVE,
        understanding,
        "A consulta não comprovou cobertura válida para todos os documentos necessários.",
        "Completar os documentos ou atualizar a publicação antes da decisão.",
        reference,
    )


def _constitutional_funds_rule(analysis: dict[str, object]) -> dict[str, object]:
    fund = str(analysis.get("fundo_constitucional") or "").strip().upper()
    program = str(analysis.get("programa_financiamento") or "").strip()
    source_mode = str(analysis.get("fonte_recursos_modo") or "manual")
    source_state = str(analysis.get("fonte_recursos_uf") or "").strip().upper()
    understanding = (
        "FCO e FNO possuem programações próprias; operações com recursos do OGU também exigem "
        "enquadramento na linha informada. Em todos os casos devem ser conferidos público, finalidade, itens "
        "financiáveis, limites, garantias e condições operacionais aplicáveis."
    )
    if source_mode == "sugerida_pela_uf" and fund in {"FNO", "FCO", "OGU"} and program:
        rationale = (
            f"Fonte sugerida pelo roteamento interno a partir da UF {source_state or 'não identificada'}: {fund}. "
            f"Linha de crédito informada: {program}. A fonte contratual ainda deve ser confirmada pelo técnico."
        )
    elif fund in {"FNO", "FCO", "OGU"} and program:
        rationale = f"Fonte de recursos informada: {fund}. Linha de crédito informada: {program}."
    elif fund in {"FNO", "FCO", "OGU"}:
        rationale = f"Fonte de recursos informada: {fund}; a linha de crédito ainda não foi selecionada."
    elif program:
        rationale = f"Linha de crédito informada: {program}; a fonte de recursos ainda não foi selecionada."
    else:
        rationale = (
            "A fonte de recursos e a linha de crédito ainda não foram selecionadas."
        )
    return _item(
        "fundos_constitucionais",
        "Enquadramento da fonte de recursos e da linha de crédito",
        TECHNICAL_REVIEW,
        understanding,
        rationale,
        "Confirmar fonte de recursos, norma ou programação vigente, linha, beneficiário, localização, finalidade, itens, limites, "
        "garantias, viabilidade e exigências do agente antes de decidir a contratação.",
        "Programação vigente do FCO/FNO ou norma aplicável ao OGU, MCR e manual operacional do agente financeiro",
    )


def _forest_rule(layer: dict[str, object]) -> dict[str, object]:
    title = str(layer.get("fonte") or "Florestas públicas")
    reference = str(
        layer.get("referencia_regulatoria") or "MCR 2-9 — florestas públicas tipo B"
    )
    understanding = (
        "A regra específica incide sobre Floresta Pública Tipo B. A sobreposição pode admitir exceção, "
        "inclusive para imóvel registrado ou, sob condições cumulativas, imóvel de até 15 módulos fiscais."
    )
    outcome = str(layer.get("resultado") or "inconclusivo")
    if outcome == "inconclusivo":
        return _item(
            "florestas_publicas",
            title,
            INCONCLUSIVE,
            understanding,
            str(layer.get("motivo") or "A camada não pôde ser verificada."),
            "Regularizar a base e repetir o cruzamento antes da decisão.",
            reference,
        )
    occurrences = _mapping_list(layer.get("ocorrencias"))
    if not occurrences:
        return _item(
            "florestas_publicas",
            title,
            NO_INDICATION,
            understanding,
            "Não houve interseção territorial com a base consultada.",
            "Registrar a versão da base e prosseguir com as demais regras.",
            reference,
        )

    types = [
        _plain(_mapping(occurrence.get("atributos")).get("tipo"))
        for occurrence in occurrences
    ]
    type_b = sum(value in {"TIPO B", "B"} for value in types)
    type_a = sum(value in {"TIPO A", "A"} for value in types)
    unknown = len(types) - type_a - type_b
    area = layer.get("area_sobreposta_ha", 0)
    if type_b:
        return _item(
            "florestas_publicas",
            title,
            POSSIBLE_IMPEDIMENT,
            understanding,
            f"Foram identificadas {type_b} interseção(ões) Tipo B, com área territorial única de {area} ha.",
            "Verificar matrícula/título. Sem registro, confirmar até 15 módulos fiscais, vegetação mantida, "
            "empreendimento fora da sobreposição e objeto vinculado a área específica.",
            reference,
        )
    if unknown:
        return _item(
            "florestas_publicas",
            title,
            INCONCLUSIVE,
            understanding,
            "Há interseção, mas o atributo de tipo não permitiu confirmar se a floresta é Tipo A ou B.",
            "Conferir a feição no CNFP e sua destinação antes da decisão.",
            reference,
        )
    return _item(
        "florestas_publicas",
        title,
        TECHNICAL_REVIEW,
        understanding,
        f"As {type_a} interseção(ões) estão identificadas como Tipo A, não como Tipo B.",
        "Afastar a regra específica de Tipo B e avaliar a categoria/destinação por sua regra própria.",
        reference,
    )


def _environment_rule(layer: dict[str, object]) -> dict[str, object]:
    code = str(layer.get("codigo") or "fonte_territorial")
    if code == "florestas_publicas":
        return _forest_rule(layer)
    title = str(layer.get("fonte") or code)
    reference = str(layer.get("referencia_regulatoria") or "")
    guidance = str(
        layer.get("orientacao_revisao") or "Conferir documentos e exceções aplicáveis."
    )
    outcome = str(layer.get("resultado") or "inconclusivo")
    understanding_by_code = {
        "embargos": "Embargo ambiental vigente e relacionado ao imóvel ou à atividade pode restringir o financiamento.",
        "terras_indigenas": "A incidência em terra indígena exige verificar delimitação, beneficiário, atividade e exceções normativas.",
        "territorios_quilombolas": "A incidência em território quilombola exige verificar delimitação, beneficiário e regularidade da atividade.",
        "unidades_conservacao": "A compatibilidade depende da categoria da unidade, do plano de manejo e da autorização para a atividade.",
        "desmatamento_pos_2020": "Supressão de vegetação nativa pode restringir o crédito; a verificação deve cobrir o marco temporal integral do MCR.",
    }
    understanding = understanding_by_code.get(
        code,
        "A fonte territorial deve ser interpretada conforme a regra e suas exceções.",
    )
    if outcome == "inconclusivo":
        return _item(
            code,
            title,
            INCONCLUSIVE,
            understanding,
            str(layer.get("motivo") or "A fonte não pôde ser verificada."),
            "Corrigir ou atualizar a fonte e repetir a análise.",
            reference,
        )
    occurrences = _mapping_list(layer.get("ocorrencias"))
    if occurrences:
        return _item(
            code,
            title,
            POSSIBLE_IMPEDIMENT,
            understanding,
            f"Foram encontradas {len(occurrences)} feição(ões), em {layer.get('area_sobreposta_ha', 0)} ha de área única.",
            guidance,
            reference,
        )
    if code == "desmatamento_pos_2020":
        return _item(
            code,
            title,
            INCONCLUSIVE,
            understanding,
            "Não houve interseção na camada instalada, mas ela começa em 2020 e não comprova sozinha todo o período normativo desde 31/07/2019.",
            "Completar o período faltante ou realizar conferência documental antes da decisão.",
            reference,
        )
    return _item(
        code,
        title,
        NO_INDICATION,
        understanding,
        "A base foi consultada e não houve interseção territorial com o imóvel analisado.",
        "Registrar a versão consultada e prosseguir com as demais regras.",
        reference,
    )


def build_pre_analysis(analysis: dict[str, object]) -> dict[str, object]:
    """Produz uma leitura explicável sem substituir a decisão do técnico."""
    outcomes = _mapping(analysis.get("resultado_fontes"))
    rules = [
        _list_rule("mma_mcr", str(outcomes.get("mma_mcr") or "inconclusivo")),
        _list_rule("mte", str(outcomes.get("mte") or "inconclusivo")),
        _constitutional_funds_rule(analysis),
    ]
    environmental = _mapping(analysis.get("ambiental"))
    rules.extend(
        _environment_rule(layer)
        for layer in _mapping_list(environmental.get("camadas"))
    )
    counts = Counter(str(item["classificacao"]) for item in rules)
    if counts[POSSIBLE_IMPEDIMENT]:
        overall = POSSIBLE_IMPEDIMENT
    elif counts[INCONCLUSIVE]:
        overall = INCONCLUSIVE
    elif counts[TECHNICAL_REVIEW]:
        overall = TECHNICAL_REVIEW
    else:
        overall = NO_INDICATION

    parts = []
    if counts[POSSIBLE_IMPEDIMENT]:
        parts.append(f"{counts[POSSIBLE_IMPEDIMENT]} possível(is) impedimento(s)")
    if counts[INCONCLUSIVE]:
        parts.append(f"{counts[INCONCLUSIVE]} verificação(ões) inconclusiva(s)")
    if counts[TECHNICAL_REVIEW]:
        parts.append(
            f"{counts[TECHNICAL_REVIEW]} ponto(s) para validação técnica/documental"
        )
    if counts[NO_INDICATION]:
        parts.append(
            f"{counts[NO_INDICATION]} verificação(ões) sem indício de impedimento"
        )
    findings = ", ".join(parts) if parts else "nenhuma regra processada"
    summary = (
        f"A pré-análise reuniu {findings}. O resultado é apoio técnico, não aprovação ou recusa automática. "
        "O responsável deve conferir documentos, exceções, vigência das fontes e registrar sua decisão sobre a contratação."
    )
    fingerprint_payload = {
        "versao_regras": RULES_VERSION,
        "classificacao_geral": overall,
        "regras": rules,
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "versao_regras": RULES_VERSION,
        "sha256": fingerprint,
        "classificacao_geral": overall,
        "classificacao_geral_rotulo": PRE_ANALYSIS_LABELS[overall],
        "resumo": summary,
        "contagens": dict(counts),
        "regras": rules,
    }
