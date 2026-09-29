from __future__ import annotations

import re
import unicodedata


def only_digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_document(value: object) -> str:
    """Normaliza CPF/CNPJ sem tentar completar ou reconstruir o documento."""
    digits = only_digits(value)
    return digits if len(digits) in (11, 14) else ""


def mask_document(value: object) -> str:
    """Exibe só os dois dígitos finais de um CPF/CNPJ válido."""
    digits = normalize_document(value)
    if len(digits) == 11:
        return f"***.***.***-{digits[-2:]}"
    if len(digits) == 14:
        return f"**.***.***/****-{digits[-2:]}"
    return "Documento indisponível"


def is_masked_document(value: object) -> bool:
    text = str(value or "")
    return bool(text) and any(marker in text for marker in ("*", "X", "x"))


def normalize_car(value: object) -> str:
    """Gera uma chave de comparação e mantém a validação formal para outra etapa."""
    text = str(value or "").strip().upper()
    if text in {"", "-1", "0", "N/A", "NA", "NULL", "NONE"}:
        return ""
    return re.sub(r"[^A-Z0-9]", "", text)


def normalize_header(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")
