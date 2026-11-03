"""Provision fixed local storage from one validated, closed data installation."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from database.session import connect
from installer.constants import UFS
from installer.package_build import validate_sources
from installer.verify import file_sha256
from qgis_plugin_microcredito.application.backup_service import snapshot_database
from qgis_plugin_microcredito.application.local_data_paths import (
    LocalDataPaths,
    default_local_data_paths,
)
from qgis_plugin_microcredito.infrastructure.downloads import (
    geopackage_foreign_feature_count,
    validate_geopackage,
)
from qgis_plugin_microcredito.infrastructure.updates import (
    _acquire_update_lock,
    _release_update_lock,
    list_restore_points,
    update_lock_path,
)


def _require_empty_destination(root: Path) -> None:
    """Allow only the inert lock scaffold left by an earlier update attempt."""
    lock = update_lock_path(root)
    if root.exists() and any(
        path.resolve() not in {lock.parent, lock} or path.is_symlink()
        for path in root.rglob("*")
    ):
        raise ValueError(
            "A pasta fixa contém uma instalação incompleta. Nenhum arquivo foi "
            "substituído; conclua a instalação pelo Bases Plugin."
        )


def _activate_staged_bases(staging: Path, paths: LocalDataPaths) -> None:
    lock = _acquire_update_lock(paths.root)
    promoted: list[tuple[Path, Path]] = []
    try:
        if paths.database.is_file():
            validate_sources(paths.root)
            return
        _require_empty_destination(paths.root)
        # Keep the lock file in place and promote the database last, so another
        # installer cannot mistake an incomplete promotion for installed bases.
        for source in sorted(
            staging.iterdir(), key=lambda path: path.name == paths.database.name
        ):
            members = (
                list(source.iterdir()) if source.name == ".atualizacoes" else [source]
            )
            for member in members:
                target = paths.root / member.relative_to(staging)
                if target.exists():
                    raise ValueError(
                        f"Destino já existe; nenhuma substituição: {target}"
                    )
                member.rename(target)
                promoted.append((member, target))
    except Exception:
        for original, target in reversed(promoted):
            target.rename(original)
        raise
    finally:
        _release_update_lock(lock)


def install_local_bases(
    source_database: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> LocalDataPaths:
    """Copy a coherent data set into fixed storage; never overwrite active bases.

    The caller must close QGIS before provisioning. Only data directories and
    their restoration history are copied, leaving packages and reports behind.
    """
    paths = default_local_data_paths()
    if paths.database.is_file():
        validate_sources(paths.root)
        return paths
    _require_empty_destination(paths.root)
    source = source_database.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    with closing(connect(source, readonly=True)):
        pass
    files = [
        path
        for folder in ("car", "ambientais", ".h")
        for path in (source.parent / folder).rglob("*")
        if path.is_file()
    ]
    registry = source.parent / ".atualizacoes" / "estado.json"
    if registry.is_file():
        files.append(registry)
    paths.root.parent.mkdir(parents=True, exist_ok=True)
    required = source.stat().st_size + sum(path.stat().st_size for path in files)
    if shutil.disk_usage(paths.root.parent).free < required + 64 * 1024 * 1024:
        raise ValueError(
            "Espaço livre insuficiente para copiar as bases com segurança."
        )
    with tempfile.TemporaryDirectory(
        prefix=".bases-", dir=paths.root.parent
    ) as directory:
        staging = Path(directory) / "dados"
        staging.mkdir()
        if progress:
            progress("Copiando e verificando o banco SQLite…")
        snapshot_database(source, staging / "car_microcredito.db")
        for index, path in enumerate(files, 1):
            relative = path.relative_to(source.parent)
            if progress:
                progress(
                    f"Copiando bases e histórico: {index}/{len(files)} — {relative}"
                )
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if file_sha256(path) != file_sha256(target):
                raise ValueError(f"Cópia divergente: {relative}")
        if source.name != paths.database.name:
            for point in list_restore_points(source.parent, source):
                if point.legacy:
                    backup = staging / ".h" / point.restore_id / source.name
                    renamed = backup.with_name(paths.database.name)
                    if renamed.exists():
                        raise ValueError(
                            "O histórico legado contém nomes de banco conflitantes. "
                            "Nenhuma base foi ativada."
                        )
                    backup.rename(renamed)
        validate_sources(staging)
        for folder in ("car", "ambientais"):
            for gpkg in (staging / folder).rglob("*.gpkg"):
                if folder == "car" and gpkg.parent.name in UFS:
                    # Inspect CAR fields without reapplying publication UF quotas.
                    geopackage_foreign_feature_count(gpkg, gpkg.parent.name)
                else:
                    validate_geopackage(gpkg)
        _activate_staged_bases(staging, paths)
    if progress:
        progress("Bases validadas e ativadas na pasta fixa.")
    return paths
