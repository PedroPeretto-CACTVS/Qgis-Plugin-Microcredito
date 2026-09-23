"""Install the plugin into QGIS profiles (replacement for the PowerShell installer)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from installer.constants import (
    PLUGIN_VERSION,
    QGIS_PROCESS_NAMES,
    SETTINGS_APP,
    SETTINGS_ORG,
)
from installer.verify import verify_package


def qgis_is_running() -> bool:
    if sys.platform == "win32":
        completed = subprocess.run(
            ["tasklist"], capture_output=True, text=True, errors="ignore", check=False
        )
        haystack = completed.stdout.lower()
        return any(name.lower() in haystack for name in QGIS_PROCESS_NAMES)
    completed = subprocess.run(
        ["pgrep", "-af", "qgis"], capture_output=True, text=True, check=False
    )
    return completed.returncode == 0 and bool(completed.stdout.strip())


def default_profiles_root() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise ValueError("APPDATA não definido.")
        return Path(appdata) / "QGIS" / "QGIS3" / "profiles"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "QGIS"
            / "QGIS3"
            / "profiles"
        )
    return Path.home() / ".local" / "share" / "QGIS" / "QGIS3" / "profiles"


def _plugin_source(package_root: Path) -> tuple[Path, str]:
    plugin_root = package_root / "arquivos" / "plugin"
    candidates = [path for path in plugin_root.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        raise ValueError("Pacote deve conter exatamente uma pasta de plugin.")
    return candidates[0], candidates[0].name


def _write_settings(database: Path, car_base: Path) -> None:
    database_value = database.resolve().as_posix()
    car_value = car_base.resolve().as_posix()
    if sys.platform == "win32":
        import winreg

        key = winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"Software\{SETTINGS_ORG}\{SETTINGS_APP}"
        )
        try:
            winreg.SetValueEx(key, "database", 0, winreg.REG_SZ, database_value)
            winreg.SetValueEx(key, "car_base", 0, winreg.REG_SZ, car_value)
        finally:
            winreg.CloseKey(key)
        return
    config_dir = Path.home() / ".config" / SETTINGS_ORG
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{SETTINGS_APP}.conf"
    config_path.write_text(
        f"[General]\ndatabase={database_value}\ncar_base={car_value}\n",
        encoding="utf-8",
    )


def install_package(
    package_root: str | Path,
    *,
    profiles_root: str | Path | None = None,
    skip_settings: bool = False,
    skip_qgis_check: bool = False,
    profile: str | None = None,
) -> list[Path]:
    root = Path(package_root).resolve()
    if not skip_qgis_check and qgis_is_running():
        raise RuntimeError(
            "Feche todas as janelas do QGIS antes de instalar ou atualizar o plugin."
        )
    verify_package(root)
    plugin_source, plugin_folder = _plugin_source(root)
    profiles_dir = Path(profiles_root) if profiles_root else default_profiles_root()
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profiles = [item for item in profiles_dir.iterdir() if item.is_dir()]
    if profile:
        profiles = [profiles_dir / profile]
        profiles[0].mkdir(parents=True, exist_ok=True)
    if not profiles:
        default_profile = profiles_dir / "default"
        default_profile.mkdir(parents=True, exist_ok=True)
        profiles = [default_profile]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    installed: list[Path] = []
    for profile_dir in profiles:
        plugins_directory = (profile_dir / "python" / "plugins").resolve()
        plugins_directory.mkdir(parents=True, exist_ok=True)
        destination = (plugins_directory / plugin_folder).resolve()
        if not str(destination).startswith(str(plugins_directory)):
            raise ValueError(f"Destino de plugin invalido: {destination}")
        backup = Path(str(destination) + "_backup_" + stamp)
        moved = False
        try:
            if destination.exists():
                destination.rename(backup)
                moved = True
            shutil.copytree(plugin_source, destination)
            metadata = (destination / "metadata.txt").read_text(encoding="utf-8")
            if f"version={PLUGIN_VERSION}" not in metadata:
                raise ValueError("Versao instalada divergente")
            installed.append(destination)
        except Exception:
            if destination.exists():
                failed = Path(str(destination) + "_falhou_" + stamp)
                destination.rename(failed)
            if moved and backup.exists():
                backup.rename(destination)
            raise
    if not skip_settings:
        database = root / "arquivos" / "dados" / "car_microcredito.db"
        car_base = root / "arquivos" / "dados" / "car"
        _write_settings(database, car_base)
    for relative in (
        "arquivos/output/pdf",
        "arquivos/output/lotes",
        "arquivos/resultados",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return installed
