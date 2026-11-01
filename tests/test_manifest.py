import json
import os
import unittest
from pathlib import Path

import jsonschema
import wx


ROOT = Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    def test_manifest_matches_installed_kicad_schema(self) -> None:
        default = (
            Path(os.environ["LOCALAPPDATA"])
            / r"Programs\KiCad\10.0\share\kicad\schemas\api.v1.schema.json"
        ) if os.name == "nt" else Path("/usr/share/kicad/schemas/api.v1.schema.json")
        schema_path = Path(os.environ.get("KICAD_API_SCHEMA", str(default)))
        if not schema_path.is_file():
            self.fail("Set KICAD_API_SCHEMA to the installed KiCad API schema.")
        manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft7Validator(schema).validate(manifest)
        self.assertEqual(manifest["runtime"]["type"], "python")
        self.assertEqual(len(manifest["actions"]), 1)
        action = manifest["actions"][0]
        self.assertEqual(action["scopes"], ["pcb"])
        self.assertTrue(action["show-button"])
        self.assertTrue((ROOT / action["entrypoint"]).is_file())
        for key in ("icons-light", "icons-dark"):
            for icon in action[key]:
                self.assertTrue((ROOT / icon).is_file())
                image = wx.Image(str(ROOT / icon), wx.BITMAP_TYPE_PNG)
                self.assertTrue(image.IsOk())
                self.assertEqual((image.Width, image.Height), (32, 32))


if __name__ == "__main__":
    unittest.main()
