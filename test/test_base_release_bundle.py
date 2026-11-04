from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from qgis_plugin_microcredito.infrastructure.updates import (
    TEST_PUBLISHER_PUBLIC_KEY_PEM,
    BaseReleaseBundle,
)


def _package() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "package.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "id": "mte",
                    "version": "2026.10.06",
                    "strategy": "import_mte",
                    "provides": ["mte"],
                    "payloads": {"file": "payload/mte.csv"},
                },
                sort_keys=True,
            ),
        )
        archive.writestr("payload/mte.csv", b"conteudo-oficial")
    return stream.getvalue()


def test_local_release_bundle_verifies_and_extracts_embedded_package(
    tmp_path: Path,
) -> None:
    package = _package()
    catalog_payload = json.dumps(
        {
            "schema_version": 1,
            "issued_at": "2026-10-15T12:00:00-03:00",
            "expires_at": "2027-10-15T12:00:00-03:00",
            "packages": [
                {
                    "id": "mte",
                    "label": "Cadastro MTE",
                    "version": "2026.10.06",
                    "strategy": "import_mte",
                    "url": "carbases://packages/mte.zip",
                    "sha256": hashlib.sha256(package).hexdigest(),
                    "size_bytes": len(package),
                    "validity_until": "2027-04-05",
                }
            ],
        }
    ).encode()
    release_path = tmp_path / "bases-2026-10.carbases"
    with zipfile.ZipFile(release_path, "w", allowZip64=True) as archive:
        archive.writestr("catalog.json", catalog_payload)
        archive.writestr("catalog.json.sig", b"assinatura-teste")
        archive.writestr("packages/mte.zip", package)

    with patch(
        "qgis_plugin_microcredito.infrastructure.updates.verify_catalog_signature"
    ) as verify:
        release = BaseReleaseBundle(release_path, TEST_PUBLISHER_PUBLIC_KEY_PEM)
        catalog = release.fetch_catalog()
        destination = tmp_path / "downloaded.zip"
        release.download_package(
            catalog.packages[0].url,
            destination,
            catalog.packages[0].size_bytes,
            catalog.packages[0].sha256,
        )

    verify.assert_called_once_with(
        catalog_payload, b"assinatura-teste", TEST_PUBLISHER_PUBLIC_KEY_PEM
    )
    assert destination.read_bytes() == package
