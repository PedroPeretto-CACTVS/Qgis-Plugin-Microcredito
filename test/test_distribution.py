import hashlib
import json
import shutil
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from uuid import uuid4

from installer.package_build import validate_inputs
from installer.plugin_build import build


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(".test-data") / uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_both_variants_contain_current_core_and_matching_hashes(self):
        for supreme, package in (
            (False, "car_microcredito_qgis"),
            (True, "car_microcredito_supremo_qgis"),
        ):
            result = build(supreme, self.root / (package + ".zip"))
            with zipfile.ZipFile(result) as archive:
                manifest = json.loads(archive.read(package + "/manifesto_codigo.json"))
                for name, checksum in manifest.items():
                    content = archive.read(package + "/" + name)
                    self.assertEqual(hashlib.sha256(content).hexdigest(), checksum)
                    if name.endswith(".py"):
                        compile(content, name, "exec")
                        self.assertNotIn(b"from pydantic", content)
                        self.assertNotIn(b"import pydantic", content)
                self.assertTrue(
                    any(name.endswith("domain/policy.py") for name in manifest)
                )
                self.assertIn("worker.py", manifest)
                for required in (
                    "car_document_window.py",
                    "update_window.py",
                    "lib/qgis_plugin_microcredito/domain/base_catalog.py",
                    "lib/qgis_plugin_microcredito/domain/financing.py",
                    "lib/qgis_plugin_microcredito/domain/models.py",
                    "lib/qgis_plugin_microcredito/application/pre_analysis.py",
                    "lib/qgis_plugin_microcredito/infrastructure/updates.py",
                ):
                    self.assertIn(required, manifest)
                self.assertEqual("supreme_mode.txt" in manifest, supreme)
                self.assertIn(b"version=0.9.5", archive.read(package + "/metadata.txt"))

    def test_twenty_seven_duplicate_states_do_not_pass(self):
        for index in range(27):
            folder = self.root / "car" / str(index)
            folder.mkdir(parents=True)
            (folder / "AC_AREA_IMOVEL.gpkg").write_bytes(b"invalid")
        with self.assertRaisesRegex(ValueError, "exatamente uma vez"):
            validate_inputs(self.root)

    def test_qgis_runtime_core_does_not_require_pydantic_or_sqlalchemy(self):
        source = Path(__file__).resolve().parents[1] / "src"
        script = f"""
import importlib.abc
import sys

class BlockExternalRuntimeDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.', 1)[0] in {{'pydantic', 'sqlalchemy'}}:
            raise ModuleNotFoundError(fullname)
        return None

sys.meta_path.insert(0, BlockExternalRuntimeDependencies())
sys.path.insert(0, {str(source)!r})
import database.schema
import database.session
import qgis_plugin_microcredito.application.query_service
import qgis_plugin_microcredito.domain.models
print('runtime-core-ok')
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("runtime-core-ok", result.stdout)
