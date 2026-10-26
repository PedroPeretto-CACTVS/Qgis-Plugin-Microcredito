"""Coordinate a complete consultation with atomic base replacement."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import local

from qgis_plugin_microcredito.infrastructure.updates import (
    UpdateError,
    _acquire_update_lock,
    _release_update_lock,
    _UpdateLockBusy,
)

EXTERNAL_UPDATE_PENDING = "external-update-pending.json"


class BaseAccessBusy(UpdateError):
    """The base edition cannot currently be safely read."""


def _check_pending_update(root: Path) -> None:
    if (root / ".atualizacoes" / EXTERNAL_UPDATE_PENDING).exists():
        raise BaseAccessBusy(
            "Há uma atualização de bases em andamento ou pendente de verificação. "
            "Abra ‘Bases de consulta e atualizações’ e aguarde a conclusão. "
            "Se o processo foi interrompido, não remova o aviso nem use as bases "
            "antes de concluir a recuperação."
        )


class _ReadAccessState(local):
    def __init__(self) -> None:
        self.roots: set[Path] = set()


_read_access = _ReadAccessState()


@contextmanager
def read_base_access(data_root: str | Path) -> Iterator[None]:
    """Keep the current edition stable until a consultation has finished."""
    root = Path(data_root).resolve()
    if root in _read_access.roots:
        yield
        return
    if not root.is_dir():
        raise BaseAccessBusy(
            "As bases locais ainda não foram instaladas. "
            "Abra ‘Bases de consulta e atualizações’ e aplique um Bases Plugin."
        )
    _check_pending_update(root)
    try:
        lock = _acquire_update_lock(root, record_timestamp=False)
    except _UpdateLockBusy as exc:
        raise BaseAccessBusy(
            "As bases estão em uso por outra consulta, atualização ou restauração. "
            "Aguarde a conclusão e tente novamente."
        ) from exc
    except UpdateError as exc:
        raise BaseAccessBusy(str(exc)) from exc
    try:
        _check_pending_update(root)
        _read_access.roots.add(root)
        try:
            yield
        finally:
            _read_access.roots.remove(root)
    finally:
        _release_update_lock(lock)
