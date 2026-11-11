from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from installer.base_release import build_base_release
from installer.constants import PLUGIN_VERSION
from installer.install import configure_data_paths, install_package, qgis_is_running
from installer.local_bases import install_local_bases
from installer.package_build import build_package
from installer.plugin_build import main as plugin_build_main
from installer.prebuilt_bases import prepare_prebuilt_bases
from installer.prebuilt_release import build_prebuilt_release
from installer.update_package import (
    STRATEGIES,
    _payload_map,
    _value_map,
    build_update_package,
)
from installer.verify import verify_package
from qgis_plugin_microcredito.infrastructure.updates import (
    PUBLISHER_PUBLIC_KEY_PEM,
)

app = typer.Typer(
    help="Instalador e empacotador do CAR Microcrédito", no_args_is_help=True
)


@app.command()
def verify(package: Path) -> None:
    """Verifica manifesto, 27 UFs, camadas ambientais e versão do plugin."""
    verify_package(package)
    typer.echo(f"Integridade verificada: plugin {PLUGIN_VERSION}.")


@app.command()
def install(
    package: Path,
    profiles_root: Annotated[Path | None, typer.Option("--profiles-root")] = None,
    skip_settings: Annotated[
        bool,
        typer.Option(
            "--skip-settings",
            help="Opção legada: instala somente o plugin, sem inicializar as bases fixas.",
        ),
    ] = False,
    skip_qgis_check: Annotated[bool, typer.Option("--skip-qgis-check")] = False,
    profile: Annotated[str | None, typer.Option("--profile")] = None,
) -> None:
    """Instala o plugin e inicializa a pasta fixa de bases do usuário."""
    destinations = install_package(
        package,
        profiles_root=profiles_root,
        skip_settings=skip_settings,
        skip_qgis_check=skip_qgis_check,
        profile=profile,
    )
    typer.echo("Instalação concluída.")
    for destination in destinations:
        typer.echo(f"Plugin instalado: {destination}")
    typer.echo(
        "Abra o QGIS, ative o complemento em Instalados e use o menu Complementos."
    )


@app.command("migrate-bases")
def migrate_bases(source_database: Path) -> None:
    """Copia banco, CAR e ambientais para a pasta fixa, preservando a origem."""
    if qgis_is_running():
        typer.echo("Feche todas as janelas do QGIS antes de migrar as bases.", err=True)
        raise typer.Exit(code=1)
    paths = install_local_bases(source_database, progress=typer.echo)
    configure_data_paths(paths.database, paths.car)
    typer.echo(f"Bases Plugin disponíveis em: {paths.root}")


@app.command("plugin-build")
def plugin_build(
    variant: Annotated[str, typer.Option()] = "all",
    output_directory: Annotated[Path, typer.Option("--output-directory")] = Path(
        "dist"
    ),
) -> None:
    """Gera os ZIPs instaláveis pelo QGIS."""
    plugin_build_main(
        ["--variant", variant, "--output-directory", str(output_directory)]
    )


@app.command("package-build")
def package_build_cmd(
    dados: Annotated[Path, typer.Option("--dados")],
    variant: Annotated[str, typer.Option()] = "all",
    output_directory: Annotated[Path, typer.Option("--output-directory")] = Path("dist")
    / f"pacote de instalação {PLUGIN_VERSION}",
) -> None:
    """Monta o pacote portátil com banco, 27 UFs e camadas ambientais."""
    variants = ("individual", "massa") if variant == "all" else (variant,)
    for item in variants:
        path = build_package(item, dados, output_directory)
        typer.echo(str(path))


@app.command("update-package")
def update_package_cmd(
    identifier: Annotated[str, typer.Option("--id")],
    version: Annotated[str, typer.Option()],
    strategy: Annotated[str, typer.Option(help=f"Uma de: {', '.join(STRATEGIES)}")],
    payload: Annotated[
        list[str], typer.Option("--payload", help="NOME=CAMINHO; opção repetível")
    ],
    output: Annotated[Path, typer.Option()],
    provides: Annotated[list[str] | None, typer.Option("--provides")] = None,
    payload_scope: Annotated[list[str] | None, typer.Option("--payload-scope")] = None,
    target: Annotated[str | None, typer.Option()] = None,
    foreign_feature_count: Annotated[
        int, typer.Option("--foreign-feature-count", min=0, max=1000)
    ] = 0,
) -> None:
    """Monta um pacote de base; a assinatura do catálogo ocorre externamente."""
    result = build_update_package(
        identifier,
        version,
        strategy,
        _payload_map(payload),
        output,
        target=target,
        provides=tuple(provides or ()) or None,
        payload_scopes=_value_map(payload_scope or [], "--payload-scope"),
        foreign_feature_count=foreign_feature_count,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("base-release")
def base_release_cmd(
    catalog: Annotated[Path, typer.Option()],
    signature: Annotated[Path, typer.Option()],
    package: Annotated[
        list[str], typer.Option("--package", help="ID=CAMINHO; opção repetível")
    ],
    output: Annotated[Path, typer.Option()],
    public_key: Annotated[Path | None, typer.Option("--public-key")] = None,
) -> None:
    """Monta um .carbases offline a partir de catálogo e pacotes assinados."""
    package_paths = _payload_map(package)
    key = (
        public_key.read_text(encoding="ascii")
        if public_key is not None
        else PUBLISHER_PUBLIC_KEY_PEM
    )
    result = build_base_release(
        catalog,
        signature,
        package_paths,
        output,
        key,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("prepare-bases")
def prepare_bases_cmd(
    release: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option()],
    public_key: Annotated[
        Path | None, typer.Option("--public-key", exists=True, dir_okay=False)
    ] = None,
) -> None:
    """Prepara bases prontas no publicador para o pacote com integridade."""
    key = (
        public_key.read_text(encoding="ascii")
        if public_key
        else PUBLISHER_PUBLIC_KEY_PEM
    )
    try:
        manifest = prepare_prebuilt_bases(
            release,
            output,
            key,
            progress=lambda value, message: typer.echo(
                f"{value}% — {message}", err=True
            ),
        )
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {"manifest": str(manifest), "status": "candidate"}, ensure_ascii=False
        )
    )


@app.command("prebuilt-release")
def prebuilt_release_cmd(
    candidate: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    output: Annotated[Path, typer.Option()],
    public_key: Annotated[
        Path | None, typer.Option("--public-key", exists=True, dir_okay=False)
    ] = None,
) -> None:
    """Monta o .carbases pré-montado com manifesto de integridade obrigatório."""
    key = (
        public_key.read_text(encoding="ascii")
        if public_key
        else PUBLISHER_PUBLIC_KEY_PEM
    )
    try:
        result = build_prebuilt_release(candidate, output, key)
    except (ValueError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    app()


def install_entrypoint() -> None:
    import sys

    sys.argv = [sys.argv[0], "install", *sys.argv[1:]]
    app()
