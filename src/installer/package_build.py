"""Build portable data+plugin packages and validate homologated snapshots."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from installer.constants import ENVIRONMENTAL, PLUGIN_VERSION, UFS, repository_root
from installer.plugin_build import plugin_files
from qgis_plugin_microcredito.infrastructure.downloads import UFS as DOWNLOAD_UFS
from qgis_plugin_microcredito.infrastructure.downloads import validate_geopackage

ROOT = repository_root()


@dataclass(frozen=True)
class Entry:
    relative: str
    source: Path | None = None
    content: bytes | None = None

    @property
    def size(self) -> int:
        return (
            self.source.stat().st_size
            if self.source is not None
            else len(self.content or b"")
        )


def validate_inputs(data: str | Path) -> list[Path]:
    data_path = Path(data)
    states = list((data_path / "car").rglob("*_AREA_IMOVEL.gpkg"))
    names = [path.stem.removesuffix("_AREA_IMOVEL") for path in states]
    if len(names) != 27 or set(names) != DOWNLOAD_UFS:
        raise ValueError("O pacote deve conter cada uma das 27 UFs exatamente uma vez.")
    for path, uf in zip(states, names, strict=False):
        validate_geopackage(path, uf)
    for code in (
        "embargos",
        "terras_indigenas",
        "territorios_quilombolas",
        "unidades_conservacao",
        "florestas_publicas",
        "desmatamento_pos_2020",
    ):
        validate_geopackage(data_path / "ambientais" / (code + ".gpkg"))
    from database.session import connect

    database = connect(data_path / "car_microcredito.db", readonly=True)
    try:
        if (
            database.execute(
                "SELECT COUNT(*) FROM importacao WHERE ativo=1"
            ).fetchone()[0]
            == 0
        ):
            raise ValueError(
                "Banco sem edições ativas; migrar e homologar os escopos antes de distribuir."
            )
    finally:
        database.close()
    return states


def validate_sources(data: Path) -> None:
    database = data / "car_microcredito.db"
    if not database.is_file():
        raise FileNotFoundError(database)
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if schema != 3:
            raise ValueError(
                f"Banco incompatível: esquema {schema}; esperado 3 para a versão {PLUGIN_VERSION}."
            )
    finally:
        connection.close()
    found_states = tuple(
        sorted(path.parent.name for path in (data / "car").glob("*/*_AREA_IMOVEL.gpkg"))
    )
    if len(found_states) != 27 or set(found_states) != set(UFS):
        raise ValueError(f"Bases estaduais divergentes: {found_states}")
    missing = [
        name for name in ENVIRONMENTAL if not (data / "ambientais" / name).is_file()
    ]
    if missing:
        raise FileNotFoundError("Bases ambientais ausentes: " + ", ".join(missing))


def _readme(variant: str) -> bytes:
    mass = variant == "massa"
    title = (
        f"CAR MICROCRÉDITO CONSULTA EM MASSA {PLUGIN_VERSION}"
        if mass
        else f"CAR MICROCRÉDITO {PLUGIN_VERSION}"
    )
    lines = [
        title,
        "",
        "1. Extraia o ZIP inteiro para uma pasta fixa.",
        "2. Não execute os arquivos de dentro do ZIP.",
        "3. Feche todas as janelas do QGIS.",
        "4. Execute: car-microcredito-installer verify .",
        "5. Execute: car-microcredito-installer install .",
        "6. Abra o QGIS e ative o complemento na seção Instalados.",
        "",
        "Não mova a pasta depois da instalação. Se mover, execute o instalador novamente.",
        "QGIS mínimo: 3.40",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8-sig")


def package_entries(variant: str, data: Path) -> tuple[str, list[Entry]]:
    mass = variant == "massa"
    folder = "car_microcredito_supremo_qgis" if mass else "car_microcredito_qgis"
    package_name = (
        f"CAR_Microcredito_Consulta_em_Massa_{PLUGIN_VERSION}"
        if mass
        else f"CAR_Microcredito_Portatil_{PLUGIN_VERSION}"
    )
    entries = [
        Entry("LEIA_ME.txt", content=_readme(variant)),
        Entry(
            "VERSAO.txt",
            content=(
                f"{'CAR Microcrédito - Consulta em Massa' if mass else 'CAR Microcrédito'} "
                f"{PLUGIN_VERSION}\r\nQGIS mínimo: 3.40\r\n"
            ).encode("utf-8-sig"),
        ),
        Entry(
            "TIPO_PACOTE.txt",
            content=(
                "consulta_em_massa\r\n" if mass else "consulta_individual\r\n"
            ).encode("ascii"),
        ),
    ]
    if mass:
        template = ROOT / "src" / "plugin" / "modelo_consulta_lote.xlsx"
        entries.append(Entry("modelo_consulta_lote.xlsx", source=template))
    for relative, content in plugin_files(supreme=mass).items():
        entries.append(Entry(f"arquivos/plugin/{folder}/{relative}", content=content))
    entries.append(
        Entry("arquivos/dados/car_microcredito.db", source=data / "car_microcredito.db")
    )
    for state in UFS:
        entries.append(
            Entry(
                f"arquivos/dados/car/{state}/{state}_AREA_IMOVEL.gpkg",
                source=data / "car" / state / f"{state}_AREA_IMOVEL.gpkg",
            )
        )
    for name in ENVIRONMENTAL:
        entries.append(
            Entry(
                f"arquivos/dados/ambientais/{name}", source=data / "ambientais" / name
            )
        )
    return package_name, entries


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_package(variant: str, data: Path, output: Path) -> Path:
    validate_sources(data)
    package_name, entries = package_entries(variant, data)
    manifest = {
        entry.relative: (
            hashlib.sha256(entry.content or b"").hexdigest()
            if entry.source is None
            else hash_file(entry.source)
        )
        for entry in entries
    }
    json_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    entries.append(Entry("MANIFESTO_SHA256.json", content=json_bytes))
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{package_name}.zip"
    temporary = destination.with_suffix(".zip.part")
    temporary.unlink(missing_ok=True)
    try:
        import zipfile

        with zipfile.ZipFile(
            temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True
        ) as archive:
            for entry in entries:
                archive_name = f"{package_name}/{entry.relative}"
                if entry.source is not None:
                    archive.write(entry.source, archive_name)
                else:
                    archive.writestr(archive_name, entry.content or b"")
            archive.writestr(f"{package_name}/arquivos/output/pdf/", b"")
            archive.writestr(f"{package_name}/arquivos/output/lotes/", b"")
            archive.writestr(f"{package_name}/arquivos/resultados/", b"")
        temporary.replace(destination)
        destination.with_suffix(".sha256.txt").write_text(
            f"{hash_file(destination)}  {destination.name}\n", encoding="ascii"
        )
        return destination
    finally:
        temporary.unlink(missing_ok=True)
