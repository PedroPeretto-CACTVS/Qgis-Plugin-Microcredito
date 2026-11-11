"""Run synthetic acceptance suites with one isolated native QGIS application.

Invoke through the QGIS Python launcher with ``-s -B``. Each execution requires
an output directory outside the source tree and keeps its own profile, settings,
authentication database, working directory, temporary files and test fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PRODUCT_PREFIXES = ("plugin", "installer", "database", "qgis_plugin_microcredito")
SUITES = {
    "base-release": (
        "test/test_base_release_bundle.py",
        "test/test_updates.py",
    ),
    "external": (
        "test/qgis/test_external_update.py",
        "test/qgis/test_prebuilt_copy_window.py",
        "test/test_update_process.py",
        "test/test_prebuilt_update_process.py",
    ),
    "fixed-root": (
        "test/qgis/test_qgis_regressions.py",
        "test/qgis/test_installed_fixed_bases.py",
        "test/qgis/test_batch_file_validation.py",
        "test/qgis/test_base_access_qgis.py",
        "test/qgis/test_fixed_base_paths.py",
        "test/qgis/test_prebuilt_copy_window.py",
    ),
}


def require(condition: bool, diagnostic: str) -> None:
    if not condition:
        raise RuntimeError(diagnostic)


def write_new(run: Path, name: str, value: object) -> None:
    path = run / name
    require(path.resolve().parent == run, "evidence_path_escaped")
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, ensure_ascii=False)
        output.write("\n")


def source_fingerprint(source: Path) -> dict[str, str]:
    files = [source / "AGENTS.md", source / "pyproject.toml"]
    for directory in ("src", "test", "tools"):
        files.extend(sorted((source / directory).rglob("*.py")))
        files.extend(sorted((source / directory).rglob("*.ps1")))
    result = {}
    for path in files:
        require(path.resolve().is_relative_to(source), "source_path_escaped")
        require(not path.is_symlink() and not path.is_junction(), "source_reparse")
        result[path.relative_to(source).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return result


def product_origins(source: Path) -> dict[str, str]:
    result = {}
    for name, module in tuple(sys.modules.items()):
        if any(
            name == root or name.startswith(root + ".") for root in PRODUCT_PREFIXES
        ):
            filename = getattr(module, "__file__", None)
            if filename:
                path = Path(filename).resolve()
                require(
                    path.is_relative_to(source / "src"), "product_import_outside_source"
                )
                result[name] = str(path)
    require("plugin.plugin" in result, "actual_plugin_not_imported")
    return result


def qgis_distribution_root() -> Path:
    executable = Path(sys.executable).resolve()
    configured = os.environ.get("OSGEO4W_ROOT")
    candidates = (
        [Path(configured).resolve()] if configured else list(executable.parents)
    )
    for root in candidates:
        if executable.is_relative_to(root) and any(
            (root / "apps" / name / "python" / "qgis").is_dir()
            for name in ("qgis", "qgis-ltr")
        ):
            return root
    raise RuntimeError("native_QGIS_python_required")


def native_dependency_boundary(
    qgis_root: Path, qa_support: Path | None
) -> dict[str, object]:
    # Preload product dependencies from QGIS before optional test-only imports.
    if qa_support is not None:
        sys.path[:] = [
            entry
            for entry in sys.path
            if not Path(entry or os.getcwd()).resolve().is_relative_to(qa_support)
        ]
        inherited = os.environ.get("PYTHONPATH", "")
        retained = [
            entry
            for entry in inherited.split(os.pathsep)
            if entry and not Path(entry).resolve().is_relative_to(qa_support)
        ]
        if retained:
            os.environ["PYTHONPATH"] = os.pathsep.join(retained)
        else:
            os.environ.pop("PYTHONPATH", None)
    for name, module in tuple(sys.modules.items()):
        if (
            name == "reportlab"
            or name.startswith("reportlab.")
            or name == "PIL"
            or name.startswith("PIL.")
        ):
            origin = getattr(module, "__file__", None)
            require(
                origin is not None and Path(origin).resolve().is_relative_to(qgis_root),
                "cached_product_dependency_outside_QGIS",
            )
    dependencies = {}
    for name, attribute in (("reportlab", "Version"), ("PIL", "__version__")):
        spec = importlib.util.find_spec(name)
        require(
            spec is not None
            and spec.origin is not None
            and Path(spec.origin).resolve().is_relative_to(qgis_root),
            "native_product_dependency_unavailable_" + name,
        )
        module = importlib.import_module(name)
        origin = Path(module.__file__).resolve()
        require(origin.is_relative_to(qgis_root), "product_dependency_outside_QGIS")
        dependencies[name] = {
            "version": str(getattr(module, attribute)),
            "origin": str(origin),
            "module_sha256": hashlib.sha256(origin.read_bytes()).hexdigest(),
        }
    if qa_support is not None:
        sys.path.append(str(qa_support))
    return {
        "qgis_distribution_root": str(qgis_root),
        "native_product_dependencies": dependencies,
        "qa_support": str(qa_support) if qa_support is not None else None,
        "qa_support_last": qa_support is None
        or Path(sys.path[-1]).resolve() == qa_support,
        "child_pythonpath": os.environ.get("PYTHONPATH"),
    }


def canonical_native_python() -> Path | None:
    """Use the distribution interpreter whose isolated children find the stdlib."""
    executable = Path(sys.executable).resolve()
    candidate = (Path(sys.prefix) / "python.exe").resolve()
    if not candidate.is_file() or candidate == executable:
        return None
    require(
        candidate.is_relative_to(qgis_distribution_root()), "native_python_outside_QGIS"
    )
    return candidate


def execute_smoke(scope: str, source: Path, run: Path, qa_support: Path | None) -> int:
    require(
        sys.flags.no_user_site and sys.dont_write_bytecode,
        "invoke_native_python_with_s_B",
    )
    require(
        not any(
            name == "qgis" or name.startswith(("qgis.", "PyQt5.", "PySide"))
            for name in sys.modules
        ),
        "Qt_imported_before_isolation",
    )
    require(
        not any(
            name == root or name.startswith(root + ".")
            for root in PRODUCT_PREFIXES
            for name in sys.modules
        ),
        "product_imported_before_isolation",
    )
    locations = {
        name: run / name
        for name in (
            "profile",
            "local",
            "roaming",
            "temporary",
            "gdal-pam",
            "qt-user",
            "qt-system",
            "work",
        )
    }
    for location in locations.values():
        location.mkdir()
    profile = locations["profile"]
    os.environ["LOCALAPPDATA"] = str(locations["local"])
    os.environ["APPDATA"] = str(locations["roaming"])
    for key in ("TEMP", "TMP", "TMPDIR", "CAR_MICROCREDITO_TEMP_DIR"):
        os.environ[key] = str(locations["temporary"])
    os.environ["GDAL_PAM_PROXY_DIR"] = str(locations["gdal-pam"])
    os.environ["QGIS_CUSTOM_CONFIG_PATH"] = str(profile)
    os.environ["QGIS_AUTH_DB_DIR_PATH"] = str(profile)
    os.environ.pop("QGIS_AUTH_DB_URI", None)
    os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PROJ_NETWORK"] = "OFF"
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.path[:0] = [str(source / "src"), str(source)]
    os.chdir(locations["work"])
    tempfile.tempdir = None
    require(
        Path(tempfile.gettempdir()).resolve() == locations["temporary"],
        "python_temp_escaped",
    )
    qgis_root = qgis_distribution_root()
    boundary = native_dependency_boundary(qgis_root, qa_support)
    write_new(run, "native-dependency-boundary.before.json", boundary)

    import pytest
    from qgis.core import Qgis, QgsApplication, QgsProject, QgsSettings
    from qgis.PyQt.QtCore import QDir, QSettings
    from qgis.PyQt.QtGui import QFont, QFontDatabase

    require(
        Path(importlib.import_module("qgis").__file__)
        .resolve()
        .is_relative_to(qgis_root),
        "qgis_import_outside_native_root",
    )
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(
        QSettings.IniFormat, QSettings.UserScope, str(locations["qt-user"])
    )
    QSettings.setPath(
        QSettings.IniFormat, QSettings.SystemScope, str(locations["qt-system"])
    )
    app = None
    try:
        app = QgsApplication([], False, str(profile), "desktop")
        require(QgsApplication.platform() == "desktop", "desktop_profile_mode_required")
        before_profile = QgsApplication.qgisSettingsDirPath()
        require(
            not before_profile
            or Path(before_profile).resolve().is_relative_to(profile),
            "profile_escaped_before_init",
        )
        require(
            Path(QSettings().fileName()).resolve().is_relative_to(run),
            "Qt_settings_escaped_before_init",
        )
        require(
            Path(QgsSettings().fileName()).resolve().is_relative_to(run),
            "QGIS_settings_escaped_before_init",
        )
        app.initQgis()
        actual_profile = Path(QgsApplication.qgisSettingsDirPath()).resolve()
        qt_settings = Path(QSettings().fileName()).resolve()
        qgis_settings = Path(QgsSettings().fileName()).resolve()
        auth_path = Path(
            QgsApplication.authManager().authenticationDatabasePath()
        ).resolve()
        require(actual_profile == profile, "explicit_QGIS_profile_not_retained")
        require(
            qt_settings.is_relative_to(run) and qgis_settings.is_relative_to(run),
            "settings_escaped_after_init",
        )
        require(
            auth_path.is_relative_to(profile), "authentication_database_escaped_profile"
        )
        require(
            Path(QDir.tempPath()).resolve() == locations["temporary"], "Qt_temp_escaped"
        )
        if not QFontDatabase().families():
            font = Path(os.environ["WINDIR"]) / "Fonts" / "arial.ttf"
            font_id = QFontDatabase.addApplicationFont(str(font))
            require(font_id >= 0, "offscreen_font_unavailable")
            app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
        for name in (
            "plugin.plugin",
            "installer.install",
            "installer.local_bases",
            "database.repositories",
            "qgis_plugin_microcredito.application.local_data_paths",
        ):
            importlib.import_module(name)
        before_origins = product_origins(source)
        before_source = source_fingerprint(source)
        arguments = [
            "-c",
            str(source / "pyproject.toml"),
            "--rootdir",
            str(source),
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "-q",
            *[str(source / relative) for relative in SUITES[scope]],
            "--junitxml",
            str(run / "pytest-qgis.xml"),
            "--basetemp",
            str(run / "pytest-tmp"),
        ]
        write_new(
            run,
            "qgis-isolation.json",
            {
                "scope": scope,
                "source": str(source),
                "run": str(run),
                "qgis_version": Qgis.QGIS_VERSION,
                "python": sys.version,
                "python_executable": sys.executable,
                "qgis_profile": str(actual_profile),
                "qt_settings": str(qt_settings),
                "qgis_settings": str(qgis_settings),
                "auth_database": str(auth_path),
                "temporary": str(locations["temporary"]),
                "working_directory": str(locations["work"]),
                "constructor_platform": "desktop",
                "module_origins_before": before_origins,
                "pytest_origin": str(Path(pytest.__file__).resolve()),
                "pytest_version": pytest.__version__,
                "test_targets": list(SUITES[scope]),
                "pytest_arguments": arguments,
                "synthetic_fixtures_only": True,
            },
        )
        write_new(run, "source-fingerprint.before.json", before_source)
        exit_code = int(pytest.main(arguments))
        after_origins = product_origins(source)
        require(
            source_fingerprint(source) == before_source,
            "test_execution_modified_source",
        )
        require(
            Path(QgsApplication.qgisSettingsDirPath()).resolve() == profile,
            "profile_changed_during_tests",
        )
        require(
            Path(QSettings().fileName()).resolve().is_relative_to(run),
            "Qt_settings_changed_during_tests",
        )
        require(
            Path(QgsSettings().fileName()).resolve().is_relative_to(run),
            "QGIS_settings_changed_during_tests",
        )
        require(
            Path(QgsApplication.authManager().authenticationDatabasePath())
            .resolve()
            .is_relative_to(profile),
            "auth_database_changed_during_tests",
        )
        after_boundary = native_dependency_boundary(qgis_root, qa_support)
        require(
            after_boundary["native_product_dependencies"]
            == boundary["native_product_dependencies"],
            "native_product_dependency_changed",
        )
        write_new(run, "native-dependency-boundary.after.json", after_boundary)
        cases = ET.parse(run / "pytest-qgis.xml").findall(".//testcase")
        require(bool(cases), "acceptance_tests_not_collected")
        require(
            not any(case.find("skipped") is not None for case in cases),
            "acceptance_tests_skipped",
        )
    finally:
        if app is not None:
            QgsProject.instance().removeAllMapLayers()
            app.exitQgis()
    require(
        source_fingerprint(source) == before_source, "QGIS_shutdown_modified_source"
    )
    result = {
        "status": "passed" if exit_code == 0 else "failed",
        "scope": scope,
        "source": str(source),
        "run": str(run),
        "pytest_exit_code": exit_code,
        "test_cases": len(cases),
        "source_unchanged": True,
        "module_origins_after": after_origins,
        "profile_and_auth_still_isolated": True,
        "native_product_dependencies_preserved": True,
        "QGIS_shutdown_completed": True,
        "test_targets": list(SUITES[scope]),
    }
    write_new(run, "runner-result.json", result)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("status", "scope", "run", "pytest_exit_code", "test_cases")
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return exit_code


def main(scope: str) -> int:
    """Validate CLI paths before importing Qt and run one synthetic suite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--run-id", help="Fresh directory name; generated when omitted."
    )
    parser.add_argument(
        "--qa-support",
        type=Path,
        help="Optional test dependencies, appended after native libraries.",
    )
    args = parser.parse_args()
    source = args.source_root.expanduser().resolve()
    output = args.output_root.expanduser().resolve()
    run_id = (
        args.run_id or f"{scope}-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
    )
    run = output / run_id
    qa_support = (
        args.qa_support.expanduser().resolve() if args.qa_support is not None else None
    )
    try:
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", run_id)), "unsafe_run_id")
        require(not output.is_relative_to(source), "output_inside_source_tree")
        require(run.resolve().parent == output, "run_path_escaped")
        require(
            not run.exists() and not run.is_symlink() and not run.is_junction(),
            "fresh_run_directory_required",
        )
        require(
            (source / "pyproject.toml").is_file() and (source / "src").is_dir(),
            "source_repository_missing",
        )
        require(scope in SUITES, "unknown_smoke_scope")
        require(
            all((source / relative).is_file() for relative in SUITES[scope]),
            "acceptance_test_file_missing",
        )
        if qa_support is not None:
            require(
                qa_support.is_dir()
                and not qa_support.is_symlink()
                and not qa_support.is_junction(),
                "qa_support_directory_invalid",
            )
    except RuntimeError as error:
        parser.error(str(error))
    try:
        interpreter = canonical_native_python()
    except RuntimeError as error:
        parser.error(str(error))
    if interpreter is not None:
        return subprocess.run(
            [
                str(interpreter),
                "-s",
                "-B",
                str(Path(sys.argv[0]).resolve()),
                *sys.argv[1:],
            ],
            check=False,
        ).returncode
    try:
        run.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error("fresh_run_directory_required")
    try:
        return execute_smoke(scope, source, run, qa_support)
    except Exception as error:
        result = {
            "status": "failed",
            "scope": scope,
            "diagnostic": str(error),
            "type": type(error).__name__,
        }
        if run.is_dir():
            write_new(run, "runner-failure.json", result)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr, flush=True)
        return 1
