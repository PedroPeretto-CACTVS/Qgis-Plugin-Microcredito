"""SQLAlchemy 2.x models matching schema v3 table and column names."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Importacao(Base):
    __tablename__ = "importacao"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('mutuarios', 'propriedades', 'operacoes', "
            "'complementos', 'glebas', 'mma_mcr')",
            name="ck_importacao_tipo",
        ),
        CheckConstraint("ativo IN (0, 1)", name="ck_importacao_ativo"),
        UniqueConstraint("tipo", "sha256", name="uq_importacao_tipo_sha256"),
        Index("ix_importacao_ativa", "tipo", "escopo", "ativo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(Text, nullable=False)
    arquivo: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    importado_em: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    total_linhas: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    linhas_validas: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    linhas_rejeitadas: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    escopo: Mapped[str] = mapped_column(
        Text, nullable=False, default="nacional", server_default=text("'nacional'")
    )
    ativo: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    validade_ate: Mapped[str | None] = mapped_column(Text, nullable=True)


class SicorMutuario(Base):
    __tablename__ = "sicor_mutuario"
    __table_args__ = (
        Index("ix_mutuario_documento", "documento_normalizado"),
        Index("ix_mutuario_ref", "ref_bacen"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    importacao_id: Mapped[int] = mapped_column(
        ForeignKey("importacao.id", ondelete="CASCADE"), nullable=False
    )
    ref_bacen: Mapped[str] = mapped_column(Text, nullable=False)
    documento_original: Mapped[str | None] = mapped_column(Text)
    documento_normalizado: Mapped[str | None] = mapped_column(Text)
    documento_mascarado: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    tipo_beneficiario: Mapped[str | None] = mapped_column(Text)
    dap_caf: Mapped[str | None] = mapped_column(Text)
    importacao: Mapped[Importacao] = relationship()


class SicorPropriedade(Base):
    __tablename__ = "sicor_propriedade"
    __table_args__ = (
        Index("ix_propriedade_documento", "documento_normalizado"),
        Index("ix_propriedade_car", "car_normalizado"),
        Index("ix_propriedade_ref", "ref_bacen"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    importacao_id: Mapped[int] = mapped_column(
        ForeignKey("importacao.id", ondelete="CASCADE"), nullable=False
    )
    ref_bacen: Mapped[str] = mapped_column(Text, nullable=False)
    nu_ordem: Mapped[str | None] = mapped_column(Text)
    documento_original: Mapped[str | None] = mapped_column(Text)
    documento_normalizado: Mapped[str | None] = mapped_column(Text)
    documento_mascarado: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    car_original: Mapped[str | None] = mapped_column(Text)
    car_normalizado: Mapped[str | None] = mapped_column(Text)
    sncr: Mapped[str | None] = mapped_column(Text)
    nirf_cib: Mapped[str | None] = mapped_column(Text)
    importacao: Mapped[Importacao] = relationship()


class SicorOperacao(Base):
    __tablename__ = "sicor_operacao"
    __table_args__ = (Index("ix_operacao_chave", "ref_bacen", "nu_ordem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    importacao_id: Mapped[int] = mapped_column(
        ForeignKey("importacao.id", ondelete="CASCADE"), nullable=False
    )
    ref_bacen: Mapped[str] = mapped_column(Text, nullable=False)
    nu_ordem: Mapped[str] = mapped_column(Text, nullable=False)
    data_emissao: Mapped[str | None] = mapped_column(Text)
    data_vencimento: Mapped[str | None] = mapped_column(Text)
    cnpj_if: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str | None] = mapped_column(Text)
    fonte_recurso: Mapped[str | None] = mapped_column(Text)
    empreendimento: Mapped[str | None] = mapped_column(Text)
    programa: Mapped[str | None] = mapped_column(Text)
    subprograma: Mapped[str | None] = mapped_column(Text)
    area_financiada: Mapped[str | None] = mapped_column(Text)
    area_informada: Mapped[str | None] = mapped_column(Text)
    bonus_car: Mapped[str | None] = mapped_column(Text)
    importacao: Mapped[Importacao] = relationship()


class SicorComplementoOperacao(Base):
    __tablename__ = "sicor_complemento_operacao"
    __table_args__ = (Index("ix_complemento_chave", "ref_bacen", "nu_ordem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    importacao_id: Mapped[int] = mapped_column(
        ForeignKey("importacao.id", ondelete="CASCADE"), nullable=False
    )
    ref_bacen: Mapped[str] = mapped_column(Text, nullable=False)
    nu_ordem: Mapped[str] = mapped_column(Text, nullable=False)
    ref_bacen_efetivo: Mapped[str | None] = mapped_column(Text)
    agencia_if: Mapped[str | None] = mapped_column(Text)
    municipio_ibge: Mapped[str | None] = mapped_column(Text)
    numero_cedula_if: Mapped[str | None] = mapped_column(Text)
    importacao: Mapped[Importacao] = relationship()


class SicorPontoGleba(Base):
    __tablename__ = "sicor_ponto_gleba"
    __table_args__ = (
        Index(
            "ix_gleba_chave",
            "ref_bacen",
            "nu_ordem",
            "indice_gleba",
            "indice_ponto",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    importacao_id: Mapped[int] = mapped_column(
        ForeignKey("importacao.id", ondelete="CASCADE"), nullable=False
    )
    ref_bacen: Mapped[str] = mapped_column(Text, nullable=False)
    nu_ordem: Mapped[str] = mapped_column(Text, nullable=False)
    identificador: Mapped[str | None] = mapped_column(Text)
    indice_gleba: Mapped[int | None] = mapped_column(Integer)
    indice_ponto: Mapped[int | None] = mapped_column(Integer)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    altitude: Mapped[str | None] = mapped_column(Text)
    id_ponto: Mapped[str | None] = mapped_column(Text)
    importacao: Mapped[Importacao] = relationship()


class SicorGlebaWkt(Base):
    __tablename__ = "sicor_gleba_wkt"
    __table_args__ = (
        Index("ix_gleba_wkt_chave", "ref_bacen", "nu_ordem", "indice_gleba"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    importacao_id: Mapped[int] = mapped_column(
        ForeignKey("importacao.id", ondelete="CASCADE"), nullable=False
    )
    ref_bacen: Mapped[str] = mapped_column(Text, nullable=False)
    nu_ordem: Mapped[str] = mapped_column(Text, nullable=False)
    indice_gleba: Mapped[int | None] = mapped_column(Integer)
    geometria_wkt: Mapped[str] = mapped_column(Text, nullable=False)
    importacao: Mapped[Importacao] = relationship()


class MmaMcr(Base):
    __tablename__ = "mma_mcr"
    __table_args__ = (Index("ix_mma_mcr_car", "car_normalizado"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    importacao_id: Mapped[int] = mapped_column(
        ForeignKey("importacao.id", ondelete="CASCADE"), nullable=False
    )
    car_original: Mapped[str] = mapped_column(Text, nullable=False)
    car_normalizado: Mapped[str] = mapped_column(Text, nullable=False)
    status_imovel: Mapped[str | None] = mapped_column(Text)
    condicao: Mapped[str | None] = mapped_column(Text)
    data_atualizacao: Mapped[str | None] = mapped_column(Text)
    area_declarada: Mapped[str | None] = mapped_column(Text)
    area_total_ha: Mapped[str | None] = mapped_column(Text)
    modulos_fiscais: Mapped[str | None] = mapped_column(Text)
    uf: Mapped[str | None] = mapped_column(Text)
    municipio: Mapped[str | None] = mapped_column(Text)
    codigo_municipio: Mapped[str | None] = mapped_column(Text)
    tipo_imovel: Mapped[str | None] = mapped_column(Text)
    julgamento_status: Mapped[str | None] = mapped_column(Text)
    soma_desmatamento: Mapped[str | None] = mapped_column(Text)
    dentro_criterio: Mapped[str | None] = mapped_column(Text)
    criterio_aplicado: Mapped[str | None] = mapped_column(Text)
    resultados: Mapped[str | None] = mapped_column(Text)
    bioma: Mapped[str | None] = mapped_column(Text)
    importacao: Mapped[Importacao] = relationship()


class TrabalhoEscravo(Base):
    __tablename__ = "trabalho_escravo"
    __table_args__ = (
        UniqueConstraint(
            "identificador_fonte",
            "documento_normalizado",
            "inclusao_cadastro",
            name="uq_trabalho_escravo_fonte_doc_inclusao",
        ),
        Index("ix_trabalho_escravo_documento", "documento_normalizado"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identificador_fonte: Mapped[str | None] = mapped_column(Text)
    documento_original: Mapped[str] = mapped_column(Text, nullable=False)
    documento_normalizado: Mapped[str] = mapped_column(Text, nullable=False)
    empregador: Mapped[str | None] = mapped_column(Text)
    uf: Mapped[str | None] = mapped_column(Text)
    estabelecimento: Mapped[str | None] = mapped_column(Text)
    ano_acao_fiscal: Mapped[str | None] = mapped_column(Text)
    trabalhadores_envolvidos: Mapped[str | None] = mapped_column(Text)
    cnae: Mapped[str | None] = mapped_column(Text)
    decisao_procedencia: Mapped[str | None] = mapped_column(Text)
    inclusao_cadastro: Mapped[str | None] = mapped_column(Text)
    fonte_url: Mapped[str] = mapped_column(Text, nullable=False)
    arquivo_fonte: Mapped[str] = mapped_column(Text, nullable=False)
    importado_em: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class MtePublicacao(Base):
    __tablename__ = "mte_publicacao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    arquivo_fonte: Mapped[str] = mapped_column(Text, nullable=False)
    fonte_url: Mapped[str] = mapped_column(Text, nullable=False)
    importado_em: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    total_registros: Mapped[int] = mapped_column(Integer, nullable=False)
    validade_ate: Mapped[str] = mapped_column(Text, nullable=False)
