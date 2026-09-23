"""Pydantic models used at import, query, and report boundaries."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: str
    arquivo: str
    total: int
    validas: int
    rejeitadas: int
    ignorado: bool = False


class CarCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    car_original: str | None = None
    car_normalizado: str | None = None
    situacao_car: str | None = None
    sncr: str | None = None
    nirf_cib: str | None = None
    ref_bacen: str | None = None
    nu_ordem: str | None = None
    tipo_vinculo: str | None = None
    documento_fonte: str | None = None
    documento_original: str | None = None
    arquivo: str | None = None
    importado_em: str | None = None


class DocumentLink(BaseModel):
    model_config = ConfigDict(extra="allow")

    car_original: str | None = None
    ref_bacen: str | None = None
    nu_ordem: str | None = None
    documento_original: str | None = None
    documento_normalizado: str | None = None
    documento_mascarado: int | None = None
    tipo_vinculo: str | None = None
    base_origem: str | None = None
    arquivo: str | None = None
    importado_em: str | None = None


class MmaRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    car_original: str | None = None
    status_imovel: str | None = None
    condicao: str | None = None
    data_atualizacao: str | None = None
    area_declarada: str | None = None
    area_total_ha: str | None = None
    modulos_fiscais: str | None = None
    uf: str | None = None
    municipio: str | None = None
    codigo_municipio: str | None = None
    tipo_imovel: str | None = None
    julgamento_status: str | None = None
    soma_desmatamento: str | None = None
    dentro_criterio: str | None = None
    criterio_aplicado: str | None = None
    resultados: str | None = None
    bioma: str | None = None
    fonte_arquivo: str | None = None
    importado_em: str | None = None


class LaborRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    documento_original: str | None = None
    documento_normalizado: str | None = None
    empregador: str | None = None
    uf: str | None = None
    estabelecimento: str | None = None
    ano_acao_fiscal: str | None = None
    trabalhadores_envolvidos: str | None = None
    cnae: str | None = None
    decisao_procedencia: str | None = None
    inclusao_cadastro: str | None = None
    fonte_url: str | None = None
    arquivo_fonte: str | None = None
    importado_em: str | None = None


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")

    linhas_validas: int | None = None
    total_registros: int | None = None
    sha256: str | None = None
    validade_ate: str | None = None
    linhas_rejeitadas: int | None = 0
    problema: str | None = None
    fonte_url: str | None = None


class VerdictBundle(BaseModel):
    mma_mcr: str
    mte: str


class EnvironmentalLayerResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    codigo: str
    fonte: str
    resultado: str
    quantidade: int | None = None
    area_sobreposta_ha: float | None = None
    motivo: str | None = None


class MutuarioRow(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    ref_bacen: str
    documento: str = ""
    tipo_beneficiario: str = ""
    dap_caf: str = ""


class PropriedadeRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref_bacen: str
    nu_ordem: str = ""
    documento: str = ""
    car: str
    sncr: str = ""
    nirf_cib: str = ""


class OperacaoRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref_bacen: str
    nu_ordem: str
    data_emissao: str = ""
    data_vencimento: str = ""
    cnpj_if: str = ""
    estado: str = ""
    fonte_recurso: str = ""
    empreendimento: str = ""
    programa: str = ""
    subprograma: str = ""
    area_financiada: str = ""
    area_informada: str = ""
    bonus_car: str = ""


class ComplementoRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref_bacen: str
    nu_ordem: str
    ref_bacen_efetivo: str = ""
    agencia_if: str = ""
    municipio_ibge: str = ""
    numero_cedula_if: str = ""


class GlebaPointRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref_bacen: str
    nu_ordem: str
    identificador: str = ""
    indice_gleba: int
    indice_ponto: int
    latitude: float
    longitude: float
    altitude: str = ""
    id_ponto: str = ""


class GlebaWktRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref_bacen: str
    nu_ordem: str
    indice_gleba: int | None = None
    geometria_wkt: str


class MmaImportRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    car: str
    status_imovel: str = ""
    condicao: str = ""
    data_atualizacao: str = ""
    area_declarada: str = ""
    area_total_ha: str = ""
    modulos_fiscais: str = ""
    uf: str = ""
    municipio: str = ""
    codigo_municipio: str = ""
    tipo_imovel: str = ""
    julgamento_status: str = ""
    soma_desmatamento: str = ""
    dentro_criterio: str = ""
    criterio_aplicado: str = ""
    resultados: str = ""
    bioma: str = ""


class BatchRow(BaseModel):
    source_row: int
    document: str
    car: str = ""
    owner_document: str = ""
    internal_reference: str = ""
    observation: str = ""


class ReportPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    resultado_geral: str
    car: str = ""
    versao_motor: str = Field(default="0.8.0")
    documentos_consultados_mte: list[str] = Field(default_factory=list)


def mapping_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {str(key): row[key] for key in keys()}
    return dict(row)
