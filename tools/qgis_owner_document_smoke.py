"""Valida no runtime do QGIS a exibição e a trava do documento do proprietário."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path


def _configure_qgis_runtime() -> tuple[Path, list[object]]:
    osgeo_root = Path(os.environ.get("OSGEO4W_ROOT", r"C:\Program Files\QGIS 3.40.10"))
    dll_handles: list[object] = []
    for directory in (
        osgeo_root / "bin",
        osgeo_root / "apps" / "Qt5" / "bin",
        osgeo_root / "apps" / "qgis-ltr" / "bin",
    ):
        if directory.is_dir():
            dll_handles.append(os.add_dll_directory(str(directory)))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return osgeo_root, dll_handles


def smoke(plugin_root: Path) -> dict[str, str]:
    osgeo_root, dll_handles = _configure_qgis_runtime()
    from qgis.core import QgsApplication

    root = plugin_root.resolve()
    if not (root / "metadata.txt").is_file() or not (root / "lib").is_dir():
        raise ValueError("Informe a raiz de um plugin QGIS extraído.")

    QgsApplication.setPrefixPath(str(osgeo_root / "apps" / "qgis-ltr"), True)
    application = QgsApplication([], False)
    application.initQgis()
    try:
        sys.path[:0] = [str(root.parent), str(root / "lib")]
        normalize_module = importlib.import_module(
            "qgis_plugin_microcredito.domain.normalize"
        )
        del normalize_module.format_document
        window_module = importlib.import_module(f"{root.name}.car_document_window")
        report_module = importlib.import_module(f"{root.name}.report")

        iface = type("Iface", (), {"mainWindow": lambda self: None})()
        window = window_module.CarDocumentWindow(iface, lambda: None)
        try:
            window.results = [
                {
                    "documento_normalizado": "12345678901",
                    "tipo_vinculo": "documento_na_propriedade",
                },
                {
                    "documento_normalizado": "11222333000144",
                    "tipo_vinculo": "mutuario_da_operacao",
                },
            ]
            window._fill_table()
            assert window.table.item(0, 1).text() == "123.456.789-01"
            assert window.table.item(1, 1).text() == "11.222.333/0001-44"

            try:
                report_module._report_payload({"documentos_proprietario_possuidor": []})
            except ValueError as exc:
                assert "proprietário/possuidor" in str(exc)
            else:
                raise AssertionError("Relatório incompleto não foi bloqueado.")
        finally:
            window.close()
    finally:
        application.exitQgis()
        for handle in dll_handles:
            handle.close()

    return {
        "plugin": root.name,
        "documentos_integrais": "ok",
        "trava_relatorio": "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin_root", type=Path)
    args = parser.parse_args()
    print(smoke(args.plugin_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
