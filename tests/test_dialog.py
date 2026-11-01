import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import wx
from kipy import KiCad
from kipy.errors import ApiError
from pynng import Timeout, lib

from kicad2cnc.board_info import BoardInfo
from kicad2cnc.export import ExportResult
from kicad2cnc.settings import CncSettings
from kicad2cnc.ui.dialog import BoardInfoDialog
from kicad2cnc.ui.settings_dialog import CncSettingsDialog


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = wx.App(False)

    def setUp(self) -> None:
        self.dialog = BoardInfoDialog(Mock(spec=KiCad))

    def tearDown(self) -> None:
        if self.dialog:
            self.dialog.Destroy()
        self.app.ProcessPendingEvents()

    def test_close_destroys_dialog_and_exits_event_loop(self) -> None:
        self.dialog.Show()
        self.app.SetTopWindow(self.dialog)
        timeout = wx.CallLater(2000, self.app.ExitMainLoop)
        wx.CallAfter(self.dialog.Close)
        self.app.MainLoop()
        timeout.Stop()
        self.assertFalse(self.dialog)

    def test_refresh_displays_filename_version_layers_and_save_reminder(self) -> None:
        info = BoardInfo(
            r"C:\boards\test board.kicad_pcb",
            ("F.Cu", "B.Cu", "Edge.Cuts"),
            True,
            "10.0.7",
        )
        with patch("kicad2cnc.ui.dialog.read_board_info", return_value=info):
            self.dialog.refresh_board()
        self.assertEqual(self.dialog.filename.GetValue(), info.filename)
        self.assertEqual(self.dialog.layers.GetStrings(), list(info.layers))
        self.assertEqual(self.dialog.status.GetLabel(), "Connected to KiCad 10.0.7")
        self.assertEqual(self.dialog.layer_label.GetLabel(), "Enabled layers (3)")
        self.assertIn("Save the board", self.dialog.notice.GetLabel())
        self.assertTrue(self.dialog.refresh.IsEnabled())
        self.assertFalse(self.dialog.filename.IsEditable())

    def test_missing_file_gets_explicit_save_warning(self) -> None:
        info = BoardInfo("(not saved)", ("F.Cu",), False, "10.0.7")
        with patch("kicad2cnc.ui.dialog.read_board_info", return_value=info):
            self.dialog.refresh_board()
        self.assertIn("No saved board file", self.dialog.notice.GetLabel())
        self.assertFalse(self.dialog.export_button.IsEnabled())

    def load_saved_board(self) -> BoardInfo:
        info = BoardInfo(r"C:\boards\test.kicad_pcb", ("F.Cu", "B.Cu", "Edge.Cuts"), True, "10.0.7")
        with patch("kicad2cnc.ui.dialog.read_board_info", return_value=info):
            self.dialog.refresh_board()
        return info

    def test_layer_selection_and_output_survive_refresh(self) -> None:
        info = self.load_saved_board()
        self.dialog.layers.SetCheckedStrings(["F.Cu", "Edge.Cuts"])
        self.dialog.output.SetPath(r"C:\custom output")
        with patch("kicad2cnc.ui.dialog.read_board_info", return_value=info):
            self.dialog.refresh_board()
        self.assertEqual(self.dialog.layers.GetCheckedStrings(), ("F.Cu", "Edge.Cuts"))
        self.assertEqual(self.dialog.output.GetPath(), r"C:\custom output")

    def test_cancel_save_confirmation_does_not_start_export(self) -> None:
        info = self.load_saved_board()
        with (
            patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
            patch("kicad2cnc.ui.dialog.wx.MessageBox", return_value=wx.NO),
            patch("kicad2cnc.ui.dialog.Thread") as thread,
        ):
            self.dialog.on_export()
        thread.assert_not_called()
        self.assertFalse(self.dialog.exporting)

    def test_no_layers_is_an_explicit_settings_error(self) -> None:
        info = self.load_saved_board()
        self.dialog.layers.SetCheckedStrings([])
        with (
            patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
            patch("kicad2cnc.ui.dialog.wx.MessageBox") as message,
            patch("kicad2cnc.ui.dialog.Thread") as thread,
        ):
            self.dialog.on_export()
        self.assertIn("Select at least one", message.call_args.args[0])
        thread.assert_not_called()

    def test_export_uses_active_installation_and_disables_controls(self) -> None:
        info = self.load_saved_board()
        self.dialog.kicad.get_kicad_binary_path.return_value = r"C:\KiCad\kicad-cli.exe"
        with (
            patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
            patch("kicad2cnc.ui.dialog.wx.MessageBox", return_value=wx.YES),
            patch("kicad2cnc.ui.dialog.Thread") as thread,
        ):
            self.dialog.on_export()
        thread.return_value.start.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["args"][0], Path(r"C:\KiCad\kicad-cli.exe"))
        self.assertEqual(thread.call_args.kwargs["args"][1], Path(info.filename))
        self.assertTrue(self.dialog.exporting)
        self.assertFalse(self.dialog.export_button.IsEnabled())
        self.assertFalse(self.dialog.refresh.IsEnabled())
        event = Mock(spec=wx.CloseEvent)
        event.CanVeto.return_value = True
        self.dialog.on_close(event)
        event.Veto.assert_called_once()
        self.dialog.set_exporting(False)

    def test_cnc_mode_validates_converter_and_passes_settings_to_worker(self) -> None:
        info = self.load_saved_board()
        self.dialog.export_only.SetValue(False)
        self.dialog.kicad.get_kicad_binary_path.return_value = r"C:\KiCad\kicad-cli.exe"
        converter = Path(r"C:\CAM\pcb2gcode.exe")
        with (
            patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
            patch("kicad2cnc.ui.dialog.wx.MessageBox", return_value=wx.YES),
            patch("kicad2cnc.ui.dialog.find_converter", return_value=converter),
            patch("kicad2cnc.ui.dialog.Thread") as thread,
        ):
            self.dialog.on_export()
        self.assertEqual(thread.call_args.kwargs["args"][4:], (CncSettings(), converter))
        self.assertFalse(self.dialog.export_only.IsEnabled())
        self.assertFalse(self.dialog.settings_button.IsEnabled())
        self.dialog.set_exporting(False)

    def test_back_only_confirmation_explains_mirrored_single_setup(self) -> None:
        info = self.load_saved_board()
        self.dialog.export_only.SetValue(False)
        self.dialog.layers.SetCheckedStrings(["B.Cu", "Edge.Cuts"])
        self.dialog.kicad.get_kicad_binary_path.return_value = r"C:\KiCad\kicad-cli.exe"
        with (
            patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
            patch("kicad2cnc.ui.dialog.wx.MessageBox", return_value=wx.YES) as message,
            patch("kicad2cnc.ui.dialog.find_converter", return_value=Path("converter")),
            patch("kicad2cnc.ui.dialog.Thread") as thread,
        ):
            self.dialog.on_export()
        confirmation = message.call_args_list[1].args[0]
        self.assertIn("X-mirrored", confirmation)
        self.assertIn("B.Cu face upward", confirmation)
        self.assertIn("does not require flipping the board or drilling registration holes", confirmation)
        thread.return_value.start.assert_called_once()
        self.dialog.set_exporting(False)

    def test_cnc_missing_outline_or_converter_does_not_start_worker(self) -> None:
        info = self.load_saved_board()
        self.dialog.export_only.SetValue(False)
        for layers in (["F.Cu"], ["F.Cu", "Edge.Cuts"]):
            self.dialog.layers.SetCheckedStrings(layers)
            with (
                patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
                patch("kicad2cnc.ui.dialog.wx.MessageBox", return_value=wx.YES) as message,
                patch("kicad2cnc.ui.dialog.find_converter", side_effect=ValueError("Missing converter")),
                patch("kicad2cnc.ui.dialog.Thread") as thread,
            ):
                self.dialog.on_export()
            thread.assert_not_called()
            self.assertIn("Edge.Cuts" if layers == ["F.Cu"] else "Missing converter", message.call_args.args[0])

    def test_combined_drill_confirmation_warns_about_alternative_and_changed_sizes(self) -> None:
        info = self.load_saved_board()
        self.dialog.export_only.SetValue(False)
        self.dialog.cnc_settings = CncSettings(combined_drilling=True, combined_drill_diameter=0.6)
        with (
            patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
            patch("kicad2cnc.ui.dialog.wx.MessageBox", side_effect=[wx.YES, wx.NO]) as message,
            patch("kicad2cnc.ui.dialog.find_converter", return_value=Path("converter")),
            patch("kicad2cnc.ui.dialog.Thread") as thread,
        ):
            self.dialog.on_export()
        confirmation = message.call_args_list[1].args[0]
        self.assertIn("0.6 mm", confirmation)
        self.assertIn("changing designed diameters", confirmation)
        self.assertIn("INSTEAD OF", confirmation)
        thread.assert_not_called()

    def test_cancel_cnc_review_confirmation_does_not_start_worker(self) -> None:
        info = self.load_saved_board()
        self.dialog.export_only.SetValue(False)
        with (
            patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
            patch("kicad2cnc.ui.dialog.wx.MessageBox", side_effect=[wx.YES, wx.NO]),
            patch("kicad2cnc.ui.dialog.find_converter", return_value=Path("converter")),
            patch("kicad2cnc.ui.dialog.Thread") as thread,
        ):
            self.dialog.on_export()
        thread.assert_not_called()

    def test_cnc_worker_runs_conversion_inside_export_staging(self) -> None:
        result = ExportResult(Path("out"), (), "")
        converter = Path("converter")
        with (
            patch("kicad2cnc.ui.dialog.export_board", return_value=result) as export,
            patch("kicad2cnc.ui.dialog.wx.CallAfter") as callback,
        ):
            self.dialog.run_export(Path("cli"), Path("board"), Path("out"), ("F.Cu",), CncSettings(), converter)
        self.assertIn("convert", export.call_args.kwargs)
        callback.assert_called_once_with(self.dialog.finish_export, result, "")

    def test_settings_dialog_accepts_numeric_values_and_operations(self) -> None:
        with CncSettingsDialog(self.dialog, CncSettings()) as settings:
            settings.values["mill_feed"].ChangeValue("180")
            settings.values["bridge_count"].ChangeValue("6")
            settings.operations["outline"].SetValue(False)
            settings.operations["registration"].SetValue(True)
            settings.operations["combined_drilling"].SetValue(True)
            settings.values["combined_drill_diameter"].ChangeValue("0.6")
            settings.values["registration_hole_diameter"].ChangeValue("2.5")
            settings.values["registration_positions"].ChangeValue("5, -2\n-5, -2")
            with patch.object(settings, "EndModal") as end:
                settings.on_ok(Mock(spec=wx.CommandEvent))
            end.assert_called_once_with(wx.ID_OK)
            self.assertEqual(settings.settings.mill_feed, 180.0)
            self.assertEqual(settings.settings.bridge_count, 6)
            self.assertFalse(settings.settings.outline)
            self.assertTrue(settings.settings.registration)
            self.assertTrue(settings.settings.combined_drilling)
            self.assertEqual(settings.settings.combined_drill_diameter, 0.6)
            self.assertEqual(settings.settings.registration_hole_diameter, 2.5)
            self.assertEqual(settings.settings.registration_positions, "5, -2\n-5, -2")

    def test_settings_dialog_rejects_invalid_values_without_closing(self) -> None:
        with CncSettingsDialog(self.dialog, CncSettings()) as settings:
            settings.values["safe_z"].ChangeValue("-1")
            with (
                patch.object(settings, "EndModal") as end,
                patch("kicad2cnc.ui.settings_dialog.wx.MessageBox") as message,
            ):
                settings.on_ok(Mock(spec=wx.CommandEvent))
            end.assert_not_called()
            message.assert_called_once()
            self.assertEqual(settings.settings, CncSettings())

    def test_settings_load_failure_is_visible_and_blocks_conversion(self) -> None:
        info = BoardInfo(r"C:\boards\saved.kicad_pcb", ("F.Cu", "Edge.Cuts"), True, "10.0.7")
        with (
            patch("kicad2cnc.ui.dialog.read_board_info", return_value=info),
            patch("kicad2cnc.ui.dialog.load_settings", side_effect=ValueError("Invalid JSON")),
            patch("kicad2cnc.ui.dialog.wx.MessageBox") as message,
            self.assertLogs(level="ERROR"),
        ):
            self.dialog.refresh_board()
        self.assertIn("Invalid JSON", self.dialog.settings_error)
        self.assertIn("Could not load CNC settings", message.call_args.args[0])
        self.assertTrue(self.dialog.export_button.IsEnabled())

    def test_worker_failure_is_logged_and_forwarded_to_ui(self) -> None:
        with (
            patch("kicad2cnc.ui.dialog.export_board", side_effect=OSError("Disk full")),
            patch("kicad2cnc.ui.dialog.wx.CallAfter") as callback,
            self.assertLogs(level="ERROR"),
        ):
            self.dialog.run_export(Path("cli"), Path("board"), Path("out"), ("F.Cu",))
        callback.assert_called_once_with(self.dialog.finish_export, None, "Disk full")

    def test_export_completion_and_failure_restore_controls(self) -> None:
        self.load_saved_board()
        output = Path(r"C:\output\job")
        result = ExportResult(output, (output / "front.gbr",), "CLI output")
        self.dialog.set_exporting(True)
        self.dialog.finish_export(result, "")
        self.assertIn("Export complete", self.dialog.log.GetValue())
        self.assertIn("front.gbr", self.dialog.log.GetValue())
        self.assertTrue(self.dialog.export_button.IsEnabled())
        self.dialog.set_exporting(True)
        with patch("kicad2cnc.ui.dialog.wx.MessageBox") as message:
            self.dialog.finish_export(None, "CLI failed")
        message.assert_called_once()
        self.assertEqual(self.dialog.log.GetValue(), "CLI failed")
        self.assertFalse(self.dialog.exporting)

    def test_connection_errors_clear_stale_data_and_allow_retry(self) -> None:
        for error in (ApiError("No board"), Timeout("Editor did not reply", lib.NNG_ETIMEDOUT)):
            with self.subTest(error=type(error).__name__):
                self.dialog.filename.ChangeValue("stale board")
                self.dialog.layers.Set(["F.Cu"])
                with (
                    patch("kicad2cnc.ui.dialog.read_board_info", side_effect=error),
                    patch("kicad2cnc.ui.dialog.wx.MessageBox") as message,
                    self.assertLogs(level="ERROR"),
                ):
                    self.dialog.refresh_board()
                self.assertEqual(self.dialog.filename.GetValue(), "")
                self.assertEqual(self.dialog.layers.GetCount(), 0)
                self.assertTrue(self.dialog.refresh.IsEnabled())
                message.assert_called_once()
                self.assertIn(str(error), message.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
