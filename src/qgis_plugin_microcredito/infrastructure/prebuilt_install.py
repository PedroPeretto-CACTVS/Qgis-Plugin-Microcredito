"""Install complete prebuilt editions without importing their source files."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from qgis_plugin_microcredito.application.prebuilt_data import (
    validate_prebuilt_database,
)
from qgis_plugin_microcredito.infrastructure.base_access import EXTERNAL_UPDATE_PENDING
from qgis_plugin_microcredito.infrastructure.downloads import validate_geopackage
from qgis_plugin_microcredito.infrastructure.prebuilt_release import (
    DATA_FILES,
    PrebuiltReleaseBundle,
)
from qgis_plugin_microcredito.infrastructure.updates import (
    UpdateError,
    UpdateStatus,
    _acquire_update_lock,
    _release_update_lock,
    compare_catalog,
)

INSTALLED_SNAPSHOT = "prebuilt-installed.json"


class PrebuiltInstallError(UpdateError):
    """Report whether a failed transaction left the prior edition untouched."""

    def __init__(self, message: str, *, state_preserved: bool) -> None:
        super().__init__(message)
        self.state_preserved = state_preserved


def compare_prebuilt_release(
    release: PrebuiltReleaseBundle, data_root: Path, database: Path
) -> list[UpdateStatus]:
    """Compare both source editions and the derived snapshot identity."""
    statuses = compare_catalog(release.fetch_catalog(), data_root, database)
    try:
        marker = data_root / ".atualizacoes" / INSTALLED_SNAPSHOT
        installed = json.loads(marker.read_text(encoding="utf-8"))
        if (
            not isinstance(installed, dict)
            or installed.get("schema_version") != 1
            or not re.fullmatch(r"[0-9a-f]{64}", str(installed.get("fingerprint", "")))
        ):
            raise ValueError("Registro de instalação inválido.")
        installed_at = datetime.fromisoformat(installed["issued_at"])
        if installed_at.tzinfo is None:
            raise ValueError("Emissão instalada sem fuso.")
        if datetime.fromisoformat(release.manifest["issued_at"]) < installed_at:
            return [
                replace(
                    status,
                    state="inaplicavel",
                    detail="Pacote pré-montado anterior ao snapshot instalado.",
                )
                for status in statuses
            ]
        current = installed["fingerprint"] == release.fingerprint and all(
            _safe_target(data_root, relative).is_file() for relative in DATA_FILES
        )
    except FileNotFoundError:
        current = False
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise UpdateError(
            "Não foi possível comprovar o registro da instalação pré-montada."
        ) from exc
    if current or any(status.state == "inaplicavel" for status in statuses):
        return statuses
    return [
        replace(
            status,
            state="disponivel",
            detail="O pacote pré-montado será instalado por cópia.",
        )
        for status in statuses
    ]


def _validate_staged_data(root: Path, release: PrebuiltReleaseBundle) -> None:
    validate_prebuilt_database(root / "car_microcredito.db")
    catalog = release.fetch_catalog()
    if any(
        status.state != "atual"
        for status in compare_catalog(catalog, root, root / "car_microcredito.db")
    ):
        raise ValueError("As versões copiadas não correspondem ao pacote pré-montado.")
    for package in catalog.packages:
        if package.strategy != "replace_file" or package.target is None:
            continue
        uf = (
            package.identifier.removeprefix("sicar_imoveis_").upper()
            if package.identifier.startswith("sicar_imoveis_")
            else None
        )
        validate_geopackage(
            root / package.target,
            uf,
            expected_foreign_features=package.foreign_feature_count,
        )
    if any(
        (root / name).exists()
        for name in (
            "car_microcredito.db-wal",
            "car_microcredito.db-shm",
            "car_microcredito.db-journal",
        )
    ):
        raise ValueError("O banco pré-montado depende de arquivos auxiliares.")


def _safe_target(root: Path, relative: str) -> Path:
    target = root / relative
    for path in (target, *target.parents):
        if path.is_symlink() or path.is_junction():
            raise ValueError("A pasta de instalação não pode usar links ou junções.")
        if path == root:
            break
    return target


def apply_prebuilt_release(
    release: PrebuiltReleaseBundle,
    data_root: Path,
    database: Path,
    *,
    progress: Callable[[int, str], None] | None = None,
) -> list[UpdateStatus]:
    """Copy and promote a complete edition under the external worker's marker.

    The root and its open lock files stay in place. Reversible renames implement
    transaction rollback only; no user-facing full-restore feature is created.
    """
    root = data_root.resolve()
    if database.resolve() != root / "car_microcredito.db":
        raise PrebuiltInstallError(
            "Destino do banco pré-montado incompatível.", state_preserved=True
        )
    pending = root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING
    try:
        document = json.loads(pending.read_text(encoding="utf-8"))
        if (
            not isinstance(document, dict)
            or document.get("pid") != os.getpid()
            or document.get("command") != "apply"
        ):
            raise ValueError("Operação externa inválida.")
    except (OSError, ValueError) as exc:
        raise PrebuiltInstallError(
            "Inicie a instalação pelo atualizador externo.", state_preserved=True
        ) from exc
    lock = _acquire_update_lock(root)
    stage: Path | None = None
    cleanup = True
    moved: list[tuple[Path, Path]] = []
    promoted: list[tuple[Path, Path]] = []
    try:
        statuses = compare_prebuilt_release(release, root, database)
        if any(status.state == "inaplicavel" for status in statuses):
            raise ValueError(
                "O pacote pré-montado é incompatível ou anterior à edição instalada."
            )
        if all(status.state == "atual" for status in statuses):
            return []
        staging_parent = _safe_target(root, ".u")
        staging_parent.mkdir(exist_ok=True)
        required = sum(
            entry["size_bytes"] for entry in release.manifest["files"].values()
        )
        if shutil.disk_usage(root).free < required + 64 * 1024 * 1024:
            raise ValueError("Espaço livre insuficiente para copiar as bases prontas.")
        stage = Path(tempfile.mkdtemp(prefix=".p-", dir=staging_parent))
        new = stage / "new"
        old = stage / "old"
        old.mkdir()
        release.extract_data(
            new,
            progress=(lambda value, message: progress(int(value * 0.8), message))
            if progress
            else None,
        )
        if progress:
            progress(85, "Conferindo o conjunto copiado antes da ativação…")
        _validate_staged_data(new, release)
        metadata = new / ".atualizacoes" / INSTALLED_SNAPSHOT
        metadata.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "fingerprint": release.fingerprint,
                    "issued_at": release.manifest["issued_at"],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        components = [
            "car",
            "ambientais",
            ".atualizacoes/estado.json",
            f".atualizacoes/{INSTALLED_SNAPSHOT}",
            database.name,
        ]
        retire = [
            ".h",
            *(database.name + suffix for suffix in ("-wal", "-shm", "-journal")),
        ]
        for relative in [*retire, *components]:
            target = _safe_target(root, relative)
            if target.exists():
                backup = old / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.rename(backup)
                moved.append((backup, target))
            if relative in components:
                source = new / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
                promoted.append((target, source))
        if progress:
            progress(100, "Bases pré-montadas instaladas por cópia.")
        return compare_catalog(release.fetch_catalog(), root, database)
    except Exception as exc:
        try:
            for target, original in reversed(promoted):
                original.parent.mkdir(parents=True, exist_ok=True)
                target.rename(original)
            for backup, target in reversed(moved):
                backup.rename(target)
        except OSError as rollback_exc:
            cleanup = False
            raise PrebuiltInstallError(
                "A instalação foi interrompida e requer verificação técnica. As consultas continuam bloqueadas.",
                state_preserved=False,
            ) from rollback_exc
        raise PrebuiltInstallError(
            f"A instalação por cópia não foi aplicada; o estado anterior foi preservado. Motivo: {exc}",
            state_preserved=True,
        ) from exc
    finally:
        try:
            if stage is not None and cleanup:
                shutil.rmtree(stage)
        finally:
            _release_update_lock(lock)
