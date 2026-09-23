"""Delimiter/encoding detection and header-normalized CSV iteration."""

from __future__ import annotations

import csv
import gzip
from collections.abc import Iterator
from pathlib import Path
from typing import IO, cast

from qgis_plugin_microcredito.domain.normalize import normalize_header


def open_text(path: Path, encoding: str) -> IO[str]:
    if path.suffix.lower() == ".gz":
        return cast(
            IO[str],
            gzip.open(path, "rt", encoding=encoding, newline="", errors="strict"),
        )
    return path.open("r", encoding=encoding, newline="", errors="strict")


def read_sample(path: Path, encoding: str, size: int = 65536) -> str:
    with open_text(path, encoding) as stream:
        return stream.read(size)


def detect_format(path: Path) -> tuple[str, csv.Dialect]:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            sample = read_sample(path, encoding)
            dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t,")
            return encoding, cast(csv.Dialect, dialect)
        except (UnicodeError, csv.Error) as exc:
            last_error = exc
    raise ValueError(f"Não foi possível detectar formato de {path}: {last_error}")


def iter_rows(path: Path) -> Iterator[dict[str, str]]:
    encoding, dialect = detect_format(path)
    with open_text(path, encoding) as stream:
        reader = csv.DictReader(stream, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError(f"Arquivo sem cabeçalho: {path}")
        for row in reader:
            yield {
                normalize_header(key): (value or "").strip()
                for key, value in row.items()
                if key
            }


def value_from_aliases(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        found = row.get(alias, "")
        if found:
            return found
    return ""
