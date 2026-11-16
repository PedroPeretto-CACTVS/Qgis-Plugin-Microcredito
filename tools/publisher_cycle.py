"""Cria e valida a evidência da revisão quinzenal das bases oficiais."""

from __future__ import annotations

import argparse
import html
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from qgis_plugin_microcredito.domain.base_catalog import BASE_DEFINITIONS

RESULTS = {
    "pendente",
    "sem_nova_edicao",
    "nova_edicao",
    "fonte_indisponivel",
    "revisao_manual",
}
MODES = {"automatic", "assisted", "captcha", "authenticated"}


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Data/hora deve informar fuso horário.")
    return parsed.astimezone(UTC)


def _https(value: object) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Toda fonte deve usar página oficial HTTPS.")
    return text


def load_source_config(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Versão do inventário de fontes incompatível.")
    if document.get("cadence_days") != 14:
        raise ValueError("A rotina do projeto deve permanecer quinzenal (14 dias).")
    raw_sources = document.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("Inventário de fontes ausente.")
    expected = {item.identifier for item in BASE_DEFINITIONS}
    identifiers = {
        str(item.get("id")) for item in raw_sources if isinstance(item, dict)
    }
    if identifiers != expected or len(raw_sources) != len(expected):
        raise ValueError("O inventário deve conter exatamente as 11 bases lógicas.")
    for source in raw_sources:
        if not isinstance(source, dict):
            raise ValueError("Fonte inválida no inventário.")
        if source.get("mode") not in MODES:
            raise ValueError(f"Modo inválido para {source.get('id')}.")
        _https(source.get("official_page_url"))
    return document


def start_cycle(
    config_path: Path,
    destination: Path,
    checked_at: datetime | None = None,
) -> dict[str, object]:
    config = load_source_config(config_path)
    started = (checked_at or datetime.now().astimezone()).astimezone()
    sources = []
    for source in config["sources"]:
        sources.append(
            {
                "id": source["id"],
                "label": source["label"],
                "mode": source["mode"],
                "official_page_url": source["official_page_url"],
                "result": "pendente",
                "checked_at": None,
                "source_date": None,
                "published_version": None,
                "official_artifact_url": None,
                "artifact_sha256": None,
                "package_candidate": None,
                "evidence_note": None,
            }
        )
    document: dict[str, object] = {
        "schema_version": 1,
        "cadence_days": 14,
        "started_at": started.isoformat(),
        "next_due_at": (started + timedelta(days=14)).isoformat(),
        "status": "em_revisao",
        "sources": sources,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    render_report(document, destination.with_suffix(".html"))
    return document


def validate_cycle(
    document: dict[str, object], *, require_complete: bool
) -> dict[str, int]:
    raw_sources = document.get("sources")
    if document.get("schema_version") != 1 or not isinstance(raw_sources, list):
        raise ValueError("Relatório quinzenal inválido.")
    expected = {item.identifier for item in BASE_DEFINITIONS}
    identifiers = {
        str(item.get("id")) for item in raw_sources if isinstance(item, dict)
    }
    if identifiers != expected or len(raw_sources) != len(expected):
        raise ValueError("A revisão não cobre exatamente as 11 bases lógicas.")
    summary = {result: 0 for result in RESULTS}
    for source in raw_sources:
        if not isinstance(source, dict):
            raise ValueError("Registro de fonte inválido.")
        result = source.get("result")
        if result not in RESULTS:
            raise ValueError(f"Resultado inválido para {source.get('id')}.")
        summary[str(result)] += 1
        _https(source.get("official_page_url"))
        if result == "pendente":
            if require_complete:
                raise ValueError(f"Fonte ainda pendente: {source.get('id')}.")
            continue
        checked_at = source.get("checked_at")
        if not isinstance(checked_at, str):
            raise ValueError(f"Consulta sem data/hora: {source.get('id')}.")
        _timestamp(checked_at)
        note = source.get("evidence_note")
        if not isinstance(note, str) or not note.strip():
            raise ValueError(f"Consulta sem evidência resumida: {source.get('id')}.")
        if result == "nova_edicao":
            for field in (
                "source_date",
                "published_version",
                "official_artifact_url",
                "artifact_sha256",
                "package_candidate",
            ):
                if not source.get(field):
                    raise ValueError(f"Nova edição de {source.get('id')} sem {field}.")
            _https(source.get("official_artifact_url"))
            digest = str(source.get("artifact_sha256"))
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest.lower()
            ):
                raise ValueError(f"SHA-256 inválido para {source.get('id')}.")
    return summary


def render_report(document: dict[str, object], destination: Path) -> None:
    rows = []
    for source in document.get("sources", []):
        if not isinstance(source, dict):
            continue
        url = _https(source.get("official_page_url"))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(source.get('label', '')))}</td>"
            f"<td>{html.escape(str(source.get('mode', '')))}</td>"
            f"<td>{html.escape(str(source.get('result', '')))}</td>"
            f"<td>{html.escape(str(source.get('checked_at') or '—'))}</td>"
            f'<td><a href="{html.escape(url, quote=True)}">fonte oficial</a></td>'
            f"<td>{html.escape(str(source.get('evidence_note') or '—'))}</td>"
            "</tr>"
        )
    page = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Revisão quinzenal das bases</title>
<style>body{{font-family:Arial,sans-serif;margin:32px;color:#183c31}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd8d3;padding:8px;text-align:left}}th{{background:#e7f0ec}}</style>
</head><body><h1>Revisão quinzenal das bases</h1>
<p>Iniciada em {html.escape(str(document.get("started_at", "")))}. Próxima revisão até {html.escape(str(document.get("next_due_at", "")))}.</p>
<table><thead><tr><th>Base</th><th>Modo</th><th>Resultado</th><th>Consultada em</th><th>Origem</th><th>Evidência</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></body></html>"""
    destination.write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start")
    start.add_argument("--config", type=Path, required=True)
    start.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "start":
        start_cycle(arguments.config, arguments.output)
        print(f"Ciclo quinzenal iniciado: {arguments.output}")
        return
    document = json.loads(arguments.input.read_text(encoding="utf-8"))
    summary = validate_cycle(document, require_complete=True)
    document["status"] = "concluida"
    arguments.input.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    render_report(document, arguments.input.with_suffix(".html"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
