"""Tiny, genuinely signed update bundle used by subprocess integration tests."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import Path

_MODULUS = base64.b64decode(
    "rl7OHaRgOpp4UVNkGA8gg/Bkze+iTfWuPdEjh1VJp3XwdKrkQl5uIKYbqnCq1i4p"
    "hX5tDoyzDeOdzMom23Aqv22I9jzb7X4igpPksE5auvFPvPVuM5tXU9e6vKFTxkHg"
    "f+0ESeNNuvBNsjGvpzUNZTWA+ko4KmRcnUj9M7y/YNJeLaEcxYG9VYJQyHSdEhSf"
    "TVsYQGKkHJ4RZ7Rk6q95JAkIthfmHeFwBrxeYLebR3dAOFAsUDHhk3zC9LJKrtO8"
    "eqHYnIqsw+TGAQqtdDCfCV2KEbPJs35QjHoUULCSml7w4LSFHfITEEGU6hZ6g7hw"
    "SaKZXBd7tSp9CgcgWtSFRQ=="
)
_PRIVATE_EXPONENT = base64.b64decode(
    "OSlDEFyOXye8QYzAx1JOKnJn2UqxPjVHxWQF7Zt75bW3+cb7xPYHzBQoBZuhpUzE"
    "t8pWHerp16fCVxv92PnQSaiyuWYCArzSu1OYKGPHQnlQ1nTuh2RpIEccJDIOsHNwE"
    "P+15DLrjFiyX7QCDSJLHd6IRYSHHP6Bjd4bgxZg9m/1Uks9LQI0g8BBjmE2AGBDWW"
    "GrIMFjwKVGjJzYi9X8NcXINoxUD3UG4h/6ayBxXWqbiV7KtCx54Ukjv/Rku8JKnJe"
    "OAQ2z6eXQC5FVYmxN8qGsfynnLNb0SwE5PQP2s20GfuO2vwjrkVCoaiCxYLOGptzS"
    "7aNoeMy138nEGYsNkQ=="
)
_PUBLIC_DER = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArl7OHaRgOpp4UVNkGA8g"
    "g/Bkze+iTfWuPdEjh1VJp3XwdKrkQl5uIKYbqnCq1i4phX5tDoyzDeOdzMom23Aq"
    "v22I9jzb7X4igpPksE5auvFPvPVuM5tXU9e6vKFTxkHgf+0ESeNNuvBNsjGvpzUN"
    "ZTWA+ko4KmRcnUj9M7y/YNJeLaEcxYG9VYJQyHSdEhSfTVsYQGKkHJ4RZ7Rk6q9"
    "5JAkIthfmHeFwBrxeYLebR3dAOFAsUDHhk3zC9LJKrtO8eqHYnIqsw+TGAQqtdDC"
    "fCV2KEbPJs35QjHoUULCSml7w4LSFHfITEEGU6hZ6g7hwSaKZXBd7tSp9CgcgWtS"
    "FRQIDAQAB"
)
TEST_PUBLIC_KEY_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    + "\n".join(textwrap.wrap(_PUBLIC_DER, 64))
    + "\n-----END PUBLIC KEY-----\n"
)


@dataclass(frozen=True)
class SignedReleaseFixture:
    release: Path
    public_key: Path
    target: str
    published_content: bytes


def _sign(payload: bytes) -> bytes:
    digest_info = (
        bytes.fromhex("3031300d060960864801650304020105000420")
        + hashlib.sha256(payload).digest()
    )
    width = len(_MODULUS)
    encoded = (
        b"\x00\x01" + (b"\xff" * (width - len(digest_info) - 3)) + b"\x00" + digest_info
    )
    signature = pow(
        int.from_bytes(encoded, "big"),
        int.from_bytes(_PRIVATE_EXPONENT, "big"),
        int.from_bytes(_MODULUS, "big"),
    )
    return signature.to_bytes(width, "big")


def write_signed_release(root: Path) -> SignedReleaseFixture:
    root.mkdir(parents=True, exist_ok=True)
    target = "normativos/fonte_teste.txt"
    published_content = "publicação assinada — ação".encode()
    manifest = {
        "schema_version": 1,
        "id": "fonte_teste",
        "version": "2026.10.23",
        "strategy": "replace_file",
        "target": target,
        "payloads": {"file": "payload/fonte_teste.txt"},
    }
    package_stream = io.BytesIO()
    with zipfile.ZipFile(
        package_stream, "w", compression=zipfile.ZIP_DEFLATED
    ) as package:
        package.writestr("package.json", json.dumps(manifest, sort_keys=True))
        package.writestr("payload/fonte_teste.txt", published_content)
    package_bytes = package_stream.getvalue()
    catalog = {
        "schema_version": 1,
        "issued_at": "2026-10-01T00:00:00+00:00",
        "expires_at": "2030-10-01T00:00:00+00:00",
        "packages": [
            {
                "id": "fonte_teste",
                "label": "Fonte de teste assinada",
                "version": "2026.10.23",
                "strategy": "replace_file",
                "url": "carbases://packages/fonte_teste.zip",
                "sha256": hashlib.sha256(package_bytes).hexdigest(),
                "size_bytes": len(package_bytes),
                "target": target,
            }
        ],
    }
    catalog_bytes = json.dumps(
        catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    release = root / "bases ação.carbases"
    with zipfile.ZipFile(release, "w", allowZip64=True) as bundle:
        bundle.writestr("catalog.json", catalog_bytes)
        bundle.writestr("catalog.json.sig", _sign(catalog_bytes))
        bundle.writestr("packages/fonte_teste.zip", package_bytes)
    public_key = root / "publicador teste.pem"
    public_key.write_text(TEST_PUBLIC_KEY_PEM, encoding="ascii")
    return SignedReleaseFixture(release, public_key, target, published_content)
