from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from itertools import chain
from pathlib import Path
from typing import Any

from qgis_plugin_microcredito.application.hashing import file_sha256
from qgis_plugin_microcredito.domain.models import ImportRecord, MutuarioRow
from qgis_plugin_microcredito.domain.normalize import (
    is_masked_document,
    normalize_car,
    normalize_document,
)
from qgis_plugin_microcredito.infrastructure.csv_reader import (
    iter_rows,
    value_from_aliases,
)

MUTUARIO_ALIASES: dict[str, tuple[str, ...]] = {
    "ref_bacen": ("REF_BACEN",),
    "documento": ("CD_CPF_CNPJ", "CPF_CNPJ", "CD_CNPJ_CPF"),
    "tipo_beneficiario": ("CD_TIPO_BENEFICIARIO", "TIPO_BENEFICIARIO"),
    "dap_caf": ("CD_DAP", "CD_CAF", "DAP", "CAF"),
}

PROPRIEDADE_ALIASES: dict[str, tuple[str, ...]] = {
    "ref_bacen": ("REF_BACEN",),
    "nu_ordem": ("NU_ORDEM", "NUM_ORDEM"),
    "documento": ("CD_CNPJ_CPF", "CD_CPF_CNPJ", "CPF_CNPJ"),
    "car": ("CD_CAR", "CAR", "CODIGO_CAR"),
    "sncr": ("CD_SNCR", "SNCR"),
    "nirf_cib": ("CD_NIRF", "NIRF", "CIB", "CD_CIB"),
}

OPERACAO_ALIASES: dict[str, tuple[str, ...]] = {
    "ref_bacen": ("REF_BACEN",),
    "nu_ordem": ("NU_ORDEM",),
    "data_emissao": ("DT_EMISSAO",),
    "data_vencimento": ("DT_VENCIMENTO",),
    "cnpj_if": ("CNPJ_IF",),
    "estado": ("CD_ESTADO",),
    "fonte_recurso": ("CD_FONTE_RECURSO",),
    "empreendimento": ("CD_EMPREENDIMENTO",),
    "programa": ("CD_PROGRAMA",),
    "subprograma": ("CD_SUBPROGRAMA",),
    "area_financiada": ("VL_AREA_FINANC",),
    "area_informada": ("VL_AREA_INFORMADA",),
    "bonus_car": ("PC_BONUS_CAR",),
}

COMPLEMENTO_ALIASES: dict[str, tuple[str, ...]] = {
    "ref_bacen": ("REF_BACEN",),
    "nu_ordem": ("NU_ORDEM",),
    "ref_bacen_efetivo": ("REF_BACEN_EFETIVO",),
    "agencia_if": ("AGENCIA_IF",),
    "municipio_ibge": ("CD_IBGE_MUNICIPIO",),
    "numero_cedula_if": ("NUM_CEDULA_IF",),
}

GLEBA_ALIASES: dict[str, tuple[str, ...]] = {
    "ref_bacen": ("REF_BACEN",),
    "nu_ordem": ("NU_ORDEM",),
    "identificador": ("NU_IDENTIFICADOR",),
    "indice_gleba": ("NU_INDICE_GLEBA",),
    "indice_ponto": ("NU_INDICE_PONTO",),
    "latitude": ("VL_LATITUDE",),
    "longitude": ("VL_LONGITUDE",),
    "altitude": ("CGL_VL_ALTITUDE", "VL_ALTITUDE"),
    "id_ponto": ("ID_PONTO",),
}

MMA_MCR_ALIASES: dict[str, tuple[str, ...]] = {
    "car": ("COD_IMOVEL", "CD_CAR", "CAR"),
    "status_imovel": ("STATUS_IMO", "STATUS_IMOVEL"),
    "condicao": ("CONDICAO",),
    "data_atualizacao": ("DATA_ATUAL", "DATA_ATUALIZACAO"),
    "area_declarada": ("AREA",),
    "area_total_ha": ("AREA_TOTAL_HA",),
    "modulos_fiscais": ("M_FISCAL", "MODULOS_FISCAIS"),
    "uf": ("UF",),
    "municipio": ("MUNICIPIO",),
    "codigo_municipio": ("COD_MUNICI", "CODIGO_MUNICIPIO"),
    "tipo_imovel": ("TIPO_IMOVE", "TIPO_IMOVEL"),
    "julgamento_status": ("JULG_STATUS",),
    "soma_desmatamento": ("SOMA_DESMAT",),
    "dentro_criterio": ("DENTRO_CRITERIO",),
    "criterio_aplicado": ("CRITERIO_APLICADO",),
    "resultados": ("RESULTADOS",),
    "bioma": ("BIOMAS", "BIOMA"),
}

ALIASES_BY_TYPE: dict[str, dict[str, tuple[str, ...]]] = {
    "mutuarios": MUTUARIO_ALIASES,
    "propriedades": PROPRIEDADE_ALIASES,
    "operacoes": OPERACAO_ALIASES,
    "complementos": COMPLEMENTO_ALIASES,
    "glebas": GLEBA_ALIASES,
    "mma_mcr": MMA_MCR_ALIASES,
}

INDEXES_BY_TYPE = {
    "mutuarios": (
        (
            "ix_mutuario_documento",
            "CREATE INDEX ix_mutuario_documento ON sicor_mutuario(documento_normalizado)",
        ),
        (
            "ix_mutuario_ref",
            "CREATE INDEX ix_mutuario_ref ON sicor_mutuario(ref_bacen)",
        ),
    ),
    "propriedades": (
        (
            "ix_propriedade_documento",
            "CREATE INDEX ix_propriedade_documento ON sicor_propriedade(documento_normalizado)",
        ),
        (
            "ix_propriedade_car",
            "CREATE INDEX ix_propriedade_car ON sicor_propriedade(car_normalizado)",
        ),
        (
            "ix_propriedade_ref",
            "CREATE INDEX ix_propriedade_ref ON sicor_propriedade(ref_bacen)",
        ),
    ),
    "operacoes": (
        (
            "ix_operacao_chave",
            "CREATE INDEX ix_operacao_chave ON sicor_operacao(ref_bacen, nu_ordem)",
        ),
    ),
    "complementos": (
        (
            "ix_complemento_chave",
            "CREATE INDEX ix_complemento_chave ON sicor_complemento_operacao(ref_bacen, nu_ordem)",
        ),
    ),
    "glebas": (
        (
            "ix_gleba_chave",
            "CREATE INDEX ix_gleba_chave ON sicor_ponto_gleba(ref_bacen, nu_ordem, indice_gleba, indice_ponto)",
        ),
        (
            "ix_gleba_wkt_chave",
            "CREATE INDEX ix_gleba_wkt_chave ON sicor_gleba_wkt(ref_bacen, nu_ordem, indice_gleba)",
        ),
    ),
    "mma_mcr": (
        ("ix_mma_mcr_car", "CREATE INDEX ix_mma_mcr_car ON mma_mcr(car_normalizado)"),
    ),
}

REQUIRED_BY_TYPE = {
    "mutuarios": ("ref_bacen", "documento"),
    "propriedades": ("ref_bacen", "car"),
    "operacoes": ("ref_bacen", "nu_ordem"),
    "complementos": ("ref_bacen", "nu_ordem"),
    "glebas": ("ref_bacen", "nu_ordem"),
    "mma_mcr": ("car",),
}


@dataclass(frozen=True)
class ImportResult:
    tipo: str
    arquivo: str
    total: int
    validas: int
    rejeitadas: int
    ignorado: bool = False

    def as_record(self) -> ImportRecord:
        return ImportRecord(**self.__dict__)


def _value(row: dict[str, str], aliases: Iterable[str]) -> str:
    return value_from_aliases(row, tuple(aliases))


def _validate_headers(
    first_row: dict[str, str],
    aliases: dict[str, tuple[str, ...]],
    required: tuple[str, ...],
) -> None:
    missing = [
        name
        for name in required
        if not any(alias in first_row for alias in aliases[name])
    ]
    if missing:
        available = ", ".join(sorted(first_row))
        raise ValueError(
            f"Campos obrigatórios ausentes: {', '.join(missing)}. Campos encontrados: {available}"
        )


def _begin_import(
    connection: sqlite3.Connection,
    tipo: str,
    path: Path,
    digest: str,
    escopo: str,
    validade_ate: str | None,
    source_reference: str | None,
) -> tuple[int, bool]:
    existing = connection.execute(
        "SELECT id, escopo FROM importacao WHERE tipo = ? AND sha256 = ?",
        (tipo, digest),
    ).fetchone()
    if existing:
        if existing["escopo"] != escopo:
            raise ValueError(
                "Arquivo já cadastrado em outro escopo. Revise a importação existente."
            )
        return int(existing["id"]), True
    cursor = connection.execute(
        "INSERT INTO importacao (tipo, arquivo, sha256, escopo, ativo, validade_ate) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (tipo, source_reference or str(path.resolve()), digest, escopo, validade_ate),
    )
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("Falha ao registrar a importação.")
    return int(row_id), False


def _integer(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decimal(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except (AttributeError, ValueError):
        return None


def import_file(
    connection: sqlite3.Connection,
    tipo: str,
    file_path: str | Path,
    *,
    escopo: str = "nacional",
    validade_ate: str | None = None,
    commit: bool = True,
    source_reference: str | None = None,
) -> ImportResult:
    if not escopo.strip():
        raise ValueError("Informe a competência e abrangência no escopo da carga.")
    if tipo == "mma_mcr" and escopo != "nacional":
        raise ValueError("A publicação MMA deve usar o escopo nacional.")
    if validade_ate:
        date.fromisoformat(validade_ate)
    connection.execute("SAVEPOINT carga")
    try:
        result = _import_file(
            connection,
            tipo,
            file_path,
            escopo.strip(),
            validade_ate,
            source_reference,
        )
        connection.execute("RELEASE carga")
        if commit:
            connection.commit()
        return result
    except Exception:
        connection.execute("ROLLBACK TO carga")
        connection.execute("RELEASE carga")
        raise


def _import_file(
    connection: sqlite3.Connection,
    tipo: str,
    file_path: str | Path,
    escopo: str,
    validade_ate: str | None,
    source_reference: str | None,
) -> ImportResult:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if tipo not in ALIASES_BY_TYPE:
        raise ValueError(f"Tipo de importação inválido: {tipo}")

    digest = file_sha256(path)
    import_id, ignored = _begin_import(
        connection,
        tipo,
        path,
        digest,
        escopo,
        validade_ate,
        source_reference,
    )
    if ignored:
        row = connection.execute(
            "SELECT * FROM importacao WHERE id = ?", (import_id,)
        ).fetchone()
        return ImportResult(
            tipo,
            str(path),
            row["total_linhas"],
            row["linhas_validas"],
            row["linhas_rejeitadas"],
            True,
        )

    for index_name, _ in INDEXES_BY_TYPE[tipo]:
        connection.execute(f"DROP INDEX IF EXISTS {index_name}")

    total = valid = rejected = 0
    rows = iter_rows(path)
    try:
        first = next(rows)
    except StopIteration as exc:
        raise ValueError(f"Arquivo sem registros: {path}") from exc

    aliases = ALIASES_BY_TYPE[tipo]
    required = REQUIRED_BY_TYPE[tipo]
    pending: list[tuple[Any, ...]] = []
    statement: str | None = None

    def flush() -> None:
        if pending and statement is not None:
            connection.executemany(statement, pending)
            pending.clear()

    def insert(sql: str, parameters: tuple[Any, ...]) -> None:
        nonlocal statement
        if statement is not None and statement != sql:
            flush()
        statement = sql
        pending.append(parameters)
        if len(pending) >= 2000:
            flush()

    _validate_headers(first, aliases, required)
    for row in chain((first,), rows):
        total += 1
        if tipo == "mma_mcr":
            car = _value(row, aliases["car"])
            car_normalized = normalize_car(car)
            if not car_normalized:
                rejected += 1
                continue
            insert(
                """INSERT INTO mma_mcr
                (importacao_id, car_original, car_normalizado, status_imovel,
                 condicao, data_atualizacao, area_declarada, area_total_ha,
                 modulos_fiscais, uf, municipio, codigo_municipio, tipo_imovel,
                 julgamento_status, soma_desmatamento, dentro_criterio,
                 criterio_aplicado, resultados, bioma)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    car,
                    car_normalized,
                    _value(row, aliases["status_imovel"]),
                    _value(row, aliases["condicao"]),
                    _value(row, aliases["data_atualizacao"]),
                    _value(row, aliases["area_declarada"]),
                    _value(row, aliases["area_total_ha"]),
                    _value(row, aliases["modulos_fiscais"]),
                    _value(row, aliases["uf"]),
                    _value(row, aliases["municipio"]),
                    _value(row, aliases["codigo_municipio"]),
                    _value(row, aliases["tipo_imovel"]),
                    _value(row, aliases["julgamento_status"]),
                    _value(row, aliases["soma_desmatamento"]),
                    _value(row, aliases["dentro_criterio"]),
                    _value(row, aliases["criterio_aplicado"]),
                    _value(row, aliases["resultados"]),
                    _value(row, aliases["bioma"]),
                ),
            )
            valid += 1
            continue
        ref_bacen = _value(row, aliases["ref_bacen"])
        if not ref_bacen:
            rejected += 1
            continue
        document = _value(row, aliases.get("documento", ()))
        if tipo == "mutuarios":
            MutuarioRow(ref_bacen=ref_bacen, documento=document)
            insert(
                """INSERT INTO sicor_mutuario
                (importacao_id, ref_bacen, documento_original, documento_normalizado,
                 documento_mascarado, tipo_beneficiario, dap_caf)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    ref_bacen,
                    document,
                    normalize_document(document),
                    int(is_masked_document(document)),
                    _value(row, aliases["tipo_beneficiario"]),
                    _value(row, aliases["dap_caf"]),
                ),
            )
        elif tipo == "propriedades":
            car = _value(row, aliases["car"])
            if not car:
                rejected += 1
                continue
            insert(
                """INSERT INTO sicor_propriedade
                (importacao_id, ref_bacen, nu_ordem, documento_original,
                 documento_normalizado, documento_mascarado, car_original,
                 car_normalizado, sncr, nirf_cib)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    ref_bacen,
                    _value(row, aliases["nu_ordem"]),
                    document,
                    normalize_document(document),
                    int(is_masked_document(document)),
                    car,
                    normalize_car(car),
                    _value(row, aliases["sncr"]),
                    _value(row, aliases["nirf_cib"]),
                ),
            )
        elif tipo == "operacoes":
            nu_ordem = _value(row, aliases["nu_ordem"])
            if not nu_ordem:
                rejected += 1
                continue
            insert(
                """INSERT INTO sicor_operacao
                (importacao_id, ref_bacen, nu_ordem, data_emissao, data_vencimento,
                 cnpj_if, estado, fonte_recurso, empreendimento, programa,
                 subprograma, area_financiada, area_informada, bonus_car)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    ref_bacen,
                    nu_ordem,
                    _value(row, aliases["data_emissao"]),
                    _value(row, aliases["data_vencimento"]),
                    _value(row, aliases["cnpj_if"]),
                    _value(row, aliases["estado"]),
                    _value(row, aliases["fonte_recurso"]),
                    _value(row, aliases["empreendimento"]),
                    _value(row, aliases["programa"]),
                    _value(row, aliases["subprograma"]),
                    _value(row, aliases["area_financiada"]),
                    _value(row, aliases["area_informada"]),
                    _value(row, aliases["bonus_car"]),
                ),
            )
        elif tipo == "complementos":
            nu_ordem = _value(row, aliases["nu_ordem"])
            if not nu_ordem:
                rejected += 1
                continue
            insert(
                """INSERT INTO sicor_complemento_operacao
                (importacao_id, ref_bacen, nu_ordem, ref_bacen_efetivo, agencia_if,
                 municipio_ibge, numero_cedula_if)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    ref_bacen,
                    nu_ordem,
                    _value(row, aliases["ref_bacen_efetivo"]),
                    _value(row, aliases["agencia_if"]),
                    _value(row, aliases["municipio_ibge"]),
                    _value(row, aliases["numero_cedula_if"]),
                ),
            )
        elif tipo == "glebas" and "GT_GEOMETRIA" in row:
            nu_ordem = _value(row, aliases["nu_ordem"])
            geometria = row.get("GT_GEOMETRIA", "").strip()
            indice = _integer(row.get("NU_INDICE", ""))
            if (
                not nu_ordem
                or not geometria
                or not geometria.upper().startswith(("POLYGON", "MULTIPOLYGON"))
            ):
                rejected += 1
                continue
            insert(
                """INSERT INTO sicor_gleba_wkt
                (importacao_id, ref_bacen, nu_ordem, indice_gleba, geometria_wkt)
                VALUES (?, ?, ?, ?, ?)""",
                (import_id, ref_bacen, nu_ordem, indice, geometria),
            )
        else:
            nu_ordem = _value(row, aliases["nu_ordem"])
            indice_gleba = _integer(_value(row, aliases["indice_gleba"]))
            indice_ponto = _integer(_value(row, aliases["indice_ponto"]))
            latitude = _decimal(_value(row, aliases["latitude"]))
            longitude = _decimal(_value(row, aliases["longitude"]))
            if not nu_ordem or None in (
                indice_gleba,
                indice_ponto,
                latitude,
                longitude,
            ):
                rejected += 1
                continue
            insert(
                """INSERT INTO sicor_ponto_gleba
                (importacao_id, ref_bacen, nu_ordem, identificador, indice_gleba,
                 indice_ponto, latitude, longitude, altitude, id_ponto)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    import_id,
                    ref_bacen,
                    nu_ordem,
                    _value(row, aliases["identificador"]),
                    indice_gleba,
                    indice_ponto,
                    latitude,
                    longitude,
                    _value(row, aliases["altitude"]),
                    _value(row, aliases["id_ponto"]),
                ),
            )
        valid += 1
    flush()
    if not valid or rejected:
        raise ValueError(
            f"Carga não ativada: {valid} registros válidos e {rejected} rejeitados. "
            "A versão anterior foi preservada."
        )
    if file_sha256(path) != digest:
        raise ValueError(
            "O arquivo foi alterado durante a importação; a versão anterior foi preservada."
        )
    connection.execute(
        """UPDATE importacao SET total_linhas = ?, linhas_validas = ?,
        linhas_rejeitadas = ? WHERE id = ?""",
        (total, valid, rejected, import_id),
    )
    for _, create_sql in INDEXES_BY_TYPE[tipo]:
        connection.execute(create_sql)
    connection.execute(
        "UPDATE importacao SET ativo = 0 WHERE tipo = ? AND escopo = ?",
        (tipo, escopo),
    )
    connection.execute("UPDATE importacao SET ativo = 1 WHERE id = ?", (import_id,))
    return ImportResult(tipo, str(path), total, valid, rejected)
