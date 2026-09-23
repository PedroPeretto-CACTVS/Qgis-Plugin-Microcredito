from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from qgis_plugin_microcredito.domain.normalize import normalize_car, normalize_document

MAIN_HEADERS = (
    "CPF_CNPJ",
    "CAR",
    "PROPRIETARIO_POSSUIDOR",
    "REFERENCIA_INTERNA",
    "OBSERVACAO",
)


@dataclass(frozen=True)
class BatchRow:
    source_row: int
    document: str
    car: str = ""
    owner_document: str = ""
    internal_reference: str = ""
    observation: str = ""


def _column_number(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    number = 0
    for char in letters.group(0) if letters else "A":
        number = number * 26 + ord(char) - 64
    return number - 1


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_namespace = {
        "r": "http://schemas.openxmlformats.org/package/2006/relationships"
    }
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheet = next(
        (
            item
            for item in workbook.findall("m:sheets/m:sheet", namespace)
            if item.attrib.get("name") == "Consultas"
        ),
        None,
    )
    if sheet is None:
        raise ValueError("A planilha deve conter a aba Consultas.")
    relationship_id = sheet.attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    )
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = None
    for relationship in relationships.findall("r:Relationship", rel_namespace):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib.get("Target")
            break
    if not target:
        raise ValueError("Não foi possível localizar a primeira aba da planilha.")
    target = target.replace("\\", "/").lstrip("/")
    return target if target.startswith("xl/") else f"xl/{target}"


def _cell_value(cell, shared_strings: list[str], namespace: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(
            node.text or "" for node in cell.findall(".//m:t", namespace)
        ).strip()
    value_node = cell.find("m:v", namespace)
    if value_node is None or value_node.text is None:
        return ""
    value = value_node.text
    if cell_type == "s":
        try:
            return shared_strings[int(value)].strip()
        except (ValueError, IndexError):
            return ""
    return value.strip()


def read_xlsx_rows(path: str | Path, *, numbered=False) -> list:
    source = Path(path)
    if source.suffix.lower() != ".xlsx":
        raise ValueError("Selecione uma planilha no formato .xlsx.")
    if not source.is_file():
        raise ValueError("A planilha selecionada não existe.")
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with zipfile.ZipFile(source) as archive:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(
                        node.text or "" for node in item.findall(".//m:t", namespace)
                    )
                    for item in root.findall("m:si", namespace)
                ]
            sheet = ET.fromstring(archive.read(_first_sheet_path(archive)))
            rows: list[list[str]] = []
            for row in sheet.findall(".//m:sheetData/m:row", namespace):
                values: dict[int, str] = {}
                for cell in row.findall("m:c", namespace):
                    values[_column_number(cell.attrib.get("r", "A1"))] = _cell_value(
                        cell, shared_strings, namespace
                    )
                if values:
                    data = [values.get(index, "") for index in range(max(values) + 1)]
                    rows.append((int(row.attrib["r"]), data) if numbered else data)
            return rows
    except zipfile.BadZipFile as exc:
        raise ValueError("O arquivo não é uma planilha XLSX válida.") from exc


def read_batch_xlsx(path: str | Path) -> list[BatchRow]:
    rows = read_xlsx_rows(path, numbered=True)
    if not rows:
        raise ValueError("A planilha está vazia.")
    headers = [str(value).strip().upper() for value in rows[0][1]]
    if len(headers) != len(set(headers)):
        raise ValueError("Cabeçalhos duplicados na aba Consultas.")
    missing = [header for header in MAIN_HEADERS if header not in headers]
    if missing:
        raise ValueError("Colunas ausentes na aba Consultas: " + ", ".join(missing))
    positions = {header: headers.index(header) for header in MAIN_HEADERS}

    def value(row: list[str], header: str) -> str:
        index = positions[header]
        return str(row[index]).strip() if index < len(row) else ""

    parsed: list[BatchRow] = []
    errors: list[str] = []
    for source_row, row in rows[1:]:
        if not any(str(item).strip() for item in row):
            continue
        raw_document = value(row, "CPF_CNPJ")
        raw_owner = value(row, "PROPRIETARIO_POSSUIDOR")
        if any(re.search(r"[eE][+-]?\d", raw) for raw in (raw_document, raw_owner)):
            errors.append(
                f"linha {source_row}: documento em notação científica; informe como texto"
            )
        document = normalize_document(raw_document)
        owner = normalize_document(raw_owner)
        if len(document) not in (11, 14):
            errors.append(f"linha {source_row}: CPF/CNPJ deve ter 11 ou 14 dígitos")
        if raw_owner and len(owner) not in (11, 14):
            errors.append(f"linha {source_row}: proprietário/possuidor inválido")
        raw_car = value(row, "CAR")
        if raw_car and not normalize_car(raw_car):
            errors.append(f"linha {source_row}: CAR ausente ou inválido")
        parsed.append(
            BatchRow(
                source_row=source_row,
                document=document,
                car=value(row, "CAR"),
                owner_document=owner,
                internal_reference=value(row, "REFERENCIA_INTERNA"),
                observation=value(row, "OBSERVACAO"),
            )
        )
    if errors:
        suffix = (
            "" if len(errors) <= 12 else f"\n... e mais {len(errors) - 12} erro(s)."
        )
        raise ValueError(
            "Corrija a planilha antes de processar:\n" + "\n".join(errors[:12]) + suffix
        )
    if not parsed:
        raise ValueError("Nenhuma consulta foi preenchida na aba Consultas.")
    return parsed
