"""Typed constants that replace stringly-typed legacy values."""

from __future__ import annotations

from enum import StrEnum


class Verdict(StrEnum):
    INCONCLUSIVE = "inconclusivo"
    CLEAR = "sem_ocorrencia_identificada"
    REVIEW = "ocorrencia_para_analise"


class ImportType(StrEnum):
    MUTUARIOS = "mutuarios"
    PROPRIEDADES = "propriedades"
    OPERACOES = "operacoes"
    COMPLEMENTOS = "complementos"
    GLEBAS = "glebas"
    MMA_MCR = "mma_mcr"


class LinkType(StrEnum):
    DOCUMENT_ON_PROPERTY = "documento_na_propriedade"
    ASSOCIATION_BY_OPERATION = "associacao_por_operacao"
    BORROWER_OF_OPERATION = "mutuario_da_operacao"
    CAR_NOT_INFORMED = "car_nao_informado_pelo_sicor"
