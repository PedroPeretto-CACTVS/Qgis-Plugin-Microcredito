"""Carga MTE validada antes de substituir a publicação ativa."""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date
from pathlib import Path

from qgis_plugin_microcredito.application.hashing import file_sha256
from qgis_plugin_microcredito.domain.normalize import (
    normalize_document,
    normalize_header,
)

SOURCE_URL = (
    "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/"
    "areas-de-atuacao/cadastro_de_empregadores.csv"
)
HEADERS = (
    "ID",
    "ANO_DA_ACAO_FISCAL",
    "UF",
    "EMPREGADOR",
    "CNPJ_CPF",
    "ESTABELECIMENTO",
    "TRABALHADORES_ENVOLVIDOS",
    "CNAE",
    "DECISAO_ADMINISTRATIVA_DE_PROCEDENCIA",
    "INCLUSAO_NO_CADASTRO_DE_EMPREGADORES",
)


def import_mte(
    connection: sqlite3.Connection,
    path: str | Path,
    *,
    validade_ate: str,
    source_reference: str | None = None,
) -> int:
    date.fromisoformat(validade_ate)
    source = Path(path)
    records: list[tuple[object, ...]] = []
    seen: set[tuple[str, str, str]] = set()
    digest = file_sha256(source)
    raw = source.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames:
        raise ValueError("Arquivo MTE vazio. A publicação anterior foi preservada.")
    fields = {normalize_header(name): name for name in reader.fieldnames}
    if len(fields) != len(reader.fieldnames) or any(
        name not in fields for name in HEADERS
    ):
        raise ValueError(
            "Cabeçalho MTE incompatível; confira o leiaute antes de substituir a publicação."
        )
    for line, row in enumerate(reader, 2):
        values = [(row.get(fields[name]) or "").strip() for name in HEADERS]
        document = normalize_document(values[4])
        if (
            None in row
            or not document
            or not values[0]
            or not values[3]
            or not values[9]
        ):
            raise ValueError(
                f"Registro MTE inválido na linha {line}. A publicação anterior foi preservada."
            )
        key = (values[0], document, values[9])
        if key in seen:
            raise ValueError(f"Registro MTE duplicado na linha {line}.")
        seen.add(key)
        records.append(
            (
                *values[:4],
                values[4],
                document,
                *values[5:],
                SOURCE_URL,
                source_reference or str(source.resolve()),
            )
        )
    if not records:
        raise ValueError(
            "Publicação MTE sem registros válidos; a versão anterior foi preservada."
        )
    if file_sha256(source) != digest:
        raise ValueError("Arquivo MTE alterado durante a leitura.")
    with connection:
        connection.execute("DELETE FROM trabalho_escravo")
        connection.executemany(
            """INSERT INTO trabalho_escravo
            (identificador_fonte, ano_acao_fiscal, uf, empregador, documento_original,
             documento_normalizado, estabelecimento, trabalhadores_envolvidos, cnae,
             decisao_procedencia, inclusao_cadastro, fonte_url, arquivo_fonte)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            records,
        )
        connection.execute(
            """INSERT INTO mte_publicacao
            (sha256, arquivo_fonte, fonte_url, total_registros, validade_ate)
            VALUES (?, ?, ?, ?, ?)""",
            (
                digest,
                source_reference or str(source.resolve()),
                SOURCE_URL,
                len(records),
                validade_ate,
            ),
        )
    return len(records)
