import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from kicad2cnc.settings import (
    CncSettings, find_converter, load_settings, save_settings, settings_path,
)


class CncSettingsTests(unittest.TestCase):
    def test_defaults_are_valid(self) -> None:
        CncSettings().validate()

    def test_invalid_values_are_rejected(self) -> None:
        for changes in (
            {"mill_diameter": 0.0}, {"safe_z": -1.0}, {"mill_depth": 0.1},
            {"drill_depth": 0.0}, {"cut_depth": 0.0}, {"overlap": 100.0},
            {"registration_depth": 0.0}, {"registration_depth": 0.5},
            {"registration_depth": float("nan")}, {"registration_depth": float("-inf")},
            {"bridge_z": -2.0}, {"bridge_count": -1}, {"change_z": 1.0},
            {"isolation": False, "drilling": False, "outline": False},
            {"cut_feed": float("nan")}, {"mill_feed": float("inf")},
            {"milldrill_threshold": 0.5}, {"bridge_count": 2.5}, {"spindle": True},
            {"spinup_time": -0.1}, {"spindown_time": 600.1},
            {"spinup_time": float("nan")},
            {"registration": True, "registration_positions": ""},
            {"registration": True, "registration_positions": "1, 2\n-2, 1"},
            {"registration": True, "registration_positions": "1, 2\n-1, 2\n0, 3\n0, 3"},
            {"registration": True, "registration_hole_diameter": 0.0,
             "registration_positions": "1, 2\n-1, 2"},
            {"combined_drilling": True, "combined_drill_diameter": 0.0},
            {"combined_drilling": True, "combined_drill_diameter": -0.5},
            {"combined_drilling": True, "drilling": False},
            {"combined_drill_diameter": float("nan")},
            {"bcnc_operations": "unknown"},
            {"bcnc_tool_changes": True, "bcnc_operations": "drills", "drilling": False},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(CncSettings(), **changes).validate()

    def test_save_and_load_round_trip_next_to_board(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            board = Path(directory) / "board.kicad_pcb"
            original = replace(
                CncSettings(), executable=r"C:\CAM tools\pcb2gcode.exe", cut_depth=-2.0,
                spinup_time=2.5, spindown_time=3.0,
                registration=True, registration_hole_diameter=2.5,
                registration_depth=-3.0,
                registration_positions="1.5, -2\n-1.5, -2",
                combined_drilling=True, combined_drill_diameter=0.6,
                bcnc_tool_changes=True, bcnc_operations="drills",
            )
            self.assertEqual(load_settings(board), CncSettings())
            save_settings(board, original)
            self.assertEqual(load_settings(board), original)
            self.assertEqual(settings_path(board), Path(directory) / "board.kicad2cnc.json")

    def test_invalid_saved_settings_do_not_silently_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            board = Path(directory) / "board.kicad_pcb"
            for content in ('null', '[]', '{"unknown": 1}', '{"spindle": "fast"}', '{'):
                settings_path(board).write_text(content)
                with self.subTest(content=content), self.assertRaises((ValueError, TypeError)):
                    load_settings(board)

    def test_existing_settings_default_to_no_combined_drill_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            board = Path(directory) / "board.kicad_pcb"
            settings_path(board).write_text('{"drill_feed": 100.0}')
            settings = load_settings(board)
            self.assertFalse(settings.combined_drilling)
            self.assertFalse(settings.bcnc_tool_changes)
            self.assertEqual(settings.bcnc_operations, "all")
            self.assertEqual(settings.drill_feed, 100.0)

    def test_executable_discovery_and_invalid_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "pcb2gcode.exe"
            executable.touch()
            self.assertEqual(find_converter(str(executable)), executable)
            with patch("kicad2cnc.settings.shutil.which", return_value=str(executable)):
                self.assertEqual(find_converter(), executable)
            with self.assertRaisesRegex(ValueError, "was not found"):
                find_converter(str(executable.with_name("missing.exe")))

    def test_existing_settings_preserve_registration_depth_from_board_drills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            board = Path(directory) / "board.kicad_pcb"
            settings_path(board).write_text('{"drill_depth": -2.7}')
            settings = load_settings(board)
            self.assertEqual(settings.registration_depth, -2.7)
            save_settings(board, replace(settings, drill_depth=-1.9))
            self.assertEqual(load_settings(board).registration_depth, -2.7)


if __name__ == "__main__":
    unittest.main()
