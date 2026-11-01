import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from kipy import KiCad
from kipy.board import Board, BoardLayer
from kipy.errors import ApiError
from kipy.kicad import KiCadVersion
from kipy.proto.common.types import DocumentSpecifier

from kicad2cnc.board_info import read_board_info


class BoardInfoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock(spec=KiCad)
        self.client.get_version.return_value = KiCadVersion(10, 0, 7, "10.0.7")
        self.layers = patch.object(
            Board,
            "get_enabled_layers",
            return_value=[BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu, BoardLayer.BL_Edge_Cuts],
        )
        self.layers.start()
        self.addCleanup(self.layers.stop)

    def set_board(self, name: str, directory: str = "") -> None:
        document = DocumentSpecifier(board_filename=name)
        document.project.path = directory
        self.client.get_board.return_value = Board(Mock(), document)

    def test_saved_board_uses_project_directory_and_real_layer_names(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cnc board ") as directory:
            path = Path(directory) / "two sided.kicad_pcb"
            path.touch()
            self.set_board(path.name, directory)
            info = read_board_info(self.client)
            self.assertEqual(info.filename, str(path))
            self.assertTrue(info.saved_file_exists)
            self.assertEqual(info.layers, ("F.Cu", "B.Cu", "Edge.Cuts"))
            self.assertEqual(info.version, "10.0.7")
            self.assertIn("does not report unsaved changes", info.save_notice)

    def test_absolute_filename_is_not_rebased(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.kicad_pcb"
            path.touch()
            self.set_board(str(path), str(Path(directory) / "other"))
            info = read_board_info(self.client)
            self.assertEqual(info.filename, str(path))
            self.assertTrue(info.saved_file_exists)

    def test_empty_board_name_does_not_count_directory_as_saved_file(self) -> None:
        self.set_board("", tempfile.gettempdir())
        info = read_board_info(self.client)
        self.assertFalse(info.saved_file_exists)
        self.assertEqual(info.filename, "(not saved)")
        self.assertIn("No saved board file", info.save_notice)

    def test_relative_name_without_directory_is_not_resolved_against_working_directory(self) -> None:
        self.set_board("board.kicad_pcb")
        self.assertFalse(read_board_info(self.client).saved_file_exists)

    def test_missing_file_requires_saving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.set_board("missing.kicad_pcb", directory)
            self.assertFalse(read_board_info(self.client).saved_file_exists)

    def test_no_open_board_error_is_not_swallowed(self) -> None:
        self.client.get_board.side_effect = ApiError("No board")
        with self.assertRaises(ApiError):
            read_board_info(self.client)

    def test_other_major_version_is_rejected(self) -> None:
        for major in (9, 11):
            self.client.get_version.return_value = KiCadVersion(major, 0, 0, f"{major}.0.0")
            with self.assertRaisesRegex(RuntimeError, "targets KiCad 10"):
                read_board_info(self.client)

    def test_inspection_never_saves_the_board(self) -> None:
        self.set_board("")
        with patch.object(Board, "save") as save:
            read_board_info(self.client)
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
