from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def repository_root() -> Path:
    """Find the checkout that contains ``src/plugin``.

    Console scripts resolve to ``.venv/.../site-packages/installer``, so
    ``Path(__file__).parents[2]`` is not the repository. Walk upward until both
    ``pyproject.toml`` and ``src/plugin`` exist.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (
            parent / "src" / "plugin"
        ).is_dir():
            return parent
    raise FileNotFoundError(
        "Não foi possível localizar o repositório (pyproject.toml e src/plugin). "
        "Execute o empacotamento a partir da árvore de fontes do projeto."
    )


def _plugin_version() -> str:
    try:
        root = repository_root()
        document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(document["project"]["version"])
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError):
        try:
            return version("qgis-plugin-microcredito")
        except PackageNotFoundError:
            return "0.9.5"


PLUGIN_VERSION = _plugin_version()


UFS = tuple(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)
ENVIRONMENTAL = (
    "embargos.gpkg",
    "terras_indigenas.gpkg",
    "territorios_quilombolas.gpkg",
    "unidades_conservacao.gpkg",
    "florestas_publicas.gpkg",
    "desmatamento_pos_2020.gpkg",
)
QGIS_PROCESS_NAMES = ("qgis-bin", "qgis-ltr-bin", "qgis")
SETTINGS_ORG = "Cactvs"
SETTINGS_APP = "CARMicrocredito"
