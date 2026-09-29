from __future__ import annotations

import copy
import hashlib
import html
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from qgis_plugin_microcredito.application.owner_documents import (
    validate_report_owner_documents,
)
from qgis_plugin_microcredito.application.pre_analysis import build_pre_analysis
from qgis_plugin_microcredito.domain.policy import (
    aggregate,
    evaluate_lists,
    list_message,
)

from .map_output import MAP_PALETTE, MAP_STYLE_BY_CODE

GREEN = colors.HexColor("#165C41")
PALE_GREEN = colors.HexColor("#EDF5F1")
PALE_YELLOW = colors.HexColor("#FFF7DF")
GRID = colors.HexColor("#CBD7D2")
TEXT = colors.HexColor("#22302B")
MUTED = colors.HexColor("#65736E")
MTE_SOURCE_URL = "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/cadastro_de_empregadores.csv"
MTE_SOURCE_NAME = "Cadastro de Empregadores do Ministério do Trabalho e Emprego (MTE)"
PDF_DOCUMENT_LIMIT = 50


def _escape(value: object) -> str:
    return html.escape(str(value if value not in (None, "") else "Não informado"))


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=23,
            textColor=GREEN,
            spaceAfter=2 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DocumentTitle",
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=GREEN,
            spaceBefore=2 * mm,
            spaceAfter=3 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=GREEN,
            spaceBefore=6 * mm,
            spaceAfter=2 * mm,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodySmall",
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=TEXT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Cell", fontName="Helvetica", fontSize=7.5, leading=9, textColor=TEXT
        )
    )
    styles.add(
        ParagraphStyle(
            name="CellWhite",
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Foot", fontName="Helvetica", fontSize=7, leading=9, textColor=MUTED
        )
    )
    return styles


def _p(value: object, style) -> Paragraph:
    return Paragraph(_escape(value), style)


def _footer(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(GRID)
    canvas.line(15 * mm, 14 * mm, 195 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(
        15 * mm, 9 * mm, "Pré-análise socioambiental - apoio à decisão técnica"
    )
    canvas.drawRightString(195 * mm, 9 * mm, f"Página {document.page}")
    canvas.restoreState()


def _label(value: object) -> str:
    return {
        "ocorrencia_para_analise": "Ocorrência para análise",
        "sem_ocorrencia_identificada": "Sem ocorrência identificada",
        "inconclusivo": "Inconclusivo",
    }.get(str(value), str(value or "Não informado"))


def _observation(item: dict[str, object]) -> str:
    if item.get("motivo"):
        return str(item["motivo"])
    occurrences = item.get("ocorrencias") or []
    if item.get("codigo") == "desmatamento_pos_2020" and occurrences:
        years = sorted(
            {
                str(row.get("atributos", {}).get("year"))
                for row in occurrences
                if row.get("atributos", {}).get("year")
            }
        )
        text = "Anos detectados: " + ", ".join(years)
        if item.get("geometrias_reparadas"):
            text += ". Geometria da fonte reparada para executar o cruzamento"
        return text
    if occurrences:
        first = occurrences[0].get("atributos", {})
        text = "; ".join(f"{key}: {value}" for key, value in list(first.items())[:3])
    else:
        text = "Base consultada sem interseção com o imóvel."
    if item.get("geometrias_reparadas"):
        text += (
            " Geometria da fonte reparada automaticamente para executar o cruzamento."
        )
    return text


def _table(data, widths, header=True):
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), GREEN),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#F6F9F7")],
            ),
        ]
    return Table(
        data,
        colWidths=widths,
        repeatRows=1 if header else 0,
        splitByRow=1,
        splitInRow=1,
        style=TableStyle(commands),
    )


def _document_values(values) -> list[str]:
    return list(
        dict.fromkeys(str(value) for value in (values or []) if str(value).strip())
    )


def _document_summary(values, limit: int = 10) -> str:
    documents = _document_values(values)
    if not documents:
        return "Nenhum"
    shown = documents[:limit]
    text = ", ".join(shown)
    omitted = len(documents) - len(shown)
    if omitted:
        text += f" e mais {omitted}. A lista completa está no JSON de auditoria."
    return text


def _format_area_ha(value: object) -> str:
    try:
        area = float(value or 0)
    except (TypeError, ValueError):
        return "Não informado"
    text = f"{area:.4f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") + " ha"


def _overlap_percentage(overlap_ha: object, car_area_ha: object) -> float | None:
    try:
        overlap = float(overlap_ha)
        car_area = float(car_area_ha)
    except (TypeError, ValueError):
        return None
    if car_area <= 0 or overlap < 0:
        return None
    return min(100.0, overlap / car_area * 100)


def _format_percentage(value: object) -> str:
    if value is None:
        return "Não informado"
    try:
        percentage = float(value)
    except (TypeError, ValueError):
        return "Não informado"
    text = f"{percentage:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") + "%"


def _map_legend(styles, visible_entries, car_area_ha=None):
    rows = [
        [
            "",
            _p("Legenda do mapa", styles["CellWhite"]),
            _p("Área no CAR", styles["CellWhite"]),
            _p("% do CAR", styles["CellWhite"]),
        ]
    ]
    car_area = (
        _format_area_ha(car_area_ha)
        if car_area_ha not in (None, "")
        else "Não informado"
    )
    car_percentage = (
        "100%"
        if _overlap_percentage(car_area_ha, car_area_ha) is not None
        else "Não informado"
    )
    entries = [
        (
            "#FFD600",
            "Imóvel analisado (CAR) — contorno escuro",
            car_area,
            car_percentage,
        )
    ]
    seen = set()
    for item in visible_entries or []:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            color = str(item.get("color") or "").strip()
            overlap = item.get("area_sobreposta_ha")
            area = _format_area_ha(overlap)
            percentage = _format_percentage(_overlap_percentage(overlap, car_area_ha))
        else:
            try:
                color, label = item
            except (TypeError, ValueError):
                continue
            area = "Não informado"
            percentage = "Não informado"
        if not label or not color or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        entries.append((color, label, area, percentage))
    for _, label, area, percentage in entries:
        rows.append(
            [
                "",
                _p(label, styles["Cell"]),
                _p(area, styles["Cell"]),
                _p(percentage, styles["Cell"]),
            ]
        )
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), GREEN),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 1), (-1, -1), 0.25, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for row, (color, _, _, _) in enumerate(entries, 1):
        commands.append(("BACKGROUND", (0, row), (0, row), colors.HexColor(color)))
        commands.append(
            (
                "BOX",
                (0, row),
                (0, row),
                1.1,
                colors.HexColor("#14181F") if row == 1 else colors.HexColor(color),
            )
        )
    return Table(
        rows,
        colWidths=[10 * mm, 95 * mm, 45 * mm, 30 * mm],
        repeatRows=1,
        style=TableStyle(commands),
    )


def _visible_map_entries(analysis: dict[str, object]) -> list[dict[str, object]]:
    """Usa o inventário produzido pelo mapa; mantém compatibilidade com análises antigas."""
    layers = analysis.get("ambiental", {}).get("camadas", [])
    areas_by_code = {
        str(item.get("codigo") or ""): item.get("area_sobreposta_ha", 0)
        for item in layers
    }
    areas_by_name = {
        str(item.get("fonte") or "").casefold(): item.get("area_sobreposta_ha", 0)
        for item in layers
    }
    if "mapa_legenda" in analysis:
        entries = []
        for raw in analysis.get("mapa_legenda") or []:
            item = dict(raw)
            code = str(item.get("code") or "")
            label = str(item.get("label") or "")
            item["area_sobreposta_ha"] = areas_by_code.get(
                code, areas_by_name.get(label.casefold(), 0)
            )
            entries.append(item)
        return entries
    entries = []
    for item in layers:
        if not item.get("quantidade"):
            continue
        code = str(item.get("codigo") or "")
        fallback = next(
            (style for style in MAP_PALETTE if style[1] == item.get("fonte")),
            ("#5B6470", str(item.get("fonte") or code or "Camada ambiental")),
        )
        color, default_label = MAP_STYLE_BY_CODE.get(code, fallback)
        entries.append(
            {
                "code": code,
                "label": str(item.get("fonte") or default_label),
                "color": color,
                "area_sobreposta_ha": item.get("area_sobreposta_ha", 0),
            }
        )
    return entries


def _attributes_text(attributes: dict[str, object]) -> str:
    if not attributes:
        return "Sem atributos adicionais na seleção de campos da camada."
    return "; ".join(f"{key}: {value}" for key, value in attributes.items())


def _report_payload(analysis: dict[str, object]) -> dict[str, object]:
    """Mantém no artefato somente evidências públicas, sem caminhos locais."""
    payload = copy.deepcopy(analysis)
    payload["documentos_proprietario_possuidor"] = (
        validate_report_owner_documents(
            payload.get("documentos_proprietario_possuidor") or []
        )
    )
    outcomes = evaluate_lists(
        payload.get("mma_mcr") or [],
        payload.get("trabalho_escravo") or [],
        payload,
        payload.get("documentos_consultados_mte") or [],
    )
    payload["resultado_fontes"] = outcomes
    payload["resultado_geral"] = aggregate(
        [
            payload.get("ambiental", {}).get("resultado_geral", "inconclusivo"),
            *outcomes.values(),
        ]
    )
    payload["pre_analise"] = build_pre_analysis(payload)
    payload["versao_motor"] = "0.9.5"
    payload["versao_regras"] = payload["pre_analise"]["versao_regras"]
    recorded_decision = payload.get("decisao_tecnica") or {}
    if (
        recorded_decision.get("codigo") not in (None, "", "pendente")
        and recorded_decision.get("pre_analise_sha256")
        != payload["pre_analise"].get("sha256")
    ):
        payload["decisao_tecnica_anterior_invalidada"] = {
            "motivo": (
                "Os resultados ou a versão das regras mudaram após a decisão; "
                "é necessária nova decisão técnica."
            ),
            "registrada_em": recorded_decision.get("registrada_em"),
        }
        payload.pop("decisao_tecnica", None)
    payload.setdefault(
        "decisao_tecnica",
        {
            "codigo": "pendente",
            "rotulo": "Pendente de decisão técnica",
            "justificativa": "",
            "responsabilidade": (
                "Decisão humana do técnico; não produzida automaticamente pela ferramenta."
            ),
        },
    )
    payload["geometria_sha256"] = (payload.get("evidencia_geometria") or {}).get(
        "sha256"
    )
    payload["edicoes_consultadas"] = [
        {
            key: item.get(key)
            for key in (
                "id",
                "tipo",
                "escopo",
                "sha256",
                "importado_em",
                "validade_ate",
            )
        }
        for item in payload.get("importacoes_sicor_mma", [])
    ]

    payload.pop("operacao", None)
    payload.pop("documentos_associados", None)
    payload.pop("importacoes_sicor_mma", None)
    map_path = payload.pop("mapa_path", "")
    if map_path:
        payload["_mapa_path_interno"] = map_path
    geometry_origin = payload.get("origem_geometria")
    payload["fonte_geometria_url"] = (
        "https://consulta.car.gov.br/geoservices"
        if geometry_origin == "poligono_cadastral_sicar"
        else "https://dadosabertos.bcb.gov.br/dataset/"
        if geometry_origin == "gleba_operacao_sicor"
        else "Dados sintéticos de demonstração"
        if payload.get("demonstracao")
        else "Origem não identificada"
    )
    payload.pop("geometria_empreendimento", None)
    payload.pop("fonte_geometria", None)
    payload.pop("evidencia_geometria", None)
    if geometry_origin == "gleba_operacao_sicor":
        payload["origem_geometria"] = "gleba_associada_ao_car"

    mma_source = payload.get("mma_fonte") or {}
    for key in ("arquivo",):
        mma_source.pop(key, None)
    for item in payload.get("mma_mcr") or []:
        item.pop("fonte_arquivo", None)

    mte_source = payload.get("mte_fonte") or {}
    mte_source.pop("arquivo_fonte", None)
    for item in payload.get("trabalho_escravo") or []:
        item.pop("arquivo_fonte", None)

    for item in payload.get("ambiental", {}).get("camadas", []):
        for key in (
            "arquivo",
            "arquivo_consultado",
            "arquivo_tamanho_bytes",
            "arquivo_modificado_em",
        ):
            item.pop(key, None)
    return payload


def _public_json_payload(payload: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(payload)
    result.pop("_mapa_path_interno", None)
    return result


def _database_evidence_story(analysis: dict[str, object], styles):
    """Compõe o dossiê auditável das consultas realizadas para uma análise."""
    s = styles
    story = [PageBreak(), Paragraph("Evidências e rastreabilidade", s["Section"])]
    story.append(
        Paragraph(
            "Esta seção registra as bases, as versões locais, os documentos pesquisados e as feições que sustentam cada resultado, inclusive quando nenhuma ocorrência foi localizada.",
            s["BodySmall"],
        )
    )

    story.append(Paragraph("Geometria submetida aos cruzamentos", s["Section"]))
    geometry_rows = [
        [
            _p("Origem", s["CellWhite"]),
            _p("Fonte pública para obtenção dos dados", s["CellWhite"]),
            _p("Identificador consultado", s["CellWhite"]),
        ],
        [
            _p(analysis.get("origem_geometria"), s["Cell"]),
            _p(analysis.get("fonte_geometria_url"), s["Cell"]),
            _p(analysis.get("car"), s["Cell"]),
        ],
    ]
    story.append(_table(geometry_rows, [40 * mm, 86 * mm, 54 * mm]))

    story.append(Paragraph("Evidência da consulta MMA/MCR", s["Section"]))
    mma_source = analysis.get("mma_fonte") or {}
    mma = analysis.get("mma_mcr") or []
    mma_description = (
        "Consulta inconclusiva"
        if analysis.get("resultado_fontes", {}).get("mma_mcr") == "inconclusivo"
        else f"{len(mma)} registro(s) para o CAR"
    )
    story.append(
        _table(
            [
                [
                    _p("Fonte pública", s["CellWhite"]),
                    _p("Importado em", s["CellWhite"]),
                    _p("Registros válidos", s["CellWhite"]),
                    _p("Resultado da busca", s["CellWhite"]),
                ],
                [
                    _p(mma_source.get("fonte_url"), s["Cell"]),
                    _p(
                        mma_source.get("importado_em")
                        or (mma[0].get("importado_em") if mma else "Não informado"),
                        s["Cell"],
                    ),
                    _p(mma_source.get("linhas_validas"), s["Cell"]),
                    _p(mma_description, s["Cell"]),
                ],
            ],
            [78 * mm, 34 * mm, 28 * mm, 40 * mm],
        )
    )
    if mma:
        rows = [
            [
                _p(x, s["CellWhite"])
                for x in (
                    "CAR",
                    "Situação",
                    "Condição",
                    "Critério",
                    "Julgamento",
                    "Supressão (ha)",
                )
            ]
        ]
        for item in mma:
            rows.append(
                [
                    _p(item.get("car_original"), s["Cell"]),
                    _p(item.get("status_imovel"), s["Cell"]),
                    _p(item.get("condicao"), s["Cell"]),
                    _p(item.get("dentro_criterio"), s["Cell"]),
                    _p(item.get("julgamento_status"), s["Cell"]),
                    _p(item.get("soma_desmatamento"), s["Cell"]),
                ]
            )
        story.append(Spacer(1, 2 * mm))
        story.append(
            _table(rows, [54 * mm, 20 * mm, 30 * mm, 20 * mm, 34 * mm, 22 * mm])
        )

    story.append(
        Paragraph("Consulta ao MTE — trabalho análogo à escravidão", s["Section"])
    )
    mte_source = analysis.get("mte_fonte") or {}
    consulted_documents = _document_values(analysis.get("documentos_consultados_mte"))
    labor = analysis.get("trabalho_escravo") or []
    mte_outcome = analysis.get("resultado_fontes", {}).get("mte")
    labor_description = f"{len(labor)} ocorrência(s) encontrada(s)"
    if mte_outcome == "inconclusivo":
        labor_description += "; validade da publicação pendente"
    story.append(
        Paragraph(
            f"Fonte consultada: <b>{MTE_SOURCE_NAME}</b> — {_escape(mte_source.get('fonte_url') or MTE_SOURCE_URL)}",
            s["BodySmall"],
        )
    )
    story.append(
        _table(
            [
                [
                    _p("Fonte pública", s["CellWhite"]),
                    _p("Importado em", s["CellWhite"]),
                    _p("Resultado", s["CellWhite"]),
                ],
                [
                    _p(mte_source.get("fonte_url") or MTE_SOURCE_URL, s["Cell"]),
                    _p(mte_source.get("importado_em"), s["Cell"]),
                    _p(labor_description, s["Cell"]),
                ],
            ],
            [100 * mm, 38 * mm, 42 * mm],
        )
    )
    shown_documents = consulted_documents[:PDF_DOCUMENT_LIMIT]
    omitted_documents = len(consulted_documents) - len(shown_documents)
    note = f"CPF/CNPJ pesquisados: {len(consulted_documents)}."
    if omitted_documents:
        note += (
            f" O PDF apresenta os primeiros {len(shown_documents)}; os {omitted_documents} restantes "
            "permanecem na lista completa do JSON de auditoria."
        )
    story.append(Paragraph(note, s["BodySmall"]))
    document_rows = [
        [
            _p("CPF/CNPJ pesquisado", s["CellWhite"]),
            _p("CPF/CNPJ pesquisado", s["CellWhite"]),
        ]
    ]
    displayed = shown_documents or ["Nenhum"]
    for index in range(0, len(displayed), 2):
        pair = displayed[index : index + 2]
        document_rows.append(
            [_p(pair[0], s["Cell"]), _p(pair[1] if len(pair) > 1 else "", s["Cell"])]
        )
    story.append(_table(document_rows, [90 * mm, 90 * mm]))
    story.append(
        Paragraph(
            f"Total carregado na base da consulta: {_escape(mte_source.get('total_registros'))} registros.",
            s["Foot"],
        )
    )
    if labor:
        rows = [
            [
                _p(x, s["CellWhite"])
                for x in (
                    "CPF/CNPJ",
                    "Empregador",
                    "Ano ação",
                    "Trabalhadores",
                    "Decisão",
                    "Inclusão",
                )
            ]
        ]
        for item in labor:
            rows.append(
                [
                    _p(item.get("documento_original"), s["Cell"]),
                    _p(item.get("empregador"), s["Cell"]),
                    _p(item.get("ano_acao_fiscal"), s["Cell"]),
                    _p(item.get("trabalhadores_envolvidos"), s["Cell"]),
                    _p(item.get("decisao_procedencia"), s["Cell"]),
                    _p(item.get("inclusao_cadastro"), s["Cell"]),
                ]
            )
        story.append(Spacer(1, 2 * mm))
        story.append(
            _table(rows, [32 * mm, 48 * mm, 20 * mm, 23 * mm, 34 * mm, 23 * mm])
        )

    story.append(Paragraph("Evidências dos cruzamentos territoriais", s["Section"]))
    for item in analysis.get("ambiental", {}).get("camadas", []):
        layer_story = [
            Paragraph(
                str(item.get("fonte") or item.get("codigo") or "Camada"),
                s["DocumentTitle"],
            ),
            Paragraph(
                f"Fonte pública para download/consulta: {_escape(item.get('url_fonte'))}",
                s["Foot"],
            ),
        ]
        rows = [
            [
                _p("Resultado", s["CellWhite"]),
                _p("CRS", s["CellWhite"]),
                _p("Total na fonte", s["CellWhite"]),
                _p("Feições intersectadas", s["CellWhite"]),
                _p("Área sobreposta (ha)", s["CellWhite"]),
            ],
            [
                _p(_label(item.get("resultado")), s["Cell"]),
                _p(item.get("crs_fonte"), s["Cell"]),
                _p(item.get("total_fonte"), s["Cell"]),
                _p(item.get("quantidade", 0), s["Cell"]),
                _p(item.get("area_sobreposta_ha", 0), s["Cell"]),
            ],
        ]
        layer_story.append(_table(rows, [43 * mm, 25 * mm, 34 * mm, 39 * mm, 39 * mm]))
        layer_story.append(
            Paragraph(
                f"Referência: {_escape(item.get('referencia_regulatoria'))}. {_escape(item.get('motivo') or item.get('orientacao_revisao'))}",
                s["Foot"],
            )
        )
        if item.get("geometrias_reparadas"):
            identifiers = ", ".join(
                str(value) for value in item["geometrias_reparadas"]
            )
            layer_story.append(
                Paragraph(
                    f"Aviso de integridade: a geometria da fonte foi reparada para o cruzamento (FID {_escape(identifiers)}). Confira a feição original antes da decisão.",
                    s["BodySmall"],
                )
            )
        occurrences = item.get("ocorrencias") or []
        if not occurrences:
            description = (
                "Nenhuma feição dessa base intersectou a geometria analisada."
                if item.get("resultado") == "sem_ocorrencia_identificada"
                else "Verificação inconclusiva; não é possível afirmar ausência de ocorrência."
            )
            layer_story.append(Paragraph(description, s["BodySmall"]))
        story.append(KeepTogether(layer_story))
        if occurrences:
            detail_rows = [
                [
                    _p("FID na fonte", s["CellWhite"]),
                    _p("Área (ha)", s["CellWhite"]),
                    _p("Atributos que identificam a ocorrência", s["CellWhite"]),
                ]
            ]
            for occurrence in occurrences:
                detail_rows.append(
                    [
                        _p(occurrence.get("fid"), s["Cell"]),
                        _p(occurrence.get("area_ha"), s["Cell"]),
                        _p(
                            _attributes_text(occurrence.get("atributos") or {}),
                            s["Cell"],
                        ),
                    ]
                )
            story.append(Spacer(1, 2 * mm))
            story.append(_table(detail_rows, [28 * mm, 28 * mm, 124 * mm]))
    return story


def _pre_analysis_story(analysis: dict[str, object], styles):
    """Apresenta a interpretação das regras e separa a decisão humana."""
    s = styles
    pre_analysis = analysis.get("pre_analise") or build_pre_analysis(analysis)
    classification = str(
        pre_analysis.get("classificacao_geral") or "inconclusivo"
    )
    background = (
        PALE_GREEN if classification == "sem_indicio_impedimento" else PALE_YELLOW
    )
    story = [
        Table(
            [
                [
                    Paragraph("Resumo da pré-análise", s["Cell"]),
                    Paragraph(
                        f"<b>{_escape(pre_analysis.get('classificacao_geral_rotulo'))}</b>",
                        s["BodySmall"],
                    ),
                ]
            ],
            colWidths=[42 * mm, 138 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), background),
                    ("BOX", (0, 0), (-1, -1), 0.8, GREEN),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("PADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        ),
        Spacer(1, 2 * mm),
        Paragraph(_escape(pre_analysis.get("resumo")), s["BodySmall"]),
        Paragraph("Entendimento das regras e conclusão preliminar", s["Section"]),
    ]
    rows = [
        [
            _p(value, s["CellWhite"])
            for value in (
                "Regra/fonte",
                "Conclusão preliminar",
                "Fundamento",
                "Providência técnica",
            )
        ]
    ]
    for item in pre_analysis.get("regras") or []:
        foundation = (
            f"{item.get('entendimento_regra', '')} Resultado: "
            f"{item.get('fundamento_resultado', '')}"
        )
        reference = str(item.get("referencia") or "").strip()
        if reference:
            foundation += f" Referência: {reference}."
        rows.append(
            [
                _p(item.get("regra"), s["Cell"]),
                _p(item.get("classificacao_rotulo"), s["Cell"]),
                _p(foundation, s["Cell"]),
                _p(item.get("providencia_tecnica"), s["Cell"]),
            ]
        )
    story.append(_table(rows, [36 * mm, 38 * mm, 58 * mm, 48 * mm]))

    decision = analysis.get("decisao_tecnica") or {}
    story.extend(
        [
            Paragraph("Decisão do técnico responsável", s["Section"]),
            _table(
                [
                    [
                        _p("Decisão", s["CellWhite"]),
                        _p("Justificativa", s["CellWhite"]),
                        _p("Registrada em", s["CellWhite"]),
                    ],
                    [
                        _p(
                            decision.get("rotulo")
                            or "Pendente de decisão técnica",
                            s["Cell"],
                        ),
                        _p(
                            decision.get("justificativa")
                            or "Ainda não registrada.",
                            s["Cell"],
                        ),
                        _p(decision.get("registrada_em") or "Pendente", s["Cell"]),
                    ],
                ],
                [48 * mm, 92 * mm, 40 * mm],
            ),
            Paragraph(
                "A classificação preliminar foi produzida pela ferramenta. A "
                "decisão é humana e deve considerar documentos, exceções e as "
                "políticas da instituição.",
                s["Foot"],
            ),
        ]
    )
    return story


def _analysis_story(analysis: dict[str, object], styles, batch_document: str = ""):
    s = styles
    story = []
    if batch_document:
        story += [
            Paragraph(
                f"CPF/CNPJ da planilha: {_escape(batch_document)}", s["DocumentTitle"]
            ),
            Paragraph(
                f"Referência interna: {_escape(analysis.get('referencia_interna'))} | Linha: {_escape(analysis.get('linha_planilha'))}",
                s["Foot"],
            ),
        ]
    story += _pre_analysis_story(analysis, s)
    story.append(Paragraph("Identificação", s["Section"]))
    car_value = str(analysis.get("car") or "")
    story.append(
        _table(
            [
                [
                    _p(x, s["CellWhite"])
                    for x in (
                        "CAR selecionado",
                        "UF indicada no CAR",
                        "Origem da geometria",
                    )
                ],
                [
                    _p(car_value, s["Cell"]),
                    _p(car_value[:2].upper() if len(car_value) >= 2 else "", s["Cell"]),
                    _p(analysis.get("origem_geometria"), s["Cell"]),
                ],
            ],
            [100 * mm, 30 * mm, 50 * mm],
        )
    )
    story.append(Spacer(1, 2 * mm))
    source_mode = (
        f"Sugerida pela UF {analysis.get('fonte_recursos_uf') or 'não identificada'}; "
        "confirmar na proposta"
        if analysis.get("fonte_recursos_modo") == "sugerida_pela_uf"
        else "Escolha manual"
    )
    story.append(
        _table(
            [
                [
                    _p("Fonte de recursos", s["CellWhite"]),
                    _p("Forma de seleção", s["CellWhite"]),
                    _p("Linha de crédito informada", s["CellWhite"]),
                ],
                [
                    _p(
                        analysis.get("fundo_constitucional") or "Não informado",
                        s["Cell"],
                    ),
                    _p(source_mode, s["Cell"]),
                    _p(
                        analysis.get("programa_financiamento") or "Não informado",
                        s["Cell"],
                    ),
                ],
            ],
            [38 * mm, 62 * mm, 80 * mm],
        )
    )
    story.append(
        Paragraph(
            f"Geometria utilizada: <b>{_escape(analysis.get('origem_geometria', 'não informada'))}</b>.",
            s["BodySmall"],
        )
    )
    if analysis.get("observacao_planilha"):
        story.append(
            Paragraph(
                f"Observação da planilha: {_escape(analysis['observacao_planilha'])}",
                s["BodySmall"],
            )
        )

    story.append(
        Paragraph("Consulta ao MTE — trabalho análogo à escravidão", s["Section"])
    )
    slave_labor = analysis.get("trabalho_escravo", [])
    consulted_documents = _document_values(analysis.get("documentos_consultados_mte"))
    mte_source = analysis.get("mte_fonte") or {}
    story.append(
        Paragraph(
            f"Fonte consultada: <b>{MTE_SOURCE_NAME}</b> — {_escape(mte_source.get('fonte_url') or MTE_SOURCE_URL)}",
            s["BodySmall"],
        )
    )
    story.append(
        Paragraph(
            "CPF/CNPJ pesquisados: " + _escape(_document_summary(consulted_documents)),
            s["BodySmall"],
        )
    )
    if slave_labor:
        rows = [
            [
                _p(x, s["CellWhite"])
                for x in ("CPF/CNPJ", "Empregador", "UF", "Inclusão", "Estabelecimento")
            ]
        ]
        for item in slave_labor:
            rows.append(
                [
                    _p(item.get("documento_original"), s["Cell"]),
                    _p(item.get("empregador"), s["Cell"]),
                    _p(item.get("uf"), s["Cell"]),
                    _p(item.get("inclusao_cadastro"), s["Cell"]),
                    _p(item.get("estabelecimento"), s["Cell"]),
                ]
            )
        story.append(_table(rows, [36 * mm, 42 * mm, 12 * mm, 24 * mm, 66 * mm]))
        story.append(
            Paragraph(
                list_message(analysis.get("resultado_fontes", {}).get("mte"), "MTE"),
                s["BodySmall"],
            )
        )
    elif consulted_documents:
        story.append(
            Paragraph(
                list_message(analysis.get("resultado_fontes", {}).get("mte"), "MTE"),
                s["BodySmall"],
            )
        )
    else:
        story.append(
            Paragraph(
                "Consulta inconclusiva: nenhum CPF/CNPJ foi fornecido para a pesquisa no cadastro do MTE.",
                s["BodySmall"],
            )
        )

    story.append(Paragraph("Publicação MMA/MCR", s["Section"]))
    mma_text = _escape(
        list_message(analysis.get("resultado_fontes", {}).get("mma_mcr"), "MMA/MCR")
    )
    story += [
        Paragraph(mma_text, s["BodySmall"]),
        Paragraph("Evidências dos cruzamentos territoriais", s["Section"]),
    ]
    rows = [
        [
            _p(x, s["CellWhite"])
            for x in ("Fonte", "Resultado", "Feições", "Área (ha)", "Observação")
        ]
    ]
    for item in analysis.get("ambiental", {}).get("camadas", []):
        observation = _observation(item)
        if item.get("orientacao_revisao"):
            observation = f"{observation} {item['orientacao_revisao']}"
        rows.append(
            [
                _p(item.get("fonte"), s["Cell"]),
                _p(_label(item.get("resultado")), s["Cell"]),
                _p(item.get("quantidade", 0), s["Cell"]),
                _p(item.get("area_sobreposta_ha", 0), s["Cell"]),
                _p(observation, s["Cell"]),
            ]
        )
    story.append(_table(rows, [46 * mm, 39 * mm, 17 * mm, 22 * mm, 56 * mm]))
    map_path = Path(str(analysis.get("_mapa_path_interno", "")))
    if map_path.is_file():
        story.append(PageBreak())
        story.append(
            KeepTogether(
                [
                    Paragraph("Mapa da análise", s["Section"]),
                    Image(str(map_path), width=180 * mm, height=101.25 * mm),
                    Spacer(1, 2 * mm),
                    _map_legend(
                        s,
                        _visible_map_entries(analysis),
                        analysis.get("ambiental", {}).get("area_car_ha"),
                    ),
                    Paragraph(
                        "Imagem de satélite: Google Satellite. Limites e ocorrências: bases indicadas neste relatório."
                        if analysis.get("mapa_satelite_incluido", True)
                        else "Mapa esquemático sem imagem de satélite. Limites e ocorrências: fontes indicadas neste relatório.",
                        s["Foot"],
                    ),
                ]
            )
        )
    story.append(
        Table(
            [
                [
                    Paragraph(
                        "<b>Uso do relatório:</b> apoio à decisão técnica. A ferramenta interpreta as regras e aponta possíveis impedimentos, lacunas e providências; não aprova nem recusa a contratação automaticamente. O JSON conserva os resultados e a decisão humana em formato estruturado.",
                        s["BodySmall"],
                    )
                ]
            ],
            colWidths=[180 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PALE_YELLOW),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D2B45B")),
                    ("PADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        )
    )
    story += _database_evidence_story(analysis, s)
    return story


def _document(path: Path, title: str):
    return SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=16 * mm,
        bottomMargin=19 * mm,
        title=title,
        author="CAR Microcrédito",
    )


def _write_report_files(
    analysis: dict[str, object], output_pdf: str | Path
) -> tuple[Path, Path]:
    pdf_path = Path(output_pdf)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = pdf_path.with_suffix(".json")
    payload = _report_payload(analysis)
    payload.setdefault(
        "emitido_em", datetime.now().astimezone().isoformat(timespec="seconds")
    )
    json_path.write_text(
        json.dumps(
            _public_json_payload(payload), ensure_ascii=False, indent=2, default=str
        ),
        encoding="utf-8",
    )
    s = _styles()
    story = [
        Paragraph("Relatório de pré-análise socioambiental", s["ReportTitle"]),
        Paragraph(
            f"Apoio à decisão técnica de crédito rural | Emitido em {_escape(payload['emitido_em'])}",
            s["Foot"],
        ),
        Spacer(1, 5 * mm),
    ]
    if payload.get("demonstracao"):
        story.append(
            Paragraph(
                "EXEMPLO COM DADOS SINTÉTICOS — SEM VALIDADE OPERACIONAL",
                s["BodySmall"],
            )
        )
    elif payload.get("homologacao"):
        story.append(
            Paragraph(
                "TESTE COM CASO REAL — NÃO UTILIZAR COMO DECISÃO OPERACIONAL",
                s["BodySmall"],
            )
        )
    story += _analysis_story(payload, s)
    _document(pdf_path, "Relatório de pré-análise socioambiental").build(
        story, onFirstPage=_footer, onLaterPages=_footer
    )
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError("O relatório PDF não foi criado.")
    return pdf_path, json_path


def _write_batch_report_files(
    analyses: list[dict[str, object]],
    output_pdf: str | Path,
    failures: list[dict[str, object]] | None = None,
    summary=None,
) -> tuple[Path, Path]:
    pdf_path = Path(output_pdf)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = pdf_path.with_suffix(".json")
    emitted = datetime.now().astimezone().isoformat(timespec="seconds")
    failures = failures or []
    report_analyses = [_report_payload(item) for item in analyses]
    payload = {
        "resumo_lote": summary or {},
        "emitido_em": emitted,
        "quantidade_analises": len(report_analyses),
        "falhas": failures,
        "analises": [_public_json_payload(item) for item in report_analyses],
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    s = _styles()
    documents = sorted(
        {
            str(item.get("documento_lote") or "")
            for item in report_analyses
            if item.get("documento_lote")
        }
    )
    possible_impediments = sum(
        (item.get("pre_analise") or {}).get("classificacao_geral")
        == "possivel_impedimento"
        for item in report_analyses
    )
    story = [
        Paragraph(
            "Relatório consolidado de pré-análise socioambiental", s["ReportTitle"]
        ),
        Paragraph(
            f"Consulta em lista - usuário supremo | Emitido em {_escape(emitted)}",
            s["Foot"],
        ),
        Spacer(1, 5 * mm),
        _table(
            [
                [
                    _p(x, s["CellWhite"])
                    for x in (
                        "CPF/CNPJ",
                        "CAR analisados",
                        "Possíveis impedimentos",
                        "Não analisados",
                    )
                ],
                [
                    _p(len(documents), s["Cell"]),
                    _p(len(report_analyses), s["Cell"]),
                    _p(possible_impediments, s["Cell"]),
                    _p(len(failures), s["Cell"]),
                ],
            ],
            [45 * mm] * 4,
        ),
        Paragraph(
            "Estado do lote: " + _escape((summary or {}).get("estado", "concluido")),
            s["BodySmall"],
        ),
        Paragraph("Índice do lote", s["Section"]),
    ]
    if (summary or {}).get("demonstracao"):
        story.insert(
            1,
            Paragraph(
                "EXEMPLO COM DADOS SINTÉTICOS — SEM VALIDADE OPERACIONAL",
                s["BodySmall"],
            ),
        )
    rows = [
        [
            _p(x, s["CellWhite"])
            for x in (
                "CPF/CNPJ",
                "CAR",
                "Resumo da pré-análise",
                "Referência",
            )
        ]
    ]
    for item in report_analyses:
        rows.append(
            [
                _p(item.get("documento_lote"), s["Cell"]),
                _p(item.get("car"), s["Cell"]),
                _p(
                    (item.get("pre_analise") or {}).get(
                        "classificacao_geral_rotulo"
                    ),
                    s["Cell"],
                ),
                _p(item.get("referencia_interna"), s["Cell"]),
            ]
        )
    story.append(_table(rows, [42 * mm, 70 * mm, 42 * mm, 26 * mm]))
    if failures:
        story.append(Paragraph("Itens não analisados", s["Section"]))
        rows = [[_p(x, s["CellWhite"]) for x in ("Linha", "CPF/CNPJ", "CAR", "Motivo")]]
        for item in failures:
            rows.append(
                [
                    _p(item.get("linha"), s["Cell"]),
                    _p(item.get("documento"), s["Cell"]),
                    _p(item.get("car"), s["Cell"]),
                    _p(item.get("erro"), s["Cell"]),
                ]
            )
        story.append(_table(rows, [15 * mm, 40 * mm, 60 * mm, 65 * mm]))
    previous_document = None
    for item in report_analyses:
        document = str(item.get("documento_lote") or "")
        story.append(PageBreak())
        if document != previous_document:
            story.append(
                Paragraph(f"Grupo CPF/CNPJ {_escape(document)}", s["ReportTitle"])
            )
            previous_document = document
        story += _analysis_story(item, s, document)
    _document(pdf_path, "Relatório consolidado de pré-análise socioambiental").build(
        story, onFirstPage=_footer, onLaterPages=_footer
    )
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError("O relatório consolidado não foi criado.")
    return pdf_path, json_path


def _publish(writer, analyses, output_pdf, *args):
    requested = Path(output_pdf)
    requested.parent.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:12]
    final = requested.parent / ("analise_" + run_id)
    configured_temp = os.environ.get("CAR_MICROCREDITO_TEMP_DIR", "").strip()
    local_root = (
        Path(configured_temp)
        if configured_temp
        else Path(os.environ.get("LOCALAPPDATA") or requested.parent)
        / "Cactvs"
        / "CAR_Microcredito"
        / "temporarios"
    )
    staging = local_root / ("relatorio_" + run_id)
    try:
        # O ReportLab trabalha primeiro na pasta temporária local. Só depois os
        # arquivos prontos são copiados para o destino, evitando bloqueios e
        # sincronizações parciais do OneDrive durante a geração.
        local_root.mkdir(parents=True, exist_ok=True)
        staging.mkdir()
        analyses = copy.deepcopy(analyses)
        collection = analyses if isinstance(analyses, list) else [analyses]
        for item in collection:
            item["id_execucao"] = run_id
        if isinstance(analyses, list):
            failures, summary = args
            args = (failures, {**(summary or {}), "id_execucao": run_id})
        pdf, audit = writer(analyses, staging / "relatorio.pdf", *args)
        collection = analyses if isinstance(analyses, list) else [analyses]
        for index, item in enumerate(collection):
            # A geometria original permanece na pasta interna da execução:
            # seus atributos podem conter referências reservadas da operação.
            for field, suffix in (("mapa_path", ".png"),):
                source = item.get(field)
                if source and Path(source).is_file():
                    shutil.copy2(source, staging / f"evidencia_{index}{suffix}")
        hashes = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in staging.iterdir()
            if path.is_file()
        }
        (staging / "manifesto_arquivos.json").write_text(
            json.dumps(hashes, indent=2), encoding="utf-8"
        )
        final.mkdir()
        for source in staging.iterdir():
            if source.is_file():
                shutil.copy2(source, final / source.name)
        final_pdf, final_audit = final / pdf.name, final / audit.name
        if not final_pdf.is_file() or not final_audit.is_file():
            raise OSError("A cópia final do PDF ou do JSON não foi concluída.")
        return final_pdf, final_audit
    except PermissionError as exc:
        shutil.rmtree(final, ignore_errors=True)
        raise PermissionError(
            "O Windows bloqueou a gravação do relatório na pasta escolhida. "
            "Selecione outra pasta em ‘Pasta dos relatórios’ e tente novamente. "
            f"Detalhe: {exc}"
        ) from exc
    except Exception:
        shutil.rmtree(final, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def write_report(analysis, output_pdf):
    return _publish(_write_report_files, analysis, output_pdf)


def write_batch_report(analyses, output_pdf, failures=None, summary=None):
    return _publish(_write_batch_report_files, analyses, output_pdf, failures, summary)
