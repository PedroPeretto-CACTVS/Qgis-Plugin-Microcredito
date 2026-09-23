import hashlib
import json
import shutil
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
                self.assertTrue(
                    any(name.endswith("domain/policy.py") for name in manifest)
                )
                self.assertIn("worker.py", manifest)
                self.assertEqual("supreme_mode.txt" in manifest, supreme)
                self.assertIn(b"version=0.8.0", archive.read(package + "/metadata.txt"))

    def test_twenty_seven_duplicate_states_do_not_pass(self):
        for index in range(27):
            folder = self.root / "car" / str(index)
            folder.mkdir(parents=True)
            (folder / "AC_AREA_IMOVEL.gpkg").write_bytes(b"invalid")
        with self.assertRaisesRegex(ValueError, "exatamente uma vez"):
            validate_inputs(self.root)
