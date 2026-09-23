from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from qgis_plugin_microcredito.application.hashing import file_sha256
from qgis_plugin_microcredito.domain.models import mapping_to_dict


def collect_database_evidence(connection: sqlite3.Connection) -> dict[str, Any]:
    """Coleta a versão das bases locais consultadas para registrar no relatório."""
    rows = connection.execute(
        """SELECT tipo, arquivo, sha256, importado_em, total_linhas,
                  linhas_validas, linhas_rejeitadas, validade_ate, escopo, id
             FROM importacao WHERE ativo = 1
         ORDER BY tipo, id DESC"""
    ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = mapping_to_dict(row)
        latest.setdefault(str(item.get("tipo") or ""), item)

    mte_row = connection.execute(
        "SELECT * FROM mte_publicacao ORDER BY id DESC LIMIT 1"
    ).fetchone()
    mte: dict[str, Any] = mapping_to_dict(mte_row) if mte_row else {}
    if not mte:
        legacy = connection.execute(
            """SELECT COUNT(*) AS total_registros,
                      MAX(fonte_url) AS fonte_url,
                      MAX(arquivo_fonte) AS arquivo_fonte,
                      MAX(importado_em) AS importado_em
                 FROM trabalho_escravo"""
        ).fetchone()
        if legacy and legacy["total_registros"]:
            mte = {
                **mapping_to_dict(legacy),
                "sha256": "",
                "validade_ate": None,
                "problema": (
                    "A carga legada foi consultada, mas sua validade administrativa "
                    "ainda não foi homologada."
                ),
            }
    if (
        mte
        and connection.execute("SELECT COUNT(*) FROM trabalho_escravo").fetchone()[0]
        != mte["total_registros"]
    ):
        mte["total_registros"] = 0
        mte["problema"] = "A contagem atual não corresponde à publicação validada."
    mma = latest.get("mma_mcr")
    if (
        mma
        and connection.execute(
            "SELECT COUNT(*) FROM mma_mcr WHERE importacao_id=?", (mma["id"],)
        ).fetchone()[0]
        != mma["linhas_validas"]
    ):
        mma["linhas_validas"] = 0
        mma["problema"] = "A contagem atual não corresponde à publicação validada."
    return {
        "importacoes_sicor_mma": [mapping_to_dict(row) for row in rows],
        "mma_fonte": {
            **latest.get("mma_mcr", {}),
            "fonte_url": (
                "https://www.gov.br/mma/pt-br/assuntos/controle-ao-desmatamento-queimadas-e-"
                "ordenamento-ambiental-territorial/controle-do-desmatamento-1/"
                "atendimento-ao-manual-de-credito-rural"
            ),
        },
        "mte_fonte": mte,
    }


def geometry_source_from_geojson(path: str | Path) -> str:
    """Recupera do GeoJSON exportado o arquivo cadastral que forneceu o polígono."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        features = payload.get("features") or []
        if features:
            properties = features[0].get("properties") or {}
            return str(properties.get("fonte_arquivo") or "")
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return ""


def file_evidence(path: str | Path) -> dict[str, Any]:
    candidate = Path(str(path))
    try:
        stat = candidate.stat()
        return {
            "arquivo": str(candidate),
            "sha256": file_sha256(candidate),
            "tamanho_bytes": int(stat.st_size),
            "modificado_em": datetime.fromtimestamp(stat.st_mtime)
            .astimezone()
            .isoformat(timespec="seconds"),
        }
    except OSError:
        return {"arquivo": str(candidate)}
