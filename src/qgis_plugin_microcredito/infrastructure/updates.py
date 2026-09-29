"""Atualização local a partir de um catálogo central assinado.

O cliente nunca envia CPF/CNPJ, CAR, geometrias ou resultados ao publicador.
Ele baixa apenas o catálogo e os pacotes de dados já publicados, valida a
assinatura e promove a nova base localmente depois de preparar uma cópia.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from database.schema import initialize
from database.session import connect
from qgis_plugin_microcredito.application.backup_service import snapshot_database
from qgis_plugin_microcredito.application.import_service import import_file
from qgis_plugin_microcredito.application.mte_service import import_mte
from qgis_plugin_microcredito.domain.base_catalog import (
    BASE_DEFINITIONS,
    LocalBaseInventory,
    build_local_inventory,
    definition_for,
    display_label,
)
from qgis_plugin_microcredito.infrastructure.downloads import validate_geopackage

CATALOG_SCHEMA_VERSION = 2
SUPPORTED_CATALOG_SCHEMA_VERSIONS = frozenset((1, CATALOG_SCHEMA_VERSION))
PACKAGE_STRATEGIES = frozenset(
    ("replace_file", "import_mma_mcr", "import_mte", "import_sicor")
)
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_SIGNATURE_BYTES = 16 * 1024
# O maior pacote atual é o conjunto Sicor. Os limites impedem catálogo malformado
# ou ZIP-bomb, sem inviabilizar uma publicação nacional compactada.
MAX_PACKAGE_BYTES = 50 * 1024 * 1024 * 1024
MAX_EXTRACTED_PACKAGE_BYTES = 60 * 1024 * 1024 * 1024
UPDATE_DIRECTORY = ".atualizacoes"
LOCK_FILENAME = "atualizacao-em-andamento.lock"
# O SQLite no Windows ainda encontra instalações sem suporte pleno a caminhos
# longos. Esta pasta é exclusivamente transitória e curta de propósito; o
# estado auditável e os pontos de reversão permanecem em .atualizacoes.
STAGING_DIRECTORY = ".u"
DOWNLOAD_DIRECTORY = ".d"
HISTORY_DIRECTORY = ".h"
RESTORE_METADATA_FILENAME = "restore.json"
RESTORE_SCHEMA_VERSION = 1

# Chave usada exclusivamente pelos vetores de teste automatizado abaixo. Não é
# selecionada pela interface e a chave privada correspondente não é utilizada
# na homologação.
TEST_PUBLISHER_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA3ofSGIW4hK09CjeNi2eh/xxzB/81uZda
GpLAmYr3XdaX15IQ1mowLOP1Tj4O3KSeo4GGWof1ImMT75TDgWJkKNxg9mKjh43iLYDeBbvGSPMv
VuCjEoLLXRDRRGT7fu4NtEkdqMDHk6hSl2XzNXIwHh5kztuvQSN4RnGFwUdSscQAK9QVSAJTwr6f
1JbQkcMICEKpsJ14jKNyXQuHAzTzI6yOmSWTT/iSCajY3Duur4IIfJA/5zDS9wd0yM5Od1l1AbNy
asonHsCzKkoW/JUrQ4wpMMgB3rE0SoBqUE/nzv0XjG+m5f7/DjFmWV6fAY0PyutWB0vDaafXIRA6
Ss4+9QIDAQAB
-----END PUBLIC KEY-----
"""

# Chave pública da homologação privada. A chave privada correspondente fica
# fora do repositório, fora do OneDrive e fora do pacote instalado no QGIS.
HOMOLOGATION_PUBLISHER_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAxSo0Rvzjqdt/wmyV311V
YpGcpvLAOA8wqTxImhoqKaRdwhrRsaq6PALnOgCo0mqbQB3ufj2t1pJ3zr7vtOLx
z4mrE8DAFUqB/lK2XKAjAUCNNxRQWK7xrlVSSYe2HD3yKKXlajX5eyCT8Zh8jg8y
4beMGU6lR7NrOaz9Uc367QKz1ZXQL8myxsfFnQmuTxh77UVFOGV7wTK+baTxIRJx
p3s792qKORG4FuTtD2PwJ9BMkrX0/2IQn+MlDUM5vLAYd1A8tiW3foQLml+2pa4J
pAlFCFgRE1jOR/bcd8Bv5hQkoXiBn9Vf+mtia8tuqgLruSIEijnIzQYEEieMyc/w
NeJMSQHjK6AimZVS0fz710tDRVzaHeNwVs1zR2XWu+GMXIAFW5T+3og/4gc6cWIe
RJcwyueSvyakD+dFpA5kICJZla420jh5h7ydl7SmAtXxE3FMIuvBUTf7wzwzdGDd
YxBTC8/Zb45Um2T9eCq93cVGa/4Vu7uKMTQyLtxUGkqlAgMBAAE=
-----END PUBLIC KEY-----
"""

# A chave privada correspondente nunca integra o plugin. A publicação de
# produção pode rotacionar esta chave pública em uma versão futura do código.
PUBLISHER_PUBLIC_KEY_PEM = HOMOLOGATION_PUBLISHER_PUBLIC_KEY_PEM


class UpdateError(ValueError):
    """Falha segura de catálogo, download, validação ou promoção."""


@dataclass(frozen=True)
class CatalogPackage:
    identifier: str
    label: str
    version: str
    strategy: str
    url: str
    sha256: str
    size_bytes: int
    target: str | None = None
    validity_until: str | None = None
    scope: str | None = None
    provides: tuple[str, ...] = ()
    source_date: str | None = None
    source_reference: str | None = None
    foreign_feature_count: int = 0


@dataclass(frozen=True)
class Catalog:
    issued_at: str
    expires_at: str
    packages: tuple[CatalogPackage, ...]
    schema_version: int = 1
    channel: str = "homologacao"
    prepared_by: str | None = None
    change_reference: str | None = None


@dataclass(frozen=True)
class UpdateStatus:
    identifier: str
    label: str
    installed_version: str | None
    available_version: str | None
    state: str
    detail: str
    regulatory_basis: str = ""
    coverage: str = ""
    source_date: str = ""


@dataclass(frozen=True)
class RestorePoint:
    """Ponto local validado que pode recompor o estado anterior à última operação."""

    restore_id: str
    identifier: str
    label: str
    created_at: str
    restore_version: str | None
    replaced_version: str | None
    kind: str
    legacy: bool = False


def _parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise UpdateError(f"{field} ausente no catálogo.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpdateError(f"{field} inválido no catálogo.") from exc
    if parsed.tzinfo is None:
        raise UpdateError(f"{field} deve informar fuso horário.")
    return parsed.astimezone(UTC)


def _safe_identifier(value: object, field: str = "identificador") -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value
    ):
        raise UpdateError(f"{field} inválido no catálogo.")
    return value


def _safe_relative_path(value: object, field: str = "caminho") -> str:
    if not isinstance(value, str) or not value:
        raise UpdateError(f"{field} ausente no catálogo.")
    candidate = PurePosixPath(value.replace("\\", "/"))
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in ("", ".") for part in candidate.parts)
    ):
        raise UpdateError(f"{field} fora da pasta de dados.")
    return candidate.as_posix()


def _safe_target(root: Path, relative: str) -> Path:
    target = (root / Path(*PurePosixPath(relative).parts)).resolve()
    if target != root and root not in target.parents:
        raise UpdateError("Destino da atualização fora da pasta de dados.")
    return target


def _catalog_text(value: object, field: str, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise UpdateError(f"{field} inválido no catálogo.")
    return value.strip()


def _iso_date(value: object, field: str) -> str:
    text = _catalog_text(value, field, 10)
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise UpdateError(f"{field} deve usar AAAA-MM-DD.") from exc
    return text


def _expected_replace_target(identifier: str) -> str | None:
    definition = definition_for(identifier)
    return definition.relative_path if definition is not None else None


def _decode_pem(pem: str, label: str) -> bytes:
    pattern = rf"-----BEGIN {re.escape(label)}-----\s*(.*?)\s*-----END {re.escape(label)}-----"
    match = re.fullmatch(pattern, pem.strip(), flags=re.DOTALL)
    if not match:
        raise UpdateError("Chave pública do publicador inválida.")
    try:
        return base64.b64decode(re.sub(r"\s+", "", match.group(1)), validate=True)
    except ValueError as exc:
        raise UpdateError("Chave pública do publicador inválida.") from exc


def _read_der_length(data: bytes, index: int) -> tuple[int, int]:
    if index >= len(data):
        raise UpdateError("Chave pública DER truncada.")
    first = data[index]
    if first < 0x80:
        return first, index + 1
    count = first & 0x7F
    if count == 0 or count > 4 or index + 1 + count > len(data):
        raise UpdateError("Comprimento DER inválido.")
    return int.from_bytes(data[index + 1 : index + 1 + count], "big"), index + 1 + count


def _read_der_value(data: bytes, index: int, tag: int) -> tuple[bytes, int]:
    if index >= len(data) or data[index] != tag:
        raise UpdateError("Estrutura da chave pública inválida.")
    length, start = _read_der_length(data, index + 1)
    end = start + length
    if end > len(data):
        raise UpdateError("Chave pública DER truncada.")
    return data[start:end], end


def _rsa_public_numbers(public_key_pem: str) -> tuple[int, int]:
    """Lê SubjectPublicKeyInfo RSA; o cliente somente verifica assinaturas."""
    der = _decode_pem(public_key_pem, "PUBLIC KEY")
    outer, end = _read_der_value(der, 0, 0x30)
    if end != len(der):
        raise UpdateError("Chave pública com dados adicionais.")
    algorithm, index = _read_der_value(outer, 0, 0x30)
    bit_string, end = _read_der_value(outer, index, 0x03)
    if end != len(outer) or not algorithm or len(bit_string) < 2 or bit_string[0] != 0:
        raise UpdateError("Chave pública RSA inválida.")
    rsa_sequence, end = _read_der_value(bit_string[1:], 0, 0x30)
    if end != len(bit_string) - 1:
        raise UpdateError("Chave pública RSA inválida.")
    modulus_bytes, index = _read_der_value(rsa_sequence, 0, 0x02)
    exponent_bytes, end = _read_der_value(rsa_sequence, index, 0x02)
    if end != len(rsa_sequence):
        raise UpdateError("Chave pública RSA inválida.")
    modulus = int.from_bytes(modulus_bytes, "big")
    exponent = int.from_bytes(exponent_bytes, "big")
    if modulus.bit_length() < 2048 or exponent < 3 or not exponent % 2:
        raise UpdateError("A chave do publicador não atende ao mínimo de segurança.")
    return modulus, exponent


def verify_catalog_signature(
    payload: bytes, signature: bytes, public_key_pem: str
) -> None:
    """Verifica RSA PKCS#1 v1.5 com SHA-256 sem carregar uma chave privada."""
    modulus, exponent = _rsa_public_numbers(public_key_pem)
    width = (modulus.bit_length() + 7) // 8
    if len(signature) != width or int.from_bytes(signature, "big") >= modulus:
        raise UpdateError("Assinatura do catálogo inválida.")
    digest_info = (
        bytes.fromhex("3031300d060960864801650304020105000420")
        + hashlib.sha256(payload).digest()
    )
    padding_size = width - len(digest_info) - 3
    if padding_size < 8:
        raise UpdateError("Chave pública inválida para SHA-256.")
    expected = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
    actual = pow(int.from_bytes(signature, "big"), exponent, modulus).to_bytes(
        width, "big"
    )
    if not hmac.compare_digest(actual, expected):
        raise UpdateError("Assinatura do catálogo inválida.")


def _parse_catalog(payload: bytes) -> Catalog:
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Catálogo não é JSON UTF-8 válido.") from exc
    schema_version = (
        document.get("schema_version") if isinstance(document, dict) else None
    )
    if schema_version not in SUPPORTED_CATALOG_SCHEMA_VERSIONS:
        raise UpdateError("Versão de catálogo incompatível.")
    channel: str = "homologacao"
    prepared_by = None
    change_reference = None
    if schema_version == 2:
        publication = document.get("publication")
        if not isinstance(publication, dict):
            raise UpdateError("Catálogo de produção sem identificação da publicação.")
        raw_channel = publication.get("channel")
        if not isinstance(raw_channel, str) or raw_channel not in (
            "homologacao",
            "producao",
        ):
            raise UpdateError("Canal de publicação inválido no catálogo.")
        channel = raw_channel
        prepared_by = _catalog_text(
            publication.get("prepared_by"), "Responsável pela preparação", 160
        )
        change_reference = _catalog_text(
            publication.get("change_reference"), "Referência de mudança", 160
        )
    issued_at = _parse_timestamp(document.get("issued_at"), "issued_at")
    expires_at = _parse_timestamp(document.get("expires_at"), "expires_at")
    now = datetime.now(UTC)
    if issued_at > now:
        raise UpdateError("Catálogo emitido no futuro.")
    if expires_at <= now or expires_at <= issued_at:
        raise UpdateError("Catálogo expirado ou com validade inválida.")
    raw_packages = document.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        raise UpdateError("Catálogo sem pacotes de dados.")
    packages = []
    seen = set()
    for raw in raw_packages:
        if not isinstance(raw, dict):
            raise UpdateError("Pacote inválido no catálogo.")
        identifier = _safe_identifier(raw.get("id"), "id do pacote")
        if identifier in seen:
            raise UpdateError("Catálogo contém pacote duplicado.")
        seen.add(identifier)
        label = raw.get("label")
        version = raw.get("version")
        strategy = raw.get("strategy")
        url = raw.get("url")
        digest = raw.get("sha256")
        size = raw.get("size_bytes")
        if not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise UpdateError("Rótulo de pacote inválido.")
        version_text = _safe_identifier(version, "versão do pacote")
        if not isinstance(strategy, str) or strategy not in PACKAGE_STRATEGIES:
            raise UpdateError("Estratégia de pacote não permitida.")
        strategy_text = strategy
        parsed_url = urllib.parse.urlparse(str(url or ""))
        if parsed_url.scheme != "https" or not parsed_url.hostname:
            raise UpdateError("URL do pacote deve usar HTTPS.")
        if not isinstance(digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", digest.lower()
        ):
            raise UpdateError("SHA-256 do pacote inválido.")
        if not isinstance(size, int) or size <= 0 or size > MAX_PACKAGE_BYTES:
            raise UpdateError("Tamanho do pacote inválido.")
        target = raw.get("target")
        if strategy_text == "replace_file":
            target = _safe_relative_path(target, "destino do pacote")
        elif target is not None:
            raise UpdateError("Somente pacotes de arquivo podem definir destino.")
        validity = raw.get("validity_until")
        if strategy_text in ("import_mma_mcr", "import_mte"):
            _parse_timestamp(str(validity or "") + "T00:00:00+00:00", "validity_until")
        elif validity is not None:
            raise UpdateError("Validade inesperada no pacote.")
        scope = raw.get("scope")
        scope_text: str | None = None
        if strategy_text == "import_sicor":
            if not isinstance(scope, str) or not re.fullmatch(
                r"[A-Za-z0-9_.:-]{3,100}", scope
            ):
                raise UpdateError("Escopo Sicor inválido.")
            scope_text = scope
        elif scope is not None:
            raise UpdateError("Escopo inesperado no pacote.")
        provides: tuple[str, ...] = (identifier,)
        source_date = None
        source_reference = None
        if schema_version == 2:
            raw_provides = raw.get("provides")
            if not isinstance(raw_provides, list) or not raw_provides:
                raise UpdateError("Pacote sem lista de bases atendidas.")
            provides = tuple(
                _safe_identifier(item, "base atendida") for item in raw_provides
            )
            if len(set(provides)) != len(provides) or identifier not in provides:
                raise UpdateError("Lista de bases atendidas inválida.")
            source_date = _iso_date(raw.get("source_date"), "source_date")
            source_reference = _catalog_text(
                raw.get("source_reference"), "source_reference", 500
            )
            unknown = [item for item in provides if definition_for(item) is None]
            if unknown:
                raise UpdateError(f"Base atendida não reconhecida: {unknown[0]}.")
            expected_provides = {
                "import_mma_mcr": {"mma_mcr"},
                "import_mte": {"mte"},
                "import_sicor": {"sicor_operacoes_car", "sicor_geometrias"},
            }.get(strategy_text)
            if expected_provides is not None and set(provides) != expected_provides:
                raise UpdateError("Estratégia e bases atendidas são incompatíveis.")
            if strategy_text == "replace_file":
                if len(provides) != 1:
                    raise UpdateError(
                        "Pacote de arquivo deve atender exatamente uma base."
                    )
                expected_target = _expected_replace_target(identifier)
                if expected_target is None or target != expected_target:
                    raise UpdateError("Destino não corresponde à base declarada.")
            foreign_feature_count = raw.get("foreign_feature_count", 0)
            if (
                not isinstance(foreign_feature_count, int)
                or isinstance(foreign_feature_count, bool)
                or foreign_feature_count < 0
                or foreign_feature_count > 1000
            ):
                raise UpdateError("Contagem de feições de outra UF inválida.")
            if foreign_feature_count and not identifier.startswith("sicar_imoveis_"):
                raise UpdateError(
                    "Exceção de UF só é permitida para pacote estadual do SICAR."
                )
        else:
            foreign_feature_count = 0
        packages.append(
            CatalogPackage(
                identifier,
                label.strip(),
                version_text,
                strategy_text,
                str(url),
                digest.lower(),
                size,
                target,
                str(validity) if validity else None,
                scope_text,
                provides,
                source_date,
                source_reference,
                foreign_feature_count,
            )
        )
    return Catalog(
        issued_at.isoformat(),
        expires_at.isoformat(),
        tuple(packages),
        schema_version,
        channel,
        prepared_by,
        change_reference,
    )


def _limited_read(response: Any, maximum: int) -> bytes:
    chunks, total = [], 0
    while True:
        block = response.read(min(1024 * 1024, maximum - total + 1))
        if not block:
            break
        total += len(block)
        if total > maximum:
            raise UpdateError("Download maior que o limite declarado.")
        chunks.append(block)
    return b"".join(chunks)


def _companion_signature_url(catalog_url: str) -> str:
    parsed = urllib.parse.urlsplit(catalog_url)
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path + ".sig",
            parsed.query,
            parsed.fragment,
        )
    )


class _SecureHttpsRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Mantém HTTPS e impede que o token GitHub siga para outro host."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        fp: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(
            request, fp, code, message, headers, new_url
        )
        if redirected is None:
            return None
        old = urllib.parse.urlparse(request.full_url)
        new = urllib.parse.urlparse(new_url)
        if new.scheme != "https" or not new.hostname:
            raise UpdateError("Redirecionamento para URL insegura recusado.")
        if (old.hostname or "").lower() != (new.hostname or "").lower():
            redirected.remove_header("Authorization")
        return redirected


class CatalogClient:
    """Cliente de rede sem qualquer dado de consulta no cabeçalho ou URL."""

    def __init__(
        self,
        catalog_url: str,
        public_key_pem: str,
        *,
        timeout: int = 30,
        fetcher: Callable[[str, int], bytes] | None = None,
        bearer_token: str | None = None,
    ):
        parsed = urllib.parse.urlparse(catalog_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise UpdateError("O catálogo do publicador deve usar HTTPS.")
        if bearer_token and parsed.hostname.lower() != "api.github.com":
            raise UpdateError(
                "A credencial do GitHub só pode ser enviada para api.github.com."
            )
        self.catalog_url = catalog_url
        self.public_key_pem = public_key_pem
        self.timeout = timeout
        self.fetcher = fetcher
        self._bearer_token = bearer_token

    def fetch_bytes(self, url: str, maximum: int) -> bytes:
        if self.fetcher:
            data = self.fetcher(url, maximum)
            if not isinstance(data, bytes):
                raise UpdateError("Resposta do catálogo inválida.")
            if len(data) > maximum:
                raise UpdateError("Resposta maior que o limite declarado.")
            return data
        try:
            with self._open_https(url) as response:
                return _limited_read(response, maximum)
        except UpdateError:
            raise
        except OSError as exc:
            raise UpdateError(
                "Não foi possível baixar a atualização. A base local foi preservada."
            ) from exc

    def _open_https(self, url: str, extra_headers: dict[str, str] | None = None) -> Any:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise UpdateError("A atualização recusou URL sem HTTPS.")
        headers = {"User-Agent": "CAR-Microcredito/0.9"}
        if parsed.hostname.lower() == "api.github.com":
            if self._bearer_token:
                headers["Authorization"] = f"Bearer {self._bearer_token}"
            if "/contents/" in parsed.path:
                headers["Accept"] = "application/vnd.github.raw+json"
            elif "/releases/assets/" in parsed.path:
                headers["Accept"] = "application/octet-stream"
            else:
                headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        if extra_headers:
            headers.update(extra_headers)
        request = urllib.request.Request(url, headers=headers)
        response = urllib.request.build_opener(_SecureHttpsRedirectHandler()).open(
            request, timeout=self.timeout
        )
        final_url = urllib.parse.urlparse(response.geturl())
        if final_url.scheme != "https" or not final_url.hostname:
            response.close()
            raise UpdateError("Redirecionamento para URL insegura recusado.")
        return response

    def download_package(
        self,
        url: str,
        destination: Path,
        expected_size: int,
        expected_sha256: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Baixa em fluxo e retoma um arquivo parcial quando o servidor aceita Range."""
        response: Any = None
        chunks: Iterable[bytes]
        discard_on_error = False
        destination.parent.mkdir(parents=True, exist_ok=True)

        def discard_partial() -> None:
            destination.unlink(missing_ok=True)

        try:
            if self.fetcher:
                discard_partial()
                chunks = (self.fetch_bytes(url, expected_size),)
                total = 0
                digest = hashlib.sha256()
                mode = "xb"
            else:
                existing = destination.stat().st_size if destination.is_file() else 0
                if existing > expected_size:
                    discard_partial()
                    existing = 0
                digest = hashlib.sha256()
                if existing:
                    with destination.open("rb") as partial:
                        for block in iter(lambda: partial.read(1024 * 1024), b""):
                            digest.update(block)
                    if existing == expected_size:
                        if hmac.compare_digest(digest.hexdigest(), expected_sha256):
                            if progress is not None:
                                progress(existing, expected_size)
                            return
                        discard_partial()
                        existing = 0
                        digest = hashlib.sha256()
                response = self._open_https(
                    url, {"Range": f"bytes={existing}-"} if existing else None
                )
                status = getattr(response, "status", None)
                if status is None and hasattr(response, "getcode"):
                    status = response.getcode()
                if existing and status != 206:
                    response.close()
                    response = self._open_https(url)
                    discard_partial()
                    existing = 0
                    digest = hashlib.sha256()
                    status = getattr(response, "status", None)
                    if status is None and hasattr(response, "getcode"):
                        status = response.getcode()
                if existing:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {existing}-"):
                        discard_on_error = True
                        raise UpdateError(
                            "O servidor retornou uma faixa incompatível com o download parcial."
                        )
                declared_size = response.headers.get("Content-Length")
                expected_response_size = expected_size - existing
                if declared_size and (
                    not declared_size.isdigit()
                    or int(declared_size) != expected_response_size
                ):
                    discard_on_error = True
                    raise UpdateError(
                        "Tamanho informado pelo servidor diverge do catálogo assinado."
                    )
                chunks = iter(lambda: response.read(1024 * 1024), b"")
                total = existing
                mode = "ab" if existing else "xb"
                if progress is not None and existing:
                    progress(existing, expected_size)
            with destination.open(mode) as stream:
                for block in chunks:
                    total += len(block)
                    if total > expected_size:
                        discard_on_error = True
                        raise UpdateError("Download maior que o tamanho assinado.")
                    digest.update(block)
                    stream.write(block)
                    if progress is not None:
                        progress(total, expected_size)
            if total < expected_size:
                raise UpdateError(
                    "O download foi interrompido antes do fim. A parte recebida foi preservada para retomada."
                )
            if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
                discard_on_error = True
                raise UpdateError(
                    "Checksum ou tamanho do pacote divergente. A base local foi preservada."
                )
        except UpdateError:
            if discard_on_error:
                discard_partial()
            raise
        except OSError as exc:
            raise UpdateError(
                "Não foi possível concluir o download. A base local foi preservada e a parte válida poderá ser retomada."
            ) from exc
        finally:
            if response is not None:
                response.close()

    def fetch_catalog(self) -> Catalog:
        payload = self.fetch_bytes(self.catalog_url, MAX_CATALOG_BYTES)
        signature = self.fetch_bytes(
            _companion_signature_url(self.catalog_url), MAX_SIGNATURE_BYTES
        )
        verify_catalog_signature(payload, signature, self.public_key_pem)
        return _parse_catalog(payload)


def _registry_path(data_root: Path) -> Path:
    return data_root / UPDATE_DIRECTORY / "estado.json"


def _load_registry(data_root: Path) -> dict[str, dict[str, str]]:
    path = _registry_path(data_root)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    packages = payload.get("packages") if isinstance(payload, dict) else None
    if not isinstance(packages, dict):
        return {}
    return {
        key: value
        for key, value in packages.items()
        if isinstance(key, str)
        and isinstance(value, dict)
        and isinstance(value.get("version"), str)
    }


def _write_registry(data_root: Path, packages: dict[str, dict[str, str]]) -> None:
    target = _registry_path(data_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    payload = {"schema_version": 1, "packages": packages}
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _history_key(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]


def _create_history_directory(data_root: Path, identifier: str) -> Path:
    package_key = _history_key(identifier)
    stamp = datetime.now(UTC).strftime("%y%m%d%H%M%S%f")[:16]
    destination = data_root / HISTORY_DIRECTORY / package_key / stamp
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def _valid_registry_snapshot(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise UpdateError("O ponto de restauração não possui estado de versões válido.")
    result: dict[str, dict[str, str]] = {}
    for key, entry in value.items():
        _safe_identifier(key, "id do registro de versão")
        if not isinstance(entry, dict) or not isinstance(entry.get("version"), str):
            raise UpdateError(
                "O ponto de restauração contém registro de versão inválido."
            )
        result[key] = {
            name: str(field)
            for name, field in entry.items()
            if isinstance(name, str) and isinstance(field, str)
        }
    return result


def _write_restore_metadata(
    history: Path,
    *,
    identifier: str,
    label: str,
    strategy: str,
    kind: str,
    backup_file: str | None,
    target: str | None,
    target_existed: bool,
    registry_snapshot: dict[str, dict[str, str]],
    restore_version: str | None,
    replaced_version: str | None,
) -> None:
    if kind not in ("database", "file"):
        raise UpdateError("Tipo de ponto de restauração inválido.")
    payload = {
        "schema_version": RESTORE_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "package": {
            "id": _safe_identifier(identifier, "id do ponto de restauração"),
            "label": label,
            "strategy": strategy,
            "target": target,
        },
        "kind": kind,
        "backup_file": backup_file,
        "target_existed": bool(target_existed),
        "registry_snapshot": registry_snapshot,
        "restore_version": restore_version,
        "replaced_version": replaced_version,
    }
    temporary = history / (RESTORE_METADATA_FILENAME + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, history / RESTORE_METADATA_FILENAME)


def _history_path(data_root: Path, restore_id: str) -> Path:
    relative = _safe_relative_path(restore_id, "id do ponto de restauração")
    history_root = (data_root / HISTORY_DIRECTORY).resolve()
    candidate = (history_root / Path(*PurePosixPath(relative).parts)).resolve()
    if history_root not in candidate.parents:
        raise UpdateError("Ponto de restauração fora do histórico local.")
    return candidate


def _database_versions(database: Path) -> dict[str, str]:
    if not database.is_file():
        return {}
    try:
        connection = connect(database, readonly=True)
    except (OSError, sqlite3.Error, ValueError):
        return {}
    try:
        versions = {}
        for row in connection.execute(
            "SELECT tipo, sha256, importado_em FROM importacao WHERE ativo=1"
        ):
            versions[str(row["tipo"])] = (
                f"{row['importado_em']} ({str(row['sha256'])[:12]})"
            )
        row = connection.execute(
            "SELECT sha256, importado_em FROM mte_publicacao ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            versions["mte"] = f"{row['importado_em']} ({str(row['sha256'])[:12]})"
        return versions
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def local_versions(data_root: str | Path, database: str | Path) -> dict[str, str]:
    root, db = Path(data_root).resolve(), Path(database).resolve()
    versions = _database_versions(db)
    for identifier, value in _load_registry(root).items():
        versions[identifier] = str(value["version"])
    return versions


def _point_from_metadata(data_root: Path, history: Path) -> RestorePoint | None:
    metadata_path = history / RESTORE_METADATA_FILENAME
    if not metadata_path.is_file():
        return None
    try:
        document = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != RESTORE_SCHEMA_VERSION
        ):
            return None
        package = document.get("package")
        if not isinstance(package, dict):
            return None
        identifier = _safe_identifier(package.get("id"), "id do ponto de restauração")
        label = package.get("label")
        created_at = document.get("created_at")
        kind = document.get("kind")
        if (
            not isinstance(label, str)
            or not label.strip()
            or kind not in ("database", "file")
        ):
            return None
        if not isinstance(created_at, str):
            return None
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        backup_file = document.get("backup_file")
        target_existed = document.get("target_existed") is True
        if target_existed:
            relative_backup = _safe_relative_path(backup_file, "arquivo de restauração")
            if not (history / Path(*PurePosixPath(relative_backup).parts)).is_file():
                return None
        _valid_registry_snapshot(document.get("registry_snapshot"))
        restore_version = document.get("restore_version")
        replaced_version = document.get("replaced_version")
        if restore_version is not None and not isinstance(restore_version, str):
            return None
        if replaced_version is not None and not isinstance(replaced_version, str):
            return None
        restore_id = history.relative_to(data_root / HISTORY_DIRECTORY).as_posix()
        return RestorePoint(
            restore_id,
            identifier,
            label.strip(),
            created_at,
            restore_version,
            replaced_version,
            kind,
            False,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, UpdateError):
        return None


def _legacy_database_point(
    data_root: Path,
    database: Path,
    history: Path,
    identifiers_by_key: dict[str, str],
    current: dict[str, str],
) -> RestorePoint | None:
    """Reconhece o backup 0.9.0, que ainda não possuía restore.json."""
    backup = history / database.name
    identifier = identifiers_by_key.get(history.parent.name)
    if not identifier or not backup.is_file():
        return None
    definition = definition_for(identifier)
    try:
        created_at = datetime.fromtimestamp(backup.stat().st_mtime, UTC).isoformat()
        restore_version = _database_versions(backup).get(identifier)
        restore_id = history.relative_to(data_root / HISTORY_DIRECTORY).as_posix()
    except OSError:
        return None
    return RestorePoint(
        restore_id,
        identifier,
        definition.label if definition else f"Base local: {identifier}",
        created_at,
        restore_version,
        current.get(identifier),
        "database",
        True,
    )


def list_restore_points(
    data_root: str | Path, database: str | Path
) -> list[RestorePoint]:
    root, db = Path(data_root).resolve(), Path(database).resolve()
    history_root = root / HISTORY_DIRECTORY
    if not history_root.is_dir() or db.parent != root:
        return []
    current = local_versions(root, db)
    known_identifiers = {item.identifier for item in BASE_DEFINITIONS} | set(
        _load_registry(root)
    )
    identifiers_by_key = {
        _history_key(identifier): identifier for identifier in known_identifiers
    }
    points: list[RestorePoint] = []
    for history in history_root.glob("*/*"):
        if not history.is_dir():
            continue
        point = _point_from_metadata(root, history)
        if point is None:
            point = _legacy_database_point(
                root, db, history, identifiers_by_key, current
            )
        if point is not None:
            points.append(point)
    points.sort(key=lambda item: item.created_at, reverse=True)
    return points


def latest_restore_point(
    data_root: str | Path, database: str | Path
) -> RestorePoint | None:
    points = list_restore_points(data_root, database)
    return points[0] if points else None


def local_inventory(
    data_root: str | Path, database: str | Path
) -> list[LocalBaseInventory]:
    """Inventário com nomes de requisitos; não expõe nomes crus de tabelas."""
    root = Path(data_root).resolve()
    return build_local_inventory(root, local_versions(root, database))


def _provided_identifiers(package: CatalogPackage) -> tuple[str, ...]:
    return package.provides or (package.identifier,)


def _installed_package_version(
    package: CatalogPackage, installed: dict[str, str]
) -> str | None:
    values = [
        installed.get(identifier) for identifier in _provided_identifiers(package)
    ]
    if all(value == package.version for value in values):
        return package.version
    present = [value for value in values if value]
    if not present:
        return None
    if len(present) == len(values) and len(set(present)) == 1:
        return present[0]
    return f"Parcial: {len(present)}/{len(values)} base(s) com versão registrada"


def compare_catalog(
    catalog: Catalog, data_root: str | Path, database: str | Path
) -> list[UpdateStatus]:
    installed = local_versions(data_root, database)
    status = []
    for package in catalog.packages:
        current = _installed_package_version(package, installed)
        if current == package.version:
            state, detail = "atual", "A versão publicada já está instalada."
        elif current:
            state, detail = "disponivel", "Há uma versão nova validada pelo publicador."
        else:
            state, detail = (
                "disponivel",
                "A base ainda não possui versão registrada localmente.",
            )
        if package.foreign_feature_count:
            detail += (
                f" A publicação de origem contém {package.foreign_feature_count} CAR(s) de outra UF, "
                "preservados e conferidos pelo pacote assinado."
            )
        definition = definition_for(package.identifier)
        status.append(
            UpdateStatus(
                package.identifier,
                display_label(package.identifier, package.label),
                current,
                package.version,
                state,
                detail,
                definition.regulatory_basis if definition else "Não definido",
                definition.coverage if definition else "Não avaliada",
                package.source_date or "Não declarada (catálogo legado)",
            )
        )
    return status


def update_lock_path(data_root: str | Path) -> Path:
    return Path(data_root).resolve() / UPDATE_DIRECTORY / LOCK_FILENAME


def ensure_not_updating(data_root: str | Path) -> None:
    if update_lock_path(data_root).exists():
        raise UpdateError(
            "Uma atualização de bases está em andamento. Aguarde a conclusão antes de consultar."
        )


def _acquire_update_lock(data_root: Path) -> Path:
    path = update_lock_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise UpdateError(
            "Já existe uma atualização ou restauração em andamento. A base local foi preservada."
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(datetime.now(UTC).isoformat())
    return path


def _release_update_lock(path: Path) -> None:
    path.unlink(missing_ok=True)


class LocalUpdater:
    """Promove um pacote de dados somente após validação integral em estágio."""

    def __init__(
        self,
        data_root: str | Path,
        database: str | Path,
        client: CatalogClient,
        progress: Callable[[int, str], None] | None = None,
    ):
        self.data_root = Path(data_root).resolve()
        self.database = Path(database).resolve()
        self.client = client
        self.progress = progress
        if not self.data_root.is_dir() or self.database.parent != self.data_root:
            raise UpdateError(
                "A pasta de dados e o banco SQLite selecionados são incompatíveis."
            )

    def _emit_progress(self, value: int, message: str) -> None:
        if self.progress is not None:
            self.progress(max(0, min(100, int(value))), message)

    def _download_package(self, package: CatalogPackage, staging: Path) -> Path:
        # O parcial fica fora do estágio aleatório para sobreviver a queda de
        # rede/QGIS. O nome deriva somente do hash assinado, nunca da URL.
        archive = self.data_root / DOWNLOAD_DIRECTORY / f"{package.sha256[:24]}.part"

        def download_progress(received: int, total: int) -> None:
            percent = 8 + int((received / max(total, 1)) * 22)
            self._emit_progress(
                percent, f"Baixando pacote assinado: {received:,} de {total:,} bytes…"
            )

        self.client.download_package(
            package.url,
            archive,
            package.size_bytes,
            package.sha256,
            progress=download_progress,
        )
        return archive

    def _payloads(
        self, archive: Path, package: CatalogPackage, staging: Path
    ) -> tuple[dict[str, Any], dict[str, Path]]:
        try:
            with zipfile.ZipFile(archive) as zipped:
                entries = {}
                for entry in zipped.infolist():
                    if entry.filename in entries:
                        raise UpdateError("Pacote ZIP contém nomes duplicados.")
                    entries[entry.filename] = entry
                if "package.json" not in entries:
                    raise UpdateError("Pacote sem package.json.")
                manifest = json.loads(zipped.read("package.json").decode("utf-8"))
                if not isinstance(manifest, dict):
                    raise UpdateError("Manifesto do pacote inválido.")
                for key, expected in (
                    ("id", package.identifier),
                    ("version", package.version),
                    ("strategy", package.strategy),
                ):
                    if manifest.get(key) != expected:
                        raise UpdateError(
                            "Pacote não corresponde ao catálogo assinado."
                        )
                manifest_provides = manifest.get("provides")
                if package.source_date is not None and manifest_provides != list(
                    _provided_identifiers(package)
                ):
                    raise UpdateError(
                        "Bases atendidas pelo pacote divergem do catálogo assinado."
                    )
                if manifest_provides is not None and manifest_provides != list(
                    _provided_identifiers(package)
                ):
                    raise UpdateError(
                        "Bases atendidas pelo pacote divergem do catálogo assinado."
                    )
                if (
                    package.strategy == "replace_file"
                    and manifest.get("target") != package.target
                ):
                    raise UpdateError("Destino do pacote diverge do catálogo assinado.")
                if (
                    manifest.get("foreign_feature_count", 0)
                    != package.foreign_feature_count
                ):
                    raise UpdateError(
                        "Exceções estaduais do pacote divergem do catálogo assinado."
                    )
                raw_payloads = manifest.get("payloads")
                if not isinstance(raw_payloads, dict) or not raw_payloads:
                    raise UpdateError("Pacote sem payload válido.")
                requested = []
                total_extracted = 0
                for name, member in raw_payloads.items():
                    _safe_identifier(name, "nome do payload")
                    member_name = _safe_relative_path(member, "payload")
                    payload_entry = entries.get(member_name)
                    if payload_entry is None or not member_name.startswith("payload/"):
                        raise UpdateError("Payload ausente ou fora da pasta permitida.")
                    if (
                        payload_entry.is_dir()
                        or payload_entry.flag_bits & 0x1
                        or payload_entry.file_size <= 0
                    ):
                        raise UpdateError("Payload ZIP inválido.")
                    total_extracted += payload_entry.file_size
                    if total_extracted > MAX_EXTRACTED_PACKAGE_BYTES:
                        raise UpdateError(
                            "Pacote descompactado acima do limite permitido."
                        )
                    requested.append((name, payload_entry))
                if shutil.disk_usage(staging).free < total_extracted:
                    raise UpdateError(
                        "Espaço livre insuficiente para validar a atualização local."
                    )
                extracted = {}
                for name, entry in requested:
                    # A extensão é funcional para leitores compactados (por
                    # exemplo, microdados Sicor .gz); o nome vem do membro já
                    # validado e nunca define diretórios locais.
                    suffix = PurePosixPath(entry.filename).suffix
                    destination = staging / "payload" / f"{name}{suffix}"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(entry) as source, destination.open("wb") as target:
                        written = 0
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            written += len(block)
                            if written > entry.file_size:
                                raise UpdateError("Payload ZIP com tamanho inválido.")
                            target.write(block)
                    if written != entry.file_size:
                        raise UpdateError("Payload ZIP truncado.")
                    extracted[name] = destination
                return manifest, extracted
        except (
            OSError,
            zipfile.BadZipFile,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise UpdateError(
                "Pacote de atualização inválido. A base local foi preservada."
            ) from exc

    def _record_installation(self, package: CatalogPackage) -> None:
        registry = _load_registry(self.data_root)
        installed_at = datetime.now(UTC).isoformat()
        for identifier in _provided_identifiers(package):
            registry[identifier] = {
                "version": package.version,
                "sha256": package.sha256,
                "installed_at": installed_at,
                "package_id": package.identifier,
                "source_date": package.source_date or "",
            }
        _write_registry(self.data_root, registry)

    def _replace_file(
        self,
        package: CatalogPackage,
        payloads: dict[str, Path],
        registry_snapshot: dict[str, dict[str, str]],
        restore_version: str | None,
    ) -> None:
        if set(payloads) != {"file"}:
            raise UpdateError(
                "Pacote de arquivo deve conter exatamente um payload chamado file."
            )
        target = _safe_target(self.data_root, package.target or "")
        source = payloads["file"]
        if target.suffix.lower() == ".gpkg":
            uf = (
                target.name[:2].upper()
                if re.fullmatch(r"[A-Z]{2}_AREA_IMOVEL\.gpkg", target.name)
                else None
            )
            validate_geopackage(
                source, uf=uf, expected_foreign_features=package.foreign_feature_count
            )
        elif source.stat().st_size == 0:
            raise UpdateError("Arquivo de atualização vazio.")
        self._emit_progress(72, "Criando ponto de restauração do arquivo atual…")
        history = _create_history_directory(self.data_root, package.identifier)
        target_existed = target.exists()
        backup_name = target.name if target_existed else None
        if target.exists():
            backup = history / target.name
            shutil.copy2(target, backup)
        _write_restore_metadata(
            history,
            identifier=package.identifier,
            label=package.label,
            strategy=package.strategy,
            kind="file",
            backup_file=backup_name,
            target=package.target,
            target_existed=target_existed,
            registry_snapshot=registry_snapshot,
            restore_version=restore_version,
            replaced_version=package.version,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        # O bloqueio exclusivo da atualização elimina concorrência; um nome
        # curto evita ultrapassar o limite legado de caminho do Windows.
        temporary = target.with_name(f".{target.name}.part")
        shutil.copy2(source, temporary)
        try:
            self._emit_progress(90, "Promovendo o arquivo validado…")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _replace_database(
        self,
        package: CatalogPackage,
        manifest: dict[str, Any],
        payloads: dict[str, Path],
        staging: Path,
        registry_snapshot: dict[str, dict[str, str]],
        restore_version: str | None,
    ) -> None:
        if not self.database.is_file():
            raise UpdateError(
                "Banco local não localizado; não é seguro aplicar atualização incremental."
            )
        # A promoção preserva uma cópia em estágio e outra para reversão. A
        # checagem ocorre antes de escrever no banco ativo, especialmente para
        # atualizações Sicor de dezenas de gigabytes.
        required_space = self.database.stat().st_size * 2
        if shutil.disk_usage(self.data_root).free < required_space:
            raise UpdateError(
                "Espaço livre insuficiente para preparar e reverter a atualização do banco."
            )
        staged_database = staging / self.database.name
        self._emit_progress(42, "Preparando uma cópia temporária do banco…")
        snapshot_database(
            self.database,
            staged_database,
            progress=lambda copied, total: self._emit_progress(
                42 + int((copied / max(total, 1)) * 10),
                f"Copiando banco para validação: {copied:,} de {total:,} páginas…",
            ),
        )
        source_reference = f"atualizacao-assinada:{package.identifier}:{package.version}:{package.sha256[:12]}"
        connection = connect(staged_database)
        try:
            initialize(connection)
            self._emit_progress(55, "Importando a nova versão na cópia temporária…")
            if package.strategy == "import_mma_mcr":
                if set(payloads) != {"file"}:
                    raise UpdateError("Pacote MMA/MCR inválido.")
                import_file(
                    connection,
                    "mma_mcr",
                    payloads["file"],
                    escopo="nacional",
                    validade_ate=package.validity_until,
                    source_reference=source_reference,
                )
            elif package.strategy == "import_mte":
                if set(payloads) != {"file"}:
                    raise UpdateError("Pacote MTE inválido.")
                import_mte(
                    connection,
                    payloads["file"],
                    validade_ate=package.validity_until or "",
                    source_reference=source_reference,
                )
            elif package.strategy == "import_sicor":
                permitted = {"mutuarios", "propriedades", "operacoes", "complementos"}
                gleba_payloads = sorted(
                    name
                    for name in payloads
                    if re.fullmatch(r"glebas(?:_[A-Za-z0-9_.-]+)?", name)
                )
                if not {"mutuarios", "propriedades"}.issubset(payloads) or not set(
                    payloads
                ).issubset(permitted | set(gleba_payloads)):
                    raise UpdateError("Pacote Sicor sem os arquivos obrigatórios.")
                payload_scopes = manifest.get("payload_scopes", {})
                if not isinstance(payload_scopes, dict):
                    raise UpdateError("Escopos dos arquivos Sicor inválidos.")
                scopes = {}
                for name in payloads:
                    scope = payload_scopes.get(name, package.scope)
                    if not isinstance(scope, str) or not re.fullmatch(
                        r"[A-Za-z0-9_.:-]{3,100}", scope
                    ):
                        raise UpdateError(f"Escopo Sicor inválido para {name}.")
                    scopes[name] = scope
                gleba_scopes = [scopes[name] for name in gleba_payloads]
                if len(set(gleba_scopes)) != len(gleba_scopes):
                    raise UpdateError(
                        "Arquivos de geometria Sicor exigem escopos distintos."
                    )
                connection.execute("BEGIN IMMEDIATE")
                try:
                    ordered = [
                        name
                        for name in (
                            "mutuarios",
                            "propriedades",
                            "operacoes",
                            "complementos",
                        )
                        if name in payloads
                    ] + gleba_payloads
                    for name in ordered:
                        kind = "glebas" if name.startswith("glebas") else name
                        import_file(
                            connection,
                            kind,
                            payloads[name],
                            escopo=scopes[name],
                            commit=False,
                            source_reference=source_reference,
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            else:
                raise UpdateError("Estratégia de banco desconhecida.")
            self._emit_progress(72, "Verificando a integridade da cópia atualizada…")
            quick_check = connection.execute("PRAGMA quick_check").fetchone()
            if not quick_check or quick_check[0] != "ok":
                raise UpdateError(
                    "Banco preparado não passou na verificação de integridade."
                )
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
        self._emit_progress(82, "Guardando a versão atual para restauração…")
        history = _create_history_directory(self.data_root, package.identifier)
        snapshot_database(
            self.database,
            history / self.database.name,
            progress=lambda copied, total: self._emit_progress(
                82 + int((copied / max(total, 1)) * 8),
                f"Preservando banco atual: {copied:,} de {total:,} páginas…",
            ),
        )
        for sidecar in (
            self.database.with_name(self.database.name + "-wal"),
            self.database.with_name(self.database.name + "-shm"),
        ):
            if sidecar.exists():
                shutil.copy2(sidecar, history / sidecar.name)
                sidecar.unlink()
        _write_restore_metadata(
            history,
            identifier=package.identifier,
            label=package.label,
            strategy=package.strategy,
            kind="database",
            backup_file=self.database.name,
            target=None,
            target_existed=True,
            registry_snapshot=registry_snapshot,
            restore_version=restore_version,
            replaced_version=package.version,
        )
        self._emit_progress(92, "Substituindo o banco ativo pela cópia validada…")
        os.replace(staged_database, self.database)

    def apply(self, package: CatalogPackage) -> UpdateStatus:
        self._emit_progress(0, "Iniciando atualização local…")
        lock = _acquire_update_lock(self.data_root)
        # Doze caracteres aleatórios evitam colisões e preservam margem para
        # bancos SQLite dentro de pastas de usuário com caminhos extensos.
        staging = self.data_root / STAGING_DIRECTORY / uuid.uuid4().hex[:12]
        try:
            registry_snapshot = _load_registry(self.data_root)
            restore_version = _installed_package_version(
                package, local_versions(self.data_root, self.database)
            )
            staging.mkdir(parents=True, exist_ok=False)
            self._emit_progress(5, "Preparando a área temporária protegida…")
            archive = self._download_package(package, staging)
            self._emit_progress(32, "Validando manifesto e conteúdo do pacote…")
            manifest, payloads = self._payloads(archive, package, staging)
            archive.unlink(missing_ok=True)
            if package.strategy == "replace_file":
                self._replace_file(
                    package, payloads, registry_snapshot, restore_version
                )
            else:
                self._replace_database(
                    package,
                    manifest,
                    payloads,
                    staging,
                    registry_snapshot,
                    restore_version,
                )
            self._emit_progress(97, "Registrando a versão instalada…")
            self._record_installation(package)
            self._emit_progress(100, "Atualização validada e aplicada localmente.")
            return UpdateStatus(
                package.identifier,
                package.label,
                package.version,
                package.version,
                "atual",
                "Atualização validada e aplicada localmente.",
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            _release_update_lock(lock)


def _read_restore_document(
    data_root: Path, database: Path, point: RestorePoint
) -> tuple[Path, dict[str, Any]]:
    history = _history_path(data_root, point.restore_id)
    metadata_path = history / RESTORE_METADATA_FILENAME
    if point.legacy:
        backup = history / database.name
        if not backup.is_file():
            raise UpdateError("A cópia legada do banco não está mais disponível.")
        return history, {
            "package": {
                "id": point.identifier,
                "label": point.label,
                "strategy": "legacy_database",
                "target": None,
            },
            "kind": "database",
            "backup_file": database.name,
            "target_existed": True,
            "registry_snapshot": None,
            "restore_version": point.restore_version,
            "replaced_version": point.replaced_version,
        }
    try:
        document = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(
            "O metadado do ponto de restauração está indisponível ou corrompido."
        ) from exc
    parsed = _point_from_metadata(data_root, history)
    if parsed is None or parsed.restore_id != point.restore_id:
        raise UpdateError("O ponto de restauração não passou na validação local.")
    return history, document


def _check_database(path: Path) -> None:
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        result = connection.execute("PRAGMA quick_check").fetchone()
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise UpdateError(
            "A cópia de restauração do banco é inválida. O banco atual foi preservado."
        ) from exc
    finally:
        if connection is not None:
            connection.close()
    if not result or result[0] != "ok":
        raise UpdateError(
            "A cópia de restauração não passou na verificação de integridade."
        )


class LocalRestorer:
    """Restaura somente o ponto mais recente e cria antes um ponto de desfazer."""

    def __init__(
        self,
        data_root: str | Path,
        database: str | Path,
        progress: Callable[[int, str], None] | None = None,
    ):
        self.data_root = Path(data_root).resolve()
        self.database = Path(database).resolve()
        self.progress = progress
        if (
            not self.data_root.is_dir()
            or self.database.parent != self.data_root
            or not self.database.is_file()
        ):
            raise UpdateError(
                "A pasta de dados e o banco SQLite selecionados são incompatíveis."
            )

    def _emit_progress(self, value: int, message: str) -> None:
        if self.progress is not None:
            self.progress(max(0, min(100, int(value))), message)

    def _registry_to_restore(
        self,
        document: dict[str, Any],
        identifier: str,
        current_registry: dict[str, dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        snapshot = document.get("registry_snapshot")
        if snapshot is None:  # histórico legado da 0.9.0
            restored = dict(current_registry)
            restored.pop(identifier, None)
            return restored
        return _valid_registry_snapshot(snapshot)

    def _write_undo_metadata(
        self,
        history: Path,
        point: RestorePoint,
        document: dict[str, Any],
        *,
        kind: str,
        backup_file: str | None,
        target: str | None,
        target_existed: bool,
        registry: dict[str, dict[str, str]],
        current_version: str | None,
    ) -> None:
        package = document["package"]
        _write_restore_metadata(
            history,
            identifier=point.identifier,
            label=point.label,
            strategy=str(package.get("strategy") or "restore"),
            kind=kind,
            backup_file=backup_file,
            target=target,
            target_existed=target_existed,
            registry_snapshot=registry,
            restore_version=current_version,
            replaced_version=point.restore_version,
        )

    def _restore_database(
        self,
        point: RestorePoint,
        history: Path,
        document: dict[str, Any],
        staging: Path,
    ) -> None:
        backup_name = _safe_relative_path(
            document.get("backup_file"), "arquivo de restauração"
        )
        source = history / Path(*PurePosixPath(backup_name).parts)
        if not source.is_file():
            raise UpdateError("A cópia anterior do banco não está mais disponível.")
        required_space = source.stat().st_size + self.database.stat().st_size
        if shutil.disk_usage(self.data_root).free < required_space:
            raise UpdateError(
                "Espaço livre insuficiente para restaurar e preservar o banco atual."
            )

        self._emit_progress(18, "Copiando a versão anterior para uma área temporária…")
        _check_database(source)
        staged_database = staging / self.database.name
        snapshot_database(
            source,
            staged_database,
            progress=lambda copied, total: self._emit_progress(
                18 + int((copied / max(total, 1)) * 18),
                f"Preparando versão anterior: {copied:,} de {total:,} páginas…",
            ),
        )
        self._emit_progress(38, "Verificando a integridade da versão anterior…")
        _check_database(staged_database)

        current_registry = _load_registry(self.data_root)
        current_version = local_versions(self.data_root, self.database).get(
            point.identifier
        )
        self._emit_progress(
            55, "Preservando o banco atual para desfazer a restauração…"
        )
        undo = _create_history_directory(self.data_root, point.identifier)
        undo_database = undo / self.database.name
        snapshot_database(
            self.database,
            undo_database,
            progress=lambda copied, total: self._emit_progress(
                55 + int((copied / max(total, 1)) * 23),
                f"Preservando banco atual: {copied:,} de {total:,} páginas…",
            ),
        )
        for sidecar in (
            self.database.with_name(self.database.name + "-wal"),
            self.database.with_name(self.database.name + "-shm"),
        ):
            if sidecar.exists():
                shutil.copy2(sidecar, undo / sidecar.name)
                sidecar.unlink()
        self._write_undo_metadata(
            undo,
            point,
            document,
            kind="database",
            backup_file=self.database.name,
            target=None,
            target_existed=True,
            registry=current_registry,
            current_version=current_version,
        )

        registry_to_restore = self._registry_to_restore(
            document, point.identifier, current_registry
        )
        promoted = False
        try:
            self._emit_progress(82, "Restaurando o banco anterior…")
            os.replace(staged_database, self.database)
            promoted = True
            _write_registry(self.data_root, registry_to_restore)
        except Exception as exc:
            if promoted:
                recovery = staging / (self.database.stem + "-recovery.db")
                snapshot_database(undo_database, recovery)
                os.replace(recovery, self.database)
                _write_registry(self.data_root, current_registry)
            raise UpdateError(
                "A restauração falhou e o banco atual foi recomposto."
            ) from exc

    def _restore_file(
        self,
        point: RestorePoint,
        history: Path,
        document: dict[str, Any],
        staging: Path,
    ) -> None:
        package = document.get("package")
        if not isinstance(package, dict):
            raise UpdateError("Ponto de restauração de arquivo inválido.")
        target_relative = _safe_relative_path(
            package.get("target"), "destino restaurado"
        )
        target = _safe_target(self.data_root, target_relative)
        target_existed = document.get("target_existed") is True
        staged_file: Path | None = None
        if target_existed:
            backup_name = _safe_relative_path(
                document.get("backup_file"), "arquivo de restauração"
            )
            source = history / Path(*PurePosixPath(backup_name).parts)
            if not source.is_file():
                raise UpdateError(
                    "A cópia anterior do arquivo não está mais disponível."
                )
            staged_file = staging / target.name
            shutil.copy2(source, staged_file)
            if target.suffix.lower() == ".gpkg":
                uf = (
                    target.name[:2].upper()
                    if re.fullmatch(r"[A-Z]{2}_AREA_IMOVEL\.gpkg", target.name)
                    else None
                )
                validate_geopackage(staged_file, uf=uf)
            elif staged_file.stat().st_size == 0:
                raise UpdateError("A cópia anterior do arquivo está vazia.")

        current_registry = _load_registry(self.data_root)
        current_version = local_versions(self.data_root, self.database).get(
            point.identifier
        )
        self._emit_progress(
            55, "Preservando o arquivo atual para desfazer a restauração…"
        )
        undo = _create_history_directory(self.data_root, point.identifier)
        current_exists = target.is_file()
        undo_name = target.name if current_exists else None
        if current_exists:
            shutil.copy2(target, undo / target.name)
        self._write_undo_metadata(
            undo,
            point,
            document,
            kind="file",
            backup_file=undo_name,
            target=target_relative,
            target_existed=current_exists,
            registry=current_registry,
            current_version=current_version,
        )

        registry_to_restore = self._registry_to_restore(
            document, point.identifier, current_registry
        )
        try:
            self._emit_progress(82, "Restaurando o arquivo anterior…")
            if staged_file is None:
                target.unlink(missing_ok=True)
            else:
                temporary = target.with_name(f".{target.name}.restore")
                shutil.copy2(staged_file, temporary)
                os.replace(temporary, target)
            _write_registry(self.data_root, registry_to_restore)
        except Exception as exc:
            if current_exists:
                temporary = target.with_name(f".{target.name}.recovery")
                shutil.copy2(undo / target.name, temporary)
                os.replace(temporary, target)
            else:
                target.unlink(missing_ok=True)
            _write_registry(self.data_root, current_registry)
            raise UpdateError(
                "A restauração falhou e o arquivo atual foi recomposto."
            ) from exc

    def restore_latest(self) -> UpdateStatus:
        self._emit_progress(0, "Localizando o ponto de restauração mais recente…")
        point = latest_restore_point(self.data_root, self.database)
        if point is None:
            raise UpdateError("Não existe versão anterior disponível para restauração.")
        lock = _acquire_update_lock(self.data_root)
        staging = self.data_root / STAGING_DIRECTORY / uuid.uuid4().hex[:12]
        try:
            # Revalida depois do bloqueio para não restaurar um ponto que deixou de ser o mais recente.
            current = latest_restore_point(self.data_root, self.database)
            if current is None or current.restore_id != point.restore_id:
                raise UpdateError(
                    "O histórico mudou antes da restauração; abra novamente a janela."
                )
            history, document = _read_restore_document(
                self.data_root, self.database, point
            )
            staging.mkdir(parents=True, exist_ok=False)
            self._emit_progress(8, "Validando o histórico local…")
            if point.kind == "database":
                self._restore_database(point, history, document, staging)
            elif point.kind == "file":
                self._restore_file(point, history, document, staging)
            else:  # pragma: no cover - validado na leitura
                raise UpdateError("Tipo de restauração desconhecido.")
            self._emit_progress(
                100, "Versão anterior restaurada e versão substituída preservada."
            )
            return UpdateStatus(
                point.identifier,
                point.label,
                point.restore_version,
                point.replaced_version,
                "restaurada",
                "Versão anterior restaurada; o estado substituído foi preservado para desfazer.",
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            _release_update_lock(lock)


def restore_latest(
    data_root: str | Path,
    database: str | Path,
    progress: Callable[[int, str], None] | None = None,
) -> UpdateStatus:
    return LocalRestorer(data_root, database, progress=progress).restore_latest()


def file_sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
