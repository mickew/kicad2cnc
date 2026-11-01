import logging
from pathlib import Path
from threading import Thread
from functools import partial

import wx
from kipy import KiCad
from kipy.errors import ApiError
from pynng import NNGException

from kicad2cnc.board_info import BoardInfo, read_board_info
from kicad2cnc.export import ExportResult, export_board
from kicad2cnc.gcode import generate_gcode
from kicad2cnc.settings import CncSettings, find_converter, load_settings, save_settings
from kicad2cnc.ui.settings_dialog import CncSettingsDialog


class BoardInfoDialog(wx.Dialog):
    def __init__(self, kicad: KiCad) -> None:
        super().__init__(
            None,
            title="KiCad to CNC - Board information",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.kicad = kicad
        self.info: BoardInfo | None = None
        self.exporting = False
        self.cnc_settings = CncSettings()
        self.settings_error = ""
        self.Bind(wx.EVT_CLOSE, self.on_close)
        layout = wx.BoxSizer(wx.VERTICAL)
        heading = wx.StaticText(self, label="KiCad to CNC")
        heading.SetFont(heading.GetFont().Bold())
        layout.Add(heading, 0, wx.ALL, 12)
        layout.Add(
            wx.StaticText(
                self,
                label="M4: GRBL per-tool files. Simulate, verify setup, and dry-run before machining.",
            ),
            0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12,
        )
        self.status = wx.StaticText(self, label="Connecting to the PCB Editor...")
        layout.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        layout.Add(wx.StaticText(self, label="Board file"), 0, wx.LEFT | wx.RIGHT, 12)
        self.filename = wx.TextCtrl(self, style=wx.TE_READONLY)
        layout.Add(self.filename, 0, wx.EXPAND | wx.ALL, 12)
        self.layer_label = wx.StaticText(self, label="Enabled layers")
        layout.Add(self.layer_label, 0, wx.LEFT | wx.RIGHT, 12)
        self.layers = wx.CheckListBox(self, size=(-1, 130))
        layout.Add(self.layers, 1, wx.EXPAND | wx.ALL, 12)
        self.notice = wx.StaticText(self, label="")
        self.notice.SetMinSize((560, 64))
        layout.Add(self.notice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        layout.Add(
            wx.StaticText(self, label="Export directory (each export creates a new job folder)"),
            0, wx.LEFT | wx.RIGHT, 12,
        )
        self.output = wx.DirPickerCtrl(self, style=wx.DIRP_USE_TEXTCTRL)
        layout.Add(self.output, 0, wx.EXPAND | wx.ALL, 12)
        mode = wx.BoxSizer(wx.HORIZONTAL)
        self.export_only = wx.CheckBox(self, label="Export only (no G-code)")
        self.export_only.SetValue(True)
        mode.Add(self.export_only, 0, wx.ALIGN_CENTER_VERTICAL)
        self.settings_button = wx.Button(self, label="CNC settings...")
        self.settings_button.Bind(wx.EVT_BUTTON, self.on_settings)
        mode.Add(self.settings_button, 0, wx.LEFT, 12)
        layout.Add(mode, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.log = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100))
        layout.Add(self.log, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.refresh = wx.Button(self, label="Refresh board information")
        self.refresh.Bind(wx.EVT_BUTTON, self.refresh_board)
        buttons.Add(self.refresh)
        self.export_button = wx.Button(self, label="Export")
        self.export_button.Disable()
        self.export_button.Bind(wx.EVT_BUTTON, self.on_export)
        buttons.Add(self.export_button, 0, wx.LEFT, 8)
        buttons.AddStretchSpacer()
        close = wx.Button(self, wx.ID_CANCEL, label="Close")
        close.Bind(wx.EVT_BUTTON, lambda event: self.Close())
        close.SetDefault()
        buttons.Add(close)
        layout.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizerAndFit(layout)
        self.SetMinSize(self.GetSize())
        self.Centre()

    def refresh_board(self, event: wx.CommandEvent | None = None) -> None:
        previous = self.info
        checked = self.layers.GetCheckedStrings()
        self.refresh.Disable()
        try:
            with wx.BusyCursor():
                info = read_board_info(self.kicad)
        except (ApiError, NNGException, OSError, RuntimeError, ValueError) as error:
            logging.exception("Could not read the open PCB")
            self.status.SetLabel("Not connected to an open KiCad 10 board.")
            self.info = None
            self.export_button.Disable()
            self.filename.Clear()
            self.layers.Clear()
            self.layer_label.SetLabel("Enabled layers")
            self.notice.SetLabel("Board information is unavailable. Correct the error and refresh.")
            wx.MessageBox(
                "Could not read the open PCB.\n\n"
                "Open a board in KiCad 10's PCB Editor, enable Preferences > "
                "Preferences > Plugins > Enable API server, and launch the action "
                "from that editor.\n\n"
                f"Details: {error}",
                "KiCad to CNC - Connection error",
                wx.OK | wx.ICON_ERROR,
                self,
            )
        else:
            self.info = info
            if previous is None or previous.filename != info.filename:
                self.settings_error = ""
                self.cnc_settings = CncSettings()
                if info.saved_file_exists:
                    try:
                        self.cnc_settings = load_settings(Path(info.filename))
                    except (OSError, ValueError, TypeError) as error:
                        self.settings_error = str(error)
                        logging.exception("Could not load CNC settings")
                        wx.MessageBox(
                            f"Could not load CNC settings: {error}\n\n"
                            "Export-only is still available. Open CNC settings to correct and save them.",
                            "KiCad to CNC - Settings error", wx.OK | wx.ICON_ERROR, self,
                        )
            self.status.SetLabel(f"Connected to KiCad {info.version}")
            self.filename.ChangeValue(info.filename)
            self.layers.Set(list(info.layers))
            defaults = checked if previous and previous.filename == info.filename else (
                "F.Cu", "B.Cu", "Edge.Cuts"
            )
            self.layers.SetCheckedStrings([layer for layer in defaults if layer in info.layers])
            self.layer_label.SetLabel(f"Enabled layers ({len(info.layers)})")
            self.notice.SetLabel(info.save_notice)
            self.export_button.Enable(info.saved_file_exists)
            if not self.output.GetPath() or (previous and previous.filename != info.filename):
                if info.saved_file_exists:
                    self.output.SetPath(str(Path(info.filename).parent / "cnc"))
        finally:
            self.notice.Wrap(560)
            self.refresh.Enable()
            self.Layout()

    def on_close(self, event: wx.CloseEvent) -> None:
        if self.exporting:
            if event.CanVeto():
                event.Veto()
            return
        self.Destroy()

    def on_export(self, event: wx.CommandEvent | None = None) -> None:
        self.refresh_board()
        info = self.info
        if info is None or not info.saved_file_exists:
            return
        layers = tuple(self.layers.GetCheckedStrings())
        directory = self.output.GetPath().strip()
        if not layers or not directory or not Path(directory).is_absolute():
            wx.MessageBox(
                "Select at least one Gerber layer and an absolute output directory.",
                "KiCad to CNC - Export settings", wx.OK | wx.ICON_ERROR, self,
            )
            return
        confirmed = wx.MessageBox(
            "Have you saved the board in the PCB Editor?\n\n"
            "This exports the saved file, not unsaved editor changes. Both Gerbers "
            "and drills use the drill/place origin. No files are overwritten.\n\n"
            "Continue with the saved board?",
            "KiCad to CNC - Confirm saved board",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self,
        )
        if confirmed != wx.YES:
            return
        cnc = None
        converter = None
        if not self.export_only.GetValue():
            try:
                if self.settings_error:
                    raise ValueError(f"Correct CNC settings before conversion: {self.settings_error}")
                self.cnc_settings.validate()
                if self.cnc_settings.isolation and not any(side in layers for side in ("F.Cu", "B.Cu")):
                    raise ValueError("Select F.Cu or B.Cu for isolation, or disable isolation in CNC settings.")
                if self.cnc_settings.outline and "Edge.Cuts" not in layers:
                    raise ValueError("Select Edge.Cuts for outline cutting, or disable outline in CNC settings.")
                converter = find_converter(self.cnc_settings.executable)
                cnc = self.cnc_settings
            except ValueError as error:
                wx.MessageBox(str(error), "KiCad to CNC - CNC settings", wx.OK | wx.ICON_ERROR, self)
                return
            back_only = "B.Cu" in layers and "F.Cu" not in layers
            if back_only:
                review_message = (
                    "Only B.Cu is selected: generated drilling and outline toolpaths will be "
                    "X-mirrored to match the back-copper isolation paths. Machine with "
                    "the B.Cu face upward; this single-sided setup does not require "
                    "flipping the board or drilling registration holes.\n\n"
                )
            else:
                review_message = (
                    "Back copper is mirrored about X=0; for a double-sided job, the "
                    "matching physical flip is 180 degrees about the Y axis. Optional "
                    "registration holes are manual through-holes, not a fixture or "
                    "automatic alignment system; verify their clearance.\n\n"
                )
            if cnc.combined_drilling:
                review_message += (
                    f"Single-diameter alternative enabled: {cnc.combined_drill_diameter:g} mm "
                    "for ALL board holes, changing designed diameters. Run the combined file "
                    "INSTEAD OF normal board drill/mill-drill files, not in addition. "
                    "Registration holes remain separate.\n\n"
                )
            if wx.MessageBox(
                "The exporter generates separate files for GRBL v1.1's supported command subset, "
                "but does not verify your controller, machine, or work setup.\n\n"
                "You must manually change tools and re-set/probe Z0 between files. "
                + review_message
                + "Verify toolpaths, work origin, travel, and workholding. Simulate and "
                "dry-run above the stock before cutting. Continue?",
                "KiCad to CNC - Verify GRBL setup",
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self,
            ) != wx.YES:
                return
        try:
            cli = Path(self.kicad.get_kicad_binary_path("kicad-cli"))
        except (ApiError, NNGException, OSError, RuntimeError) as error:
            logging.exception("Could not locate KiCad CLI")
            wx.MessageBox(str(error), "KiCad to CNC - CLI error", wx.OK | wx.ICON_ERROR, self)
            return
        self.set_exporting(True)
        self.log.ChangeValue("Exporting Gerbers and Excellon drill files...\n")
        Thread(
            target=self.run_export,
            args=(cli, Path(info.filename), Path(directory), layers, cnc, converter),
            daemon=True,
        ).start()

    def set_exporting(self, active: bool) -> None:
        self.exporting = active
        for control in (self.refresh, self.layers, self.output, self.export_only, self.settings_button):
            control.Enable(not active)
        self.export_button.Enable(not active and self.info is not None and self.info.saved_file_exists)

    def run_export(
        self, cli: Path, board: Path, output: Path, layers: tuple[str, ...],
        cnc: CncSettings | None = None, converter: Path | None = None,
    ) -> None:
        try:
            if cnc is None:
                result = export_board(cli, board, output, layers)
            else:
                if converter is None:
                    raise ValueError("No pcb2gcode executable selected.")
                convert = partial(
                    generate_gcode, executable=converter, settings=cnc,
                    report=lambda text: wx.CallAfter(self.log.AppendText, text),
                )
                result = export_board(cli, board, output, layers, convert=convert)
        except Exception as error:
            # Worker exceptions must reach the UI rather than disappear in a thread.
            logging.exception("PCB export failed")
            wx.CallAfter(self.finish_export, None, str(error))
        else:
            wx.CallAfter(self.finish_export, result, "")

    def finish_export(self, result: ExportResult | None, error: str) -> None:
        self.set_exporting(False)
        if result is None:
            self.log.ChangeValue(error)
            wx.MessageBox(
                error, "KiCad to CNC - Export failed", wx.OK | wx.ICON_ERROR, self,
            )
        else:
            if any(path.suffix == ".nc" for path in result.files):
                review = " - GRBL files generated; verify before use"
            elif any(path.suffix == ".ngc" for path in result.files):
                review = " - CAM review required"
            else:
                review = ""
            self.log.ChangeValue(
                f"Export complete{review}: {result.directory}\n\n"
                + "\n".join(str(path.relative_to(result.directory)) for path in result.files)
                + "\n\n" + result.log
            )
            self.log.SetInsertionPoint(0)

    def on_settings(self, event: wx.CommandEvent | None = None) -> None:
        with CncSettingsDialog(self, self.cnc_settings) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                if self.info is not None and self.info.saved_file_exists:
                    save_settings(Path(self.info.filename), dialog.settings)
            except (OSError, ValueError) as error:
                logging.exception("Could not save CNC settings")
                wx.MessageBox(str(error), "KiCad to CNC - Settings error", wx.OK | wx.ICON_ERROR, self)
                return
            self.cnc_settings = dialog.settings
            self.settings_error = ""
