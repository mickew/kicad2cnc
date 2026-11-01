from dataclasses import asdict

import wx

from kicad2cnc.settings import CncSettings


class CncSettingsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, settings: CncSettings) -> None:
        super().__init__(parent, title="CNC settings - millimetres, mm/min, RPM")
        self.settings = settings
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(
            wx.StaticText(self, label="Example parameters only: verify them for your machine, tools, and stock."),
            0, wx.ALL, 12,
        )
        self.executable = wx.FilePickerCtrl(
            self, path=settings.executable, message="Select pcb2gcode executable",
            style=wx.FLP_OPEN | wx.FLP_USE_TEXTCTRL | wx.FLP_FILE_MUST_EXIST,
        )
        layout.Add(wx.StaticText(self, label="pcb2gcode executable (blank = auto-discover)"), 0, wx.LEFT, 12)
        layout.Add(self.executable, 0, wx.EXPAND | wx.ALL, 12)
        notebook = wx.Notebook(self)
        self.operations: dict[str, wx.CheckBox] = {}
        self.values: dict[str, wx.TextCtrl] = {}
        groups = (
            ("Common", "", (
                ("spindle", "Spindle RPM"), ("safe_z", "Safe Z (mm)"),
                ("change_z", "Tool-change Z (mm)"), ("plunge_feed", "Plunge feed (mm/min)"),
                ("spinup_time", "Spindle spin-up dwell (seconds)"),
                ("spindown_time", "Spindle shutdown dwell (seconds)"),
            )),
            ("Isolation", "isolation", (
                ("mill_diameter", "Effective tool diameter (mm)"),
                ("isolation_width", "Isolation width (mm)"), ("overlap", "Overlap (%)"),
                ("mill_depth", "Depth (negative mm)"), ("mill_feed", "Feed (mm/min)"),
            )),
            ("Drill", "drilling", (
                ("drill_depth", "Depth (negative mm)"), ("drill_feed", "Feed (mm/min)"),
                ("milldrill_threshold", "Mill-drill hole threshold (mm; 0 = disabled)"),
                ("combined_drill_diameter", "Single-diameter alternative: drill diameter (mm)"),
            )),
            ("Outline", "outline", (
                ("cutter_diameter", "Cutter diameter (mm)"), ("cut_depth", "Depth (negative mm)"),
                ("cut_infeed", "Maximum depth per pass (mm)"), ("cut_feed", "Feed (mm/min)"),
                ("bridge_width", "Tab width (mm; 0 = no tabs)"),
                ("bridge_count", "Number of tabs"), ("bridge_z", "Tab top Z (negative mm)"),
            )),
            ("Registration", "registration", (
                ("registration_hole_diameter", "Registration-hole diameter (mm)"),
                ("registration_positions", "Hole centers in drill/place coordinates (X,Y mm; one per line)"),
            )),
        )
        defaults = asdict(settings)
        for title, operation, entries in groups:
            panel = wx.Panel(notebook)
            content = wx.BoxSizer(wx.VERTICAL)
            if operation:
                label = (
                    "Generate registration-hole drilling operation"
                    if operation == "registration"
                    else f"Generate {title.lower()} G-code"
                )
                check = wx.CheckBox(panel, label=label)
                check.SetValue(defaults[operation])
                self.operations[operation] = check
                content.Add(check, 0, wx.ALL, 10)
            if operation == "drilling":
                check = wx.CheckBox(panel, label="Also generate one file for all board holes using one drill size")
                check.SetValue(settings.combined_drilling)
                self.operations["combined_drilling"] = check
                content.Add(check, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
                content.Add(
                    wx.StaticText(panel, label=(
                        "Alternative to the normal drill/mill-drill files, not an extra pass. "
                        "Changes all board hole diameters to the selected diameter. "
                        "Registration holes remain separate."
                    )),
                    0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12,
                )
            if operation == "registration":
                content.Add(
                    wx.StaticText(
                        panel,
                        label=(
                            "Enter 2-4 unique X,Y centers. They must be symmetric about X=0 "
                            "for the Y-axis flip. Holes are drilled through the PCB; verify "
                            "Edge.Cuts, copper, components, and clamps yourself."
                        ),
                    ),
                    0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12,
                )
            grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=12)
            grid.AddGrowableCol(1)
            for key, label in entries:
                grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
                if key == "registration_positions":
                    control = wx.TextCtrl(
                        panel, value=str(defaults[key]), style=wx.TE_MULTILINE,
                        size=wx.Size(-1, 84),
                    )
                else:
                    control = wx.TextCtrl(panel, value=str(defaults[key]))
                self.values[key] = control
                grid.Add(control, 1, wx.EXPAND)
            content.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
            panel.SetSizer(content)
            notebook.AddPage(panel, title)
        layout.Add(notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        layout.Add(buttons, 0, wx.EXPAND | wx.ALL, 12)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.SetSizerAndFit(layout)
        self.CentreOnParent()

    def on_ok(self, event: wx.CommandEvent) -> None:
        try:
            data = asdict(self.settings)
            data["executable"] = self.executable.GetPath().strip()
            for name, check in self.operations.items():
                data[name] = check.GetValue()
            for name, control in self.values.items():
                value = control.GetValue().strip()
                if name == "registration_positions":
                    data[name] = value
                else:
                    data[name] = int(value) if name in ("spindle", "bridge_count") else float(value)
            settings = CncSettings(**data)
            settings.validate()
        except ValueError as error:
            wx.MessageBox(str(error), "Invalid CNC settings", wx.OK | wx.ICON_ERROR, self)
            return
        self.settings = settings
        self.EndModal(wx.ID_OK)
