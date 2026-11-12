from __future__ import annotations

import base64

import pytest

from qgis_plugin_microcredito.infrastructure.updates import (
    HOMOLOGATION_PUBLISHER_PUBLIC_KEY_PEM,
    UpdateError,
    verify_catalog_signature,
)

PAYLOAD = b"catalog-homologacao-key-2026-10-26"
SIGNATURE = base64.b64decode(
    "cQziZSXZaWpern+JklSArG2uX/fOB+Gnpr9vDSDEXLpt968bXG7eXd8KT6fAkgd6m+BJnJWW1LxF"
    "qwhze67PkP/ZcIx+Vl/+jliu68GCz6Zvp53siAYC3zl+4btmUlTXKHQMjKNOP4k4+pxn9gHF8jY0e"
    "uJebAgKSsqxRE48Bt7dpU2mwPIwroqbLXzymIfH/iDb2f5fOVhNLnLuOIRon8iwyoU0v8oXRZObXX"
    "fh4kjgT9PnHBqzBtcIXI5ALtaQhh6aX/lrMgu4t4xI+u0y0uSd3qq+fTwqnBSfPvOuc7850Il6H9c"
    "WBSKJySa7m+tcpW/MYZol1pIdR7wIP/pZ0lPquWSm/2OPuq1LUMlkf0z03bJxOAzyZyViONqof78+A"
    "9ZzPowwI28yQPXrfAlxK8kNe6Tjvv6b5TjIicyoK+C8nzuX2sDLOC9EpuPMPlq/fc/+DL32s81rcpR"
    "97wA91yJ1wXnJ+Rjerp4uwS5OYLRzqlCevWMi3Gvgd60iflOp"
)


def test_homologation_key_verifies_custody_vector() -> None:
    verify_catalog_signature(PAYLOAD, SIGNATURE, HOMOLOGATION_PUBLISHER_PUBLIC_KEY_PEM)
    with pytest.raises(UpdateError, match="Assinatura do catálogo inválida"):
        verify_catalog_signature(
            PAYLOAD + b"-alterado", SIGNATURE, HOMOLOGATION_PUBLISHER_PUBLIC_KEY_PEM
        )
