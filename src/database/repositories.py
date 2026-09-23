"""Read repositories. Complex UNION queries stay here so application stays SQL-free."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from qgis_plugin_microcredito.domain.models import mapping_to_dict
from qgis_plugin_microcredito.domain.normalize import normalize_car, normalize_document


def find_by_document(
    connection: sqlite3.Connection, document: str
) -> list[dict[str, Any]]:
    normalized = normalize_document(document)
    if not normalized:
        raise ValueError("Informe um CPF com 11 dígitos ou CNPJ com 14 dígitos")
    rows = connection.execute(
        """
        WITH evidencias AS (
            SELECT p.car_original, p.car_normalizado,
                   CASE WHEN p.car_normalizado = '' THEN 'car_nao_informado_pelo_sicor'
                        ELSE 'car_candidato' END AS situacao_car,
                   p.sncr, p.nirf_cib, p.ref_bacen, p.nu_ordem,
                   'documento_na_propriedade' AS tipo_vinculo,
                   p.documento_original AS documento_fonte,
                   i.arquivo, i.importado_em
              FROM ativo_sicor_propriedade p
              JOIN importacao i ON i.id = p.importacao_id
             WHERE p.documento_normalizado = ?
            UNION ALL
            SELECT p.car_original, p.car_normalizado,
                   CASE WHEN p.car_normalizado = '' THEN 'car_nao_informado_pelo_sicor'
                        ELSE 'car_candidato' END AS situacao_car,
                   p.sncr, p.nirf_cib, p.ref_bacen, p.nu_ordem,
                   'associacao_por_operacao' AS tipo_vinculo,
                   m.documento_original AS documento_fonte,
                   i.arquivo, i.importado_em
              FROM ativo_sicor_mutuario m
              JOIN ativo_sicor_propriedade p ON p.ref_bacen = m.ref_bacen
              JOIN importacao i ON i.id = p.importacao_id
             WHERE m.documento_normalizado = ?
        )
        SELECT DISTINCT * FROM evidencias
        ORDER BY situacao_car, car_normalizado, tipo_vinculo, ref_bacen
        """,
        (normalized, normalized),
    ).fetchall()
    return [mapping_to_dict(row) for row in rows]


def find_by_car(connection: sqlite3.Connection, car: str) -> list[dict[str, Any]]:
    normalized = normalize_car(car)
    if not normalized:
        raise ValueError("Informe um número de CAR")
    rows = connection.execute(
        """
        SELECT p.car_original, p.car_normalizado, 'car_candidato' AS situacao_car,
               p.ref_bacen, p.nu_ordem, p.documento_original,
               p.sncr, p.nirf_cib, i.arquivo, i.importado_em
          FROM ativo_sicor_propriedade p
          JOIN importacao i ON i.id = p.importacao_id
         WHERE p.car_normalizado = ?
         ORDER BY p.ref_bacen, p.nu_ordem
        """,
        (normalized,),
    ).fetchall()
    return [mapping_to_dict(row) for row in rows]


def find_documents_by_car(
    connection: sqlite3.Connection, car: str
) -> list[dict[str, Any]]:
    """Retorna documentos ligados ao CAR por evidência explícita do Sicor."""
    normalized = normalize_car(car)
    if not normalized:
        raise ValueError("Informe um número de CAR")
    rows = connection.execute(
        """
        WITH vinculos AS (
            SELECT p.car_original, p.ref_bacen, p.nu_ordem,
                   p.documento_original, p.documento_normalizado,
                   p.documento_mascarado,
                   'documento_na_propriedade' AS tipo_vinculo,
                   'SICOR_PROPRIEDADES' AS base_origem,
                   ip.arquivo, ip.importado_em
              FROM ativo_sicor_propriedade p
              JOIN importacao ip ON ip.id = p.importacao_id
             WHERE p.car_normalizado = ? AND p.documento_normalizado <> ''
            UNION ALL
            SELECT p.car_original, p.ref_bacen, p.nu_ordem,
                   m.documento_original, m.documento_normalizado,
                   m.documento_mascarado,
                   'mutuario_da_operacao' AS tipo_vinculo,
                   'SICOR_MUTUARIOS+SICOR_PROPRIEDADES' AS base_origem,
                   im.arquivo, im.importado_em
              FROM ativo_sicor_propriedade p
              JOIN ativo_sicor_mutuario m ON m.ref_bacen = p.ref_bacen
              JOIN importacao im ON im.id = m.importacao_id
             WHERE p.car_normalizado = ? AND m.documento_normalizado <> ''
        )
        SELECT DISTINCT * FROM vinculos
         ORDER BY ref_bacen, nu_ordem, tipo_vinculo, documento_normalizado
        """,
        (normalized, normalized),
    ).fetchall()
    return [mapping_to_dict(row) for row in rows]


def find_slave_labor_by_documents(
    connection: sqlite3.Connection, documents: Iterable[str]
) -> list[dict[str, Any]]:
    normalized = sorted(
        {normalize_document(value) for value in documents if normalize_document(value)}
    )
    if not normalized:
        return []
    placeholders = ",".join("?" for _ in normalized)
    rows = connection.execute(
        f"""SELECT documento_original, documento_normalizado, empregador, uf,
                   estabelecimento, ano_acao_fiscal, trabalhadores_envolvidos,
                   cnae, decisao_procedencia, inclusao_cadastro, fonte_url,
                   arquivo_fonte, importado_em
              FROM trabalho_escravo
             WHERE documento_normalizado IN ({placeholders})
          ORDER BY documento_normalizado, inclusao_cadastro""",
        normalized,
    ).fetchall()
    return [mapping_to_dict(row) for row in rows]


def find_operation_context(
    connection: sqlite3.Connection, ref_bacen: str, nu_ordem: str
) -> dict[str, Any]:
    operation = connection.execute(
        """SELECT o.*, c.municipio_ibge, c.agencia_if, c.ref_bacen_efetivo,
                  ((SELECT COUNT(DISTINCT g.indice_gleba)
                     FROM ativo_sicor_ponto_gleba g
                    WHERE g.ref_bacen = o.ref_bacen AND g.nu_ordem = o.nu_ordem) +
                   (SELECT COUNT(*) FROM ativo_sicor_gleba_wkt w
                    WHERE w.ref_bacen = o.ref_bacen AND w.nu_ordem = o.nu_ordem)) AS total_glebas,
                  (SELECT COUNT(*) FROM ativo_sicor_ponto_gleba g
                    WHERE g.ref_bacen = o.ref_bacen AND g.nu_ordem = o.nu_ordem) AS total_pontos
             FROM ativo_sicor_operacao o
        LEFT JOIN ativo_sicor_complemento_operacao c
               ON c.ref_bacen = o.ref_bacen AND c.nu_ordem = o.nu_ordem
            WHERE o.ref_bacen = ? AND o.nu_ordem = ?
         ORDER BY o.id DESC LIMIT 1""",
        (ref_bacen, nu_ordem),
    ).fetchone()
    return mapping_to_dict(operation) if operation else {}


def find_mma_mcr_by_car(
    connection: sqlite3.Connection, car: str
) -> list[dict[str, Any]]:
    normalized = normalize_car(car)
    if not normalized:
        raise ValueError("Informe um número de CAR")
    rows = connection.execute(
        """SELECT m.car_original, m.status_imovel, m.condicao, m.data_atualizacao,
                  m.area_declarada, m.area_total_ha, m.modulos_fiscais, m.uf,
                  m.municipio, m.codigo_municipio, m.tipo_imovel,
                  m.julgamento_status, m.soma_desmatamento, m.dentro_criterio,
                  m.criterio_aplicado, m.resultados, m.bioma,
                  i.arquivo AS fonte_arquivo, i.importado_em
             FROM ativo_mma_mcr m
             JOIN importacao i ON i.id = m.importacao_id
            WHERE m.car_normalizado = ?
         ORDER BY i.id DESC""",
        (normalized,),
    ).fetchall()
    return [mapping_to_dict(row) for row in rows]


def list_imports(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT id, tipo, escopo, ativo, validade_ate, arquivo, importado_em,
                  total_linhas, linhas_validas, linhas_rejeitadas
             FROM importacao ORDER BY id"""
    ).fetchall()
    return [mapping_to_dict(row) for row in rows]
