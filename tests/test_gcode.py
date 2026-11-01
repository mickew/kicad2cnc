import os
import re
import subprocess
import tempfile
import unittest
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest.mock import MagicMock, patch

from kicad2cnc.export import ExportError, export_board
from kicad2cnc.gcode import generate_gcode, layer_file
from kicad2cnc.settings import CncSettings, find_converter


ROOT = Path(__file__).resolve().parents[1]


class GcodeTests(unittest.TestCase):
    def test_converter_failure_and_timeout_are_reported(self) -> None:
        for failure in ("exit", "timeout"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                executable = root / "converter.exe"
                executable.touch()
                process = MagicMock()
                process.stdout = iter(["Converter diagnostic\n"])
                process.returncode = 7
                if failure == "timeout":
                    process.wait.side_effect = [subprocess.TimeoutExpired("converter", 15), 0]
                process.__enter__.return_value = process
                with patch("kicad2cnc.gcode.subprocess.Popen", return_value=process):
                    with self.assertRaisesRegex(ExportError, "exit 7|timed out"):
                        generate_gcode(root, executable, CncSettings())
                if failure == "timeout":
                    process.kill.assert_called_once()

    def test_unsupported_converter_options_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "converter.exe"
            executable.touch()
            process = MagicMock()
            process.stdout = iter([])
            process.returncode = 0
            process.__enter__.return_value = process
            with patch("kicad2cnc.gcode.subprocess.Popen", return_value=process):
                with self.assertRaisesRegex(ExportError, "missing options"):
                    generate_gcode(root, executable, CncSettings())

    def test_custom_gerbers_are_identified_by_layer_not_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / "gerbers").mkdir()
            front = job / "gerbers" / "top_layer.gbr"
            front.write_text("%TF.FileFunction,Copper,L1,Top*%\n")
            self.assertEqual(layer_file(job, "F.Cu"), front)
            self.assertIsNone(layer_file(job, "B.Cu"))
            front.with_name("duplicate.gbr").write_bytes(front.read_bytes())
            with self.assertRaisesRegex(ExportError, "Multiple"):
                layer_file(job, "F.Cu")

    def test_missing_converter_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ExportError, "executable not found"):
                generate_gcode(Path(directory), Path(directory) / "missing.exe", CncSettings())

    def test_converter_failure_rejects_complete_job_without_publishing(self) -> None:
        cli = Path(os.environ.get("LOCALAPPDATA", "")) / r"Programs\KiCad\10.0\bin\kicad-cli.exe"
        if not cli.is_file():
            self.skipTest("KiCad CLI required for staging test.")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ExportError, "Converter failed"):
                export_board(
                    cli, ROOT / r"tests\fixtures\demo.kicad_pcb", output,
                    ("F.Cu", "Edge.Cuts"),
                    convert=MockConverterFailure(),
                )
            self.assertEqual(list(output.iterdir()), [])


class MockConverterFailure:
    def __call__(self, job: Path) -> str:
        (job / "partial.ngc").write_text("partial")
        raise ExportError("Converter failed")


class GcodeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.converter = find_converter(os.environ.get("PCB2GCODE", ""))
        except ValueError as error:
            raise unittest.SkipTest(str(error)) from error
        cls.cli = Path(os.environ.get(
            "KICAD_CLI",
            str(Path(os.environ.get("LOCALAPPDATA", "")) / r"Programs\KiCad\10.0\bin\kicad-cli.exe"),
        ))
        if not cls.cli.is_file():
            raise unittest.SkipTest("Set KICAD_CLI for real CAM integration tests.")

    def export(self, output: Path, settings: CncSettings, layers: tuple[str, ...] = ("F.Cu", "B.Cu", "Edge.Cuts")) -> Path:
        result = export_board(
            self.cli, ROOT / r"tests\fixtures\demo.kicad_pcb", output, layers,
            convert=partial(generate_gcode, executable=self.converter, settings=settings),
        )
        return result.directory

    def test_actual_routing_and_drilling_units_extents_depths_tabs_and_mirroring(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cnc CAM with spaces ") as directory:
            job = self.export(Path(directory), CncSettings())
            gcode = job / "gcode"
            paths = tuple((gcode / "cam").rglob("*.ngc"))
            self.assertEqual(len(paths), 5)
            self.assertTrue((gcode / "REVIEW_BEFORE_MACHINING.txt").is_file())
            self.assertNotIn("CRITICAL", (gcode / "conversion.log").read_text())
            for path in paths:
                text = path.read_text()
                code = re.sub(r"\([^)]*\)", "", text)
                self.assertRegex(code, r"\bG21\b")
                self.assertRegex(code, r"\bG90\b")
                self.assertNotRegex(code, r"\bG(?:20|64|81)\b")
                self.assertTrue(re.search(r"\bG0?1\b", code))
                self.assertIn("Z3.00000", code)
            front = (gcode / r"cam\routing\front.ngc").read_text()
            back = (gcode / r"cam\routing\back.ngc").read_text()
            outline = (gcode / r"cam\routing\outline.ngc").read_text()
            for text in (front, back):
                self.assertIn("Z-0.05000", text)
                self.assertIn("F120.00000", text)
            front_x = [float(value) for value in re.findall(r"\bX(-?[\d.]+)", front)]
            back_x = [float(value) for value in re.findall(r"\bX(-?[\d.]+)", back)]
            self.assertGreater(min(front_x), 3.0)
            self.assertLess(max(front_x), 17.0)
            self.assertLess(max(back_x), -3.0)
            self.assertGreater(min(back_x), -17.0)
            for value in ("Z-0.36000", "Z-0.72000", "Z-1.08000", "Z-1.44000", "Z-1.80000", "Z-1.00000"):
                self.assertIn(value, outline)
            outline_x = [float(value) for value in re.findall(r"\bX(-?[\d.]+)", outline)]
            outline_y = [float(value) for value in re.findall(r"\bY(-?[\d.]+)", outline)]
            self.assertAlmostEqual(max(outline_x) - min(outline_x), 31.0, delta=0.1)
            self.assertAlmostEqual(max(outline_y) - min(outline_y), 21.0, delta=0.1)
            drill_text = "\n".join(
                path.read_text() for path in paths
                if path.parent.name.startswith("drill-")
            )
            for position in ("X5.00000 Y-5.00000", "X15.00000 Y-5.00000", "X25.00000 Y-15.00000"):
                self.assertIn(position, drill_text)
            self.assertIn("Z-1.80000", drill_text)
            config = (gcode / r"cam\routing\millproject").read_text()
            self.assertIn("metricoutput=true", config)
            self.assertIn("zero-start=false", config)
            self.assertIn("nog81=true", config)
            self.assertIn("%TF.FileFunction", (job / r"gerbers\demo-F_Cu.gbr").read_text())
            self.assertNotIn("%TF.", (gcode / r"cam\routing\front.gbr").read_text())
            grbl = tuple((gcode / "grbl").glob("*.nc"))
            self.assertEqual(len(grbl), 6)
            for path in grbl:
                code = re.sub(r"\([^)]*\)", "", path.read_text(encoding="ascii"))
                self.assertNotRegex(code, r"\b(?:M0?6|T\d+)\b")
                self.assertNotRegex(code, r"\bM0\b")
                self.assertIn("M3 S10000", code)
                self.assertTrue(code.rstrip().endswith("M30"))
            self.assertTrue((gcode / "grbl" / "README_job.txt").is_file())

    def test_actual_milldrill_routes_large_holes_and_drills_small_holes(self) -> None:
        settings = replace(CncSettings(), milldrill_threshold=1.2, cutter_diameter=0.5)
        with tempfile.TemporaryDirectory() as directory:
            job = self.export(Path(directory), settings)
            mills = tuple((job / "gcode").rglob("milldrill.ngc"))
            drills = tuple((job / "gcode").rglob("drill.ngc"))
            self.assertEqual(len(mills), 1)
            self.assertEqual(len(drills), 1)
            text = mills[0].read_text()
            self.assertIn("Z-1.80000", text)
            self.assertRegex(text, r"\bG0?[23]\b")
            self.assertIn("X5.00000 Y-5.00000", drills[0].read_text())
            grbl = tuple((job / "gcode" / "grbl").glob("*.nc"))
            self.assertTrue(any("milldrill" in path.name for path in grbl))
            self.assertTrue(any("drill-pth" in path.name for path in grbl))

    def test_single_diameter_alternative_keeps_normal_files_and_all_holes(self) -> None:
        settings = replace(
            CncSettings(), combined_drilling=True, combined_drill_diameter=0.6,
            milldrill_threshold=1.2, cutter_diameter=0.5,
            registration=True, registration_positions="0, -5\n0, -15",
        )
        with tempfile.TemporaryDirectory() as directory:
            for layers, sign in ((("F.Cu", "Edge.Cuts"), ""), (("B.Cu", "Edge.Cuts"), "-")):
                with self.subTest(layers=layers):
                    job = self.export(Path(directory), settings, layers)
                    programs = tuple((job / "gcode" / "grbl").glob("*.nc"))
                    combined = [path for path in programs if "drill-all-one-size" in path.name]
                    self.assertEqual(len(combined), 1)
                    text = combined[0].read_text(encoding="ascii")
                    self.assertIn("Tool: 0.6 mm", text)
                    self.assertIn("ALTERNATIVE", text)
                    for x, y in (("5", "-5"), ("15", "-5"), ("25", "-15")):
                        self.assertIn(f"X{sign}{x}.00000 Y{y}.00000", text)
                    self.assertNotIn("X0.00000 Y-5.00000", text)
                    self.assertEqual(text.count("M3 S10000"), 1)
                    self.assertEqual(text.count("M30"), 1)
                    code = re.sub(r"\([^)]*\)", "", text)
                    self.assertNotRegex(code, r"\b(?:M0?6|T\d+)\b")
                    self.assertTrue(any("drill-pth-0p8mm" in path.name for path in programs))
                    self.assertTrue(any("drill-pth-1mm" in path.name for path in programs))
                    self.assertTrue(any("milldrill-npth" in path.name for path in programs))
                    self.assertTrue(any("registration-drill-2mm" in path.name for path in programs))
                    readme = (job / "gcode" / "grbl" / "README_job.txt").read_text(encoding="utf-8")
                    self.assertIn("Run it INSTEAD OF", readme)
                    combined_cam = tuple((job / "gcode" / "cam").glob("drill-combined-*"))
                    self.assertEqual(len(combined_cam), 2)
                    for folder in combined_cam:
                        config = (folder / "millproject").read_text()
                        self.assertNotIn("min-milldrill-hole-diameter", config)

    def test_registration_holes_create_first_symmetric_through_drill_operation(self) -> None:
        settings = replace(
            CncSettings(),
            registration=True,
            registration_hole_diameter=2.0,
            registration_positions="0, -5\n0, -15",
        )
        with tempfile.TemporaryDirectory() as directory:
            job = self.export(Path(directory), settings)
            source = (job / "gcode" / "cam" / "registration-input.drl").read_text()
            self.assertIn("T1C2.000000", source)
            self.assertIn("X0.000000Y-5.000000", source)
            self.assertIn("X0.000000Y-15.000000", source)
            programs = tuple((job / "gcode" / "grbl").glob("*registration*.nc"))
            self.assertEqual(len(programs), 1)
            self.assertEqual(programs[0].name, "01-registration-drill-2mm.nc")
            text = programs[0].read_text(encoding="ascii")
            self.assertIn("Tool: 2 mm", text)
            self.assertIn("X0.00000 Y-5.00000", text)
            self.assertIn("X0.00000 Y-15.00000", text)
            readme = (job / "gcode" / "grbl" / "README_job.txt").read_text(encoding="utf-8")
            self.assertIn("Drill registration holes first", readme)
            self.assertIn("180-degree Y-axis flip", readme)
            self.assertIn("copper, component, edge, and clamp clearances are not checked", readme)

    def test_single_diameter_alternative_rejects_slots_instead_of_omitting_them(self) -> None:
        settings = replace(
            CncSettings(), isolation=False, outline=False,
            combined_drilling=True, combined_drill_diameter=0.6,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            board = root / "slots.kicad_pcb"
            source = (ROOT / r"tests\fixtures\demo.kicad_pcb").read_text()
            board.write_text(source.replace("(drill 1.5)", "(drill oval 1.5 2.5)"))
            with self.assertRaisesRegex(ExportError, "Routed Excellon slots are not supported"):
                export_board(
                    self.cli, board, root / "output", ("Edge.Cuts",),
                    convert=partial(generate_gcode, executable=self.converter, settings=settings),
                )
            self.assertEqual(list((root / "output").iterdir()), [])

    def test_back_only_mirrors_drills_and_outline_to_match_back_copper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = self.export(Path(directory), CncSettings(), ("B.Cu", "Edge.Cuts"))
            gcode = job / "gcode"
            files = tuple(sorted((gcode / "grbl").glob("*.nc")))
            names = [path.name for path in files]
            self.assertTrue(any("isolation-back" in name for name in names))
            self.assertTrue(any("drill-pth-0p8mm" in name for name in names))
            self.assertTrue(any("outline-1mm" in name for name in names))
            self.assertFalse(any("isolation-front" in name for name in names))

            drill = "\n".join(
                path.read_text(encoding="ascii")
                for path in files
                if "drill-pth" in path.name
            )
            self.assertIn("X-5.00000 Y-5.00000", drill)
            self.assertIn("X-15.00000 Y-5.00000", drill)
            outline_path = next(path for path in files if "outline-1mm" in path.name)
            outline = outline_path.read_text(encoding="ascii")
            outline_x = [
                float(value)
                for value in re.findall(r"\bX(-?[\d.]+)", re.sub(r"\([^)]*\)", "", outline))
            ]
            self.assertTrue(outline_x)
            source_outline = (gcode / r"cam\routing\outline.ngc").read_text()
            source_x = [
                float(value)
                for value in re.findall(
                    r"\bX(-?[\d.]+)", re.sub(r"\([^)]*\)", "", source_outline)
                )
            ]
            self.assertEqual(len(outline_x), len(source_x))
            for actual, source in zip(outline_x, source_x):
                self.assertAlmostEqual(actual, -source, places=5)
            self.assertIn("X-mirrored to match B.Cu", outline)

            back_path = next(path for path in files if "isolation-back" in path.name)
            back = back_path.read_text(encoding="ascii")
            self.assertNotIn("X-mirrored to match B.Cu", back)
            review = (gcode / "REVIEW_BEFORE_MACHINING.txt").read_text(encoding="utf-8")
            self.assertIn("B.Cu-only mode", review)
            self.assertIn("no board flip", review)
            readme = (gcode / "grbl" / "README_job.txt").read_text(encoding="utf-8")
            self.assertIn("do not flip it between these operations", readme)

    def test_actual_front_only_isolation_does_not_create_other_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            job = self.export(
                Path(directory), replace(CncSettings(), outline=False, drilling=False),
                ("F.Cu", "Edge.Cuts"),
            )
            gcode = job / "gcode"
            self.assertEqual(
                [path.name for path in (gcode / "cam").rglob("*.ngc")], ["front.ngc"]
            )
            self.assertEqual(
                [path.name for path in (gcode / "grbl").glob("*.nc")],
                ["01-isolation-front-0p2mm.nc"],
            )

    def test_converter_nonzero_exit_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("kicad2cnc.gcode.subprocess.Popen", side_effect=OSError("Cannot start")):
                with self.assertRaisesRegex(ExportError, "Could not launch"):
                    generate_gcode(Path(directory), self.converter, CncSettings())


if __name__ == "__main__":
    unittest.main()
