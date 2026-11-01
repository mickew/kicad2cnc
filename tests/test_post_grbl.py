import re
import tempfile
import unittest
from pathlib import Path

from kicad2cnc.export import ExportError
from kicad2cnc.post_grbl import _grbl_line, _tool_blocks, postprocess_gcode
from kicad2cnc.settings import CncSettings


class GrblPostprocessorTests(unittest.TestCase):
    def write_toolpath(self, root: Path, relative: str, text: str) -> Path:
        source = root / "cam" / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8")
        return source

    def test_splits_tools_orders_files_and_writes_grbl_safe_programs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "gcode"
            self.write_toolpath(
                root,
                r"routing\front.ngc",
                """T1
(MSG, Change tool bit to mill diameter 0.2mm)
M6 (Tool change.)
M0 (Pause for tool change.)
G21
G90
G00 S10000
G00 Z3
G01 X1 Y2 Z-0.05 F120
G04 P1
M5
T2
(MSG, Change tool bit to mill diameter 0.4mm)
M6
M0
G00 Z3
G01 X2 Y3 Z-0.05 F120
""",
            )
            self.write_toolpath(
                root,
                r"drill-1-board-PTH\drill.ngc",
                """T0
(MSG, Change tool bit to drill size 0.8mm)
M6
M0
G00 Z3
G01 X5 Y6 Z-1 F80
""",
            )
            files = postprocess_gcode(
                root, CncSettings(spinup_time=2.0, spindown_time=3.0)
            )
            self.assertEqual(
                [path.name for path in files],
                [
                    "01-drill-pth-0p8mm.nc",
                    "02-isolation-front-0p2mm.nc",
                    "03-isolation-front-0p4mm.nc",
                ],
            )
            for path in files:
                text = path.read_text(encoding="ascii")
                code = re.sub(r"\([^)]*\)", "", text)
                self.assertNotRegex(code, r"\b(?:M0?6|T\d+)\b")
                self.assertNotRegex(code, r"\bM0\b")
                self.assertIn("G21\n", code)
                self.assertIn("G90\n", code)
                self.assertIn("M3 S10000", code)
                self.assertIn("M5\nM9\nG4 P3\nM30", code)
                self.assertTrue(code.rstrip().endswith("M30"))
                self.assertIn("G0 Z10.000", code)
            self.assertIn("G4 P2", files[0].read_text(encoding="ascii"))
            self.assertNotIn("G4 P1", files[1].read_text(encoding="ascii"))
            readme = (root / "grbl" / "README_job.txt").read_text(encoding="utf-8")
            self.assertIn("Change tools manually", readme)
            self.assertIn("No registration holes are generated. Double-sided alignment is manual.", readme)
            self.assertIn("01-drill-pth-0p8mm.nc", readme)

    def test_source_dwells_are_replaced_by_configured_spindle_dwells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "gcode"
            source = self.write_toolpath(
                root,
                r"routing\front.ngc",
                """T0
(MSG, Change tool bit to mill diameter 0.2mm)
M6
G04 P1
G01 X1 Y2 Z-0.05 F120
""",
            )
            settings = CncSettings(spinup_time=2.5, spindown_time=3.5)
            (output,) = postprocess_gcode(root, settings)
            text = output.read_text(encoding="ascii")
            self.assertIn("M3 S10000\nG4 P2.5", text)
            self.assertIn("M5\nM9\nG4 P3.5\nM30", text)
            self.assertEqual(text.count("G4 P"), 2)

    def test_missing_tool_diameter_or_tool_change_fails_explicitly(self) -> None:
        for text, error in (
            ("T1\nM6\nG1 X1\n", "diameter"),
            ("T1\n(MSG, Change tool bit to drill size 0.8mm)\nG1 X1\n", "M6"),
        ):
            with tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "drill.ngc"
                source.write_text(text, encoding="utf-8")
                with self.subTest(error=error), self.assertRaisesRegex(ExportError, error):
                    _tool_blocks(source)

    def test_unsupported_codes_and_conflicting_modes_fail_closed(self) -> None:
        for line, error in (
            ("G20", "Conflicting coordinate mode"),
            ("G91", "Conflicting coordinate mode"),
            ("G18", "Conflicting coordinate mode"),
            ("M7", "Unsupported or unsafe"),
            ("Q1", "Unsupported G-code word"),
            ("S12000", "does not match configured"),
            ("T2", "Unexpected tool selection"),
        ):
            with self.subTest(line=line), self.assertRaisesRegex(ExportError, error):
                _grbl_line(line, 10000, Path("tool.ngc"))

    def test_x_reflection_reverses_arc_direction_and_negates_center_offset(self) -> None:
        self.assertEqual(
            _grbl_line(
                "G2 X1.250 Y-2 I0.625 J0.0 F100",
                10000,
                Path("outline.ngc"),
                mirror_x=True,
            ),
            "G3 X-1.250 Y-2 I-0.625 J0.0 F100",
        )
        self.assertEqual(
            _grbl_line(
                "G3 X-1 Y2 I-0.5 J0 F100",
                10000,
                Path("outline.ngc"),
                mirror_x=True,
            ),
            "G2 X1 Y2 I0.5 J0 F100",
        )

    def test_front_isolation_output_matches_golden_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "gcode"
            self.write_toolpath(
                root,
                "routing/front.ngc",
                """T1
(MSG, Change tool bit to mill diameter 0.2mm)
M6
M0
G21
G90
G00 S10000
G00 Z3
G01 X1 Y2 Z-0.05 F120
G04 P1
M5
""",
            )
            (output,) = postprocess_gcode(
                root, CncSettings(spinup_time=2.0, spindown_time=3.0)
            )
            expected = Path(__file__).parent / "golden" / "grbl-isolation-front.nc"
            self.assertEqual(output.read_bytes(), expected.read_bytes())

    def test_combined_drilling_merges_tools_and_rejects_wrong_diameter(self) -> None:
        for diameter in (0.6, 0.8):
            with self.subTest(diameter=diameter), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "gcode"
                for index in (1, 2):
                    self.write_toolpath(
                        root, f"drill-combined-{index}\\drill.ngc",
                        f"""T1
(MSG, Change tool bit to drill size {diameter}mm)
M6
G00 Z3
G00 X{index} Y2
G01 Z-1.8 F80
G00 Z3
M2
""",
                    )
                settings = CncSettings(combined_drilling=True, combined_drill_diameter=0.6)
                if diameter != 0.6:
                    with self.assertRaisesRegex(ExportError, "do not match"):
                        postprocess_gcode(root, settings)
                    continue
                (output,) = postprocess_gcode(root, settings)
                text = output.read_text(encoding="ascii")
                self.assertIn("G0 X1 Y2", text)
                self.assertIn("G0 X2 Y2", text)
                self.assertEqual(text.count("G1 Z-1.8 F80"), 2)
                self.assertEqual(output.name, "01-drill-all-one-size-0p6mm.nc")

    def test_back_only_outline_output_matches_golden_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "gcode"
            self.write_toolpath(
                root,
                "routing/outline.ngc",
                """T1
(MSG, Change tool bit to cutter diameter 1mm)
M6
G00 X1 Y2
G02 X3 Y4 I1 J0 F100
""",
            )
            (output,) = postprocess_gcode(
                root, CncSettings(), mirror_non_copper_x=True
            )
            expected = Path(__file__).parent / "golden" / "grbl-back-only-outline.nc"
            self.assertEqual(output.read_bytes(), expected.read_bytes())


if __name__ == "__main__":
    unittest.main()
