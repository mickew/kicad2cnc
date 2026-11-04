import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kicad2cnc.export import ExportError, _publish_job, export_board


ROOT = Path(__file__).resolve().parents[1]


class ExportTests(unittest.TestCase):
    def test_publication_retries_transient_windows_locks_and_logs_them(self) -> None:
        for code in (5, 32, 33):
            error = PermissionError("Folder locked")
            error.winerror = code
            with (
                self.subTest(code=code),
                patch.object(Path, "rename", side_effect=[error, error, None]) as rename,
                patch("kicad2cnc.export.time.sleep") as sleep,
            ):
                log: list[str] = []
                _publish_job(Path("stage"), Path("destination"), log)
                self.assertEqual(rename.call_count, 3)
                self.assertEqual(sleep.call_count, 2)
                self.assertEqual(len(log), 2)
                self.assertIn(f"error {code}", log[0])

    def test_persistent_publication_lock_fails_and_no_job_is_published(self) -> None:
        error = PermissionError("Folder locked")
        error.winerror = 5
        with (
            patch("kicad2cnc.export.subprocess.run", side_effect=self.fake_run),
            patch.object(Path, "rename", side_effect=error) as rename,
            patch("kicad2cnc.export.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(ExportError, "after 5 seconds of retries"):
                export_board(self.cli, self.board, self.output, self.layers)
        self.assertEqual(rename.call_count, 11)
        self.assertEqual(sleep.call_count, 10)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_publication_does_not_retry_other_errors_or_overwrite_existing_jobs(self) -> None:
        with (
            patch.object(Path, "rename", side_effect=FileExistsError("Destination exists")),
            patch("kicad2cnc.export.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(ExportError, "Could not publish completed job"):
                _publish_job(Path("stage"), Path("destination"), [])
        sleep.assert_not_called()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cnc tests with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.board = self.root / "test board.kicad_pcb"
        self.board.write_text("board", encoding="utf-8")
        self.cli = self.root / "kicad-cli.exe"
        self.cli.touch()
        self.output = self.root / "cnc output"
        self.layers = ("F.Cu", "Edge.Cuts")

    def fake_run(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        directory = Path(args[args.index("--output") + 1])
        directory.mkdir(parents=True)
        if args[3] == "gerbers":
            for layer in args[args.index("--layers") + 1].split(","):
                (directory / f"{self.board.stem}-{layer.replace('.', '_')}.gbr").write_text("gerber")
        else:
            (directory / f"{self.board.stem}-PTH.drl").write_text("drill")
            (directory / f"{self.board.stem}-NPTH.drl").write_text("drill")
        return subprocess.CompletedProcess(args, 0, "CLI output", "")

    def test_exact_arguments_shared_origin_spaces_and_complete_job(self) -> None:
        with patch("kicad2cnc.export.subprocess.run", side_effect=self.fake_run) as run:
            result = export_board(self.cli, self.board, self.output, self.layers)
        self.assertEqual(len(result.files), 4)
        self.assertTrue(all(path.is_file() for path in result.files))
        gerber, drill = [call.args[0] for call in run.call_args_list]
        self.assertIn("--use-drill-file-origin", gerber)
        self.assertEqual(gerber[gerber.index("--layers") + 1], "F.Cu,Edge.Cuts")
        self.assertEqual(drill[drill.index("--drill-origin") + 1], "plot")
        self.assertEqual(drill[drill.index("--excellon-units") + 1], "mm")
        self.assertIn("--excellon-separate-th", drill)
        self.assertEqual(gerber[-1], str(self.board))
        self.assertTrue(result.directory.is_relative_to(self.output))
        self.assertFalse(any(path.name.startswith(".kicad2cnc-") for path in self.output.iterdir()))
        self.assertIn("CLI output", result.log)

    def test_repeated_exports_do_not_overwrite_jobs_or_unrelated_files(self) -> None:
        self.output.mkdir()
        unrelated = self.output / "keep.txt"
        unrelated.write_text("keep")
        with patch("kicad2cnc.export.subprocess.run", side_effect=self.fake_run):
            first = export_board(self.cli, self.board, self.output, self.layers)
            second = export_board(self.cli, self.board, self.output, self.layers)
        self.assertNotEqual(first.directory, second.directory)
        self.assertTrue(first.files[0].is_file())
        self.assertEqual(unrelated.read_text(), "keep")

    def test_failed_drill_export_never_publishes_partial_job(self) -> None:
        def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if args[3] == "gerbers":
                return self.fake_run(args)
            return subprocess.CompletedProcess(args, 3, "", "Drill export failed")
        with patch("kicad2cnc.export.subprocess.run", side_effect=run):
            with self.assertRaisesRegex(ExportError, "Drill export failed"):
                export_board(self.cli, self.board, self.output, self.layers)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_timeout_and_launch_errors_are_explicit_and_cleaned_up(self) -> None:
        for error in (subprocess.TimeoutExpired("kicad-cli", 180), OSError("Access denied")):
            with self.subTest(error=type(error).__name__):
                with patch("kicad2cnc.export.subprocess.run", side_effect=error):
                    with self.assertRaisesRegex(ExportError, "Could not run KiCad export"):
                        export_board(self.cli, self.board, self.output, self.layers)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_missing_gerber_or_drill_output_is_not_success(self) -> None:
        for missing in ("F_Cu.gbr", "PTH.drl"):
            def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                result = self.fake_run(args)
                directory = Path(args[args.index("--output") + 1])
                for path in directory.iterdir():
                    if path.name.endswith(missing):
                        path.unlink()
                return result
            with self.subTest(missing=missing):
                with patch("kicad2cnc.export.subprocess.run", side_effect=run):
                    with self.assertRaises(ExportError):
                        export_board(self.cli, self.board, self.output, self.layers)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_board_saved_mid_export_is_rejected(self) -> None:
        def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            self.board.write_text("edited")
            return self.fake_run(args)
        with patch("kicad2cnc.export.subprocess.run", side_effect=run):
            with self.assertRaisesRegex(ExportError, "changed during export"):
                export_board(self.cli, self.board, self.output, self.layers)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_custom_copper_filenames_are_validated_by_x2_not_filename(self) -> None:
        def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            result = self.fake_run(args)
            if args[3] == "gerbers":
                directory = Path(args[args.index("--output") + 1])
                front = directory / f"{self.board.stem}-F_Cu.gbr"
                front.rename(directory / f"{self.board.stem}-top_layer.gbr")
                (directory / f"{self.board.stem}-top_layer.gbr").write_text(
                    "%TF.FileFunction,Copper,L1,Top*%\n%FSLAX46Y46*%\n"
                )
            return result
        with patch("kicad2cnc.export.subprocess.run", side_effect=run):
            result = export_board(self.cli, self.board, self.output, self.layers)
        self.assertTrue((result.directory / "gerbers" / f"{self.board.stem}-top_layer.gbr").is_file())

    def test_wrong_side_or_duplicate_custom_layers_do_not_pass_validation(self) -> None:
        for functions in (("Copper,L2,Bot",), ("Copper,L1,Top", "Copper,L1,Top")):
            def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                result = self.fake_run(args)
                if args[3] == "gerbers":
                    directory = Path(args[args.index("--output") + 1])
                    (directory / f"{self.board.stem}-F_Cu.gbr").unlink()
                    for index, function in enumerate(functions):
                        (directory / f"custom-{index}.gbr").write_text(f"%TF.FileFunction,{function}*%\n")
                return result
            with self.subTest(functions=functions):
                with patch("kicad2cnc.export.subprocess.run", side_effect=run):
                    with self.assertRaisesRegex(ExportError, "requested layer: F.Cu"):
                        export_board(self.cli, self.board, self.output, self.layers)
                self.assertEqual(list(self.output.iterdir()), [])

    def test_invalid_inputs_never_launch_cli(self) -> None:
        cases = (
            (self.root / "missing.exe", self.board, self.output, self.layers),
            (self.cli, self.root / "missing.kicad_pcb", self.output, self.layers),
            (self.cli, self.board, Path("relative"), self.layers),
            (self.cli, self.board, self.output, ()),
        )
        with patch("kicad2cnc.export.subprocess.run") as run:
            for args in cases:
                with self.subTest(args=args), self.assertRaises(ExportError):
                    export_board(*args)
            run.assert_not_called()


class KiCadExportIntegrationTests(unittest.TestCase):
    def test_custom_layer_names_with_real_cli(self) -> None:
        default = Path(os.environ.get("LOCALAPPDATA", "")) / r"Programs\KiCad\10.0\bin\kicad-cli.exe"
        cli = Path(os.environ.get("KICAD_CLI", str(default)))
        if not cli.is_file():
            self.skipTest("Set KICAD_CLI to run the real KiCad export integration test.")
        with tempfile.TemporaryDirectory(prefix="cnc custom names ") as output:
            root = Path(output)
            board = root / "custom.kicad_pcb"
            source = (ROOT / r"tests\fixtures\demo.kicad_pcb").read_text()
            board.write_text(
                source.replace('(0 "F.Cu" signal)', '(0 "F.Cu" signal "top_layer")')
                .replace('(2 "B.Cu" signal)', '(2 "B.Cu" signal "bottom_layer")')
                .replace('(25 "Edge.Cuts" user)', '(25 "Edge.Cuts" user "board_outline")')
            )
            result = export_board(cli, board, root / "out", ("F.Cu", "B.Cu", "Edge.Cuts"))
            names = {path.name for path in result.files}
            self.assertTrue({"custom-top_layer.gbr", "custom-bottom_layer.gbr", "custom-board_outline.gbr"} <= names)
            self.assertEqual(len(tuple(result.directory.rglob("*.drl"))), 2)

    def test_real_cli_exports_selected_layers_and_aligned_metric_drills(self) -> None:
        default = Path(os.environ.get("LOCALAPPDATA", "")) / r"Programs\KiCad\10.0\bin\kicad-cli.exe"
        cli = Path(os.environ.get("KICAD_CLI", str(default)))
        if not cli.is_file():
            self.skipTest("Set KICAD_CLI to run the real KiCad export integration test.")
        board = ROOT / r"tests\fixtures\demo.kicad_pcb"
        with tempfile.TemporaryDirectory(prefix="cnc integration ") as output:
            result = export_board(cli, board, Path(output), ("F.Cu", "B.Cu", "Edge.Cuts"))
            self.assertEqual(len(tuple(result.directory.rglob("*.gbr"))), 3)
            front = (result.directory / r"gerbers\demo-F_Cu.gbr").read_text()
            outline = (result.directory / r"gerbers\demo-Edge_Cuts.gbr").read_text()
            pth = (result.directory / r"drill\demo-PTH.drl").read_text()
            npth = (result.directory / r"drill\demo-NPTH.drl").read_text()
            self.assertIn("%MOMM*%", front)
            self.assertIn("X5000000Y-5000000", front)
            self.assertIn("X0Y0", outline)
            self.assertIn("X30000000Y-20000000", outline)
            self.assertIn("METRIC", pth)
            self.assertIn("X5.0Y-5.0", pth)
            self.assertIn("X15.0Y-5.0", pth)
            self.assertIn("C0.800", pth)
            self.assertIn("X25.0Y-15.0", npth)
            self.assertIn("C1.500", npth)
            single = export_board(cli, board, Path(output), ("F.Cu", "Edge.Cuts"))
            self.assertFalse(tuple(single.directory.rglob("*B_Cu*")))

    def test_cli_matches_kicad_plotter_reference(self) -> None:
        default = Path(os.environ.get("LOCALAPPDATA", "")) / r"Programs\KiCad\10.0\bin\kicad-cli.exe"
        cli = Path(os.environ.get("KICAD_CLI", str(default)))
        python = cli.with_name("python.exe")
        if not cli.is_file() or not python.is_file():
            self.skipTest("KiCad's bundled Python is needed for the reference plotter test.")
        board = ROOT / r"tests\fixtures\demo.kicad_pcb"
        reference_script = """
import sys
import pcbnew
board = pcbnew.LoadBoard(sys.argv[1])
plot = pcbnew.PLOT_CONTROLLER(board)
options = plot.GetPlotOptions()
options.SetOutputDirectory(sys.argv[2])
options.SetUseAuxOrigin(True)
options.SetGerberPrecision(6)
options.SetUseGerberX2format(True)
options.SetIncludeGerberNetlistInfo(True)
options.SetPlotFrameRef(False)
options.SetDrillMarksType(pcbnew.DRILL_MARKS_NO_DRILL_SHAPE)
for layer, name in [(pcbnew.F_Cu, 'F_Cu'), (pcbnew.B_Cu, 'B_Cu'), (pcbnew.Edge_Cuts, 'Edge_Cuts')]:
    plot.SetLayer(layer)
    assert plot.OpenPlotfile(name, pcbnew.PLOT_FORMAT_GERBER)
    assert plot.PlotLayer()
plot.ClosePlot()
writer = pcbnew.EXCELLON_WRITER(board)
writer.SetFormat(True)
writer.SetOptions(False, False, board.GetDesignSettings().GetAuxOrigin(), False)
writer.SetRouteModeForOvalHoles(True)
assert writer.CreateDrillandMapFilesSet(sys.argv[2], True, False)
"""
        with tempfile.TemporaryDirectory(prefix="cnc reference ") as output:
            root = Path(output)
            reference = root / "reference"
            reference.mkdir()
            completed = subprocess.run(
                [str(python), "-c", reference_script, str(board), str(reference)],
                capture_output=True, text=True, timeout=60, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = export_board(cli, board, root, ("F.Cu", "B.Cu", "Edge.Cuts"))
            for path in result.files:
                if path.suffix not in (".gbr", ".drl"):
                    continue
                with self.subTest(file=path.name):
                    def geometry(file: Path) -> list[str]:
                        return [
                            line for line in file.read_text().splitlines()
                            if not line.startswith(("G04", "%TF.", ";"))
                        ]
                    self.assertEqual(geometry(path), geometry(reference / path.name))


if __name__ == "__main__":
    unittest.main()
