import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import jsonschema
import importlib.resources


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SCRIPT = ROOT / "tools" / "package.py"


class PackageTests(unittest.TestCase):
    def test_builds_schema_valid_pcm_metadata_and_runtime_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            command = [
                sys.executable, str(PACKAGE_SCRIPT),
                "--version", "1.2.3",
                "--author", "Test Author",
                "--license", "LicenseRef-Test",
                "--project-url", "https://example.invalid/project",
                "--download-url", "https://example.invalid/kicad2cnc-1.2.3.zip",
                "--output-directory", str(output),
            ]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

            archive_path = output / "kicad2cnc-1.2.3.zip"
            metadata_path = output / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            schema_path = importlib.resources.files("kipy").joinpath(
                "packaging", "schemas", "pcm.v2.schema.json"
            )
            jsonschema.Draft7Validator(
                json.loads(schema_path.read_text(encoding="utf-8"))
            ).validate(metadata)
            version = metadata["versions"][0]
            archive_bytes = archive_path.read_bytes()
            self.assertEqual(version["download_sha256"], hashlib.sha256(archive_bytes).hexdigest())
            self.assertEqual(version["download_size"], len(archive_bytes))
            self.assertEqual(version["runtime"], "ipc")
            self.assertEqual(version["kicad_version"], "10.0")
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
            self.assertIn("plugin.json", names)
            self.assertIn("launch.py", names)
            self.assertIn("kicad2cnc/post_grbl.py", names)
            self.assertNotIn("tests/test_post_grbl.py", names)

    def test_refuses_to_overwrite_existing_release_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive = output / "kicad2cnc-1.2.3.zip"
            archive.write_bytes(b"keep")
            result = subprocess.run(
                [
                    sys.executable, str(PACKAGE_SCRIPT),
                    "--version", "1.2.3",
                    "--author", "Test Author",
                    "--license", "LicenseRef-Test",
                    "--project-url", "https://example.invalid/project",
                    "--download-url", "https://example.invalid/kicad2cnc-1.2.3.zip",
                    "--output-directory", str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(archive.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
