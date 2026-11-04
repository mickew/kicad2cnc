from dataclasses import asdict

import wx

from kicad2cnc.settings import CncSettings
from kicad2cnc.ui import set_dialog_icon


SETTING_TOOLTIPS = {
    "executable": (
        "Path to pcb2gcode.exe, which converts exported Gerber/Excellon files to toolpaths. "
        "Leave blank to search PATH and the plugin's standard local tool installation."
    ),
    "bcnc_tool_changes": (
        "Also create bCNC programs with T/M6 manual tool changes; per-tool GRBL files remain available. "
        "Use bCNC's Manual tool change (WCS) or (No Probe) policy, not TLO, skip, or send M6 to GRBL. "
        "Set/probe Z0 after each change. Board flips still require separate setups."
    ),
    "bcnc_operations": (
        "All operations combines the enabled operations per physical setup. Drills only combines "
        "registration and board drill/mill-drill operations and copies isolation/outline as separate files. "
        "Registration runs first; board drill tools follow in ascending diameter. "
        "The single-diameter drill alternative is excluded."
    ),
    "isolation": (
        "Generate copper-isolation toolpaths from the selected F.Cu and/or B.Cu layers. "
        "Select the copper layers to machine in the export window."
    ),
    "drilling": (
        "Generate board-hole drilling from the exported plated and non-plated Excellon files, "
        "using their specified tool sizes unless mill-drilling is enabled. Registration is separate."
    ),
    "combined_drilling": (
        "Also generate an alternative file using one drill diameter for all board holes. "
        "Run it instead of the normal drill/mill-drill files, not in addition. "
        "This changes hole sizes and slot widths; registration holes are excluded."
    ),
    "combined_drill_diameter": (
        "Drill diameter in mm for the optional single-diameter board-hole alternative. "
        "Must be positive. Normal per-tool files keep their original sizes."
    ),
    "outline": (
        "Generate board-profile cutting from the selected Edge.Cuts layer, using the outline cutter, "
        "depth-per-pass and tab settings. Keep the board secured throughout cutting."
    ),
    "registration": (
        "Generate a separate registration-hole operation before board machining. "
        "Enter symmetric centers and verify hole clearance and pin fit yourself; "
        "the plugin does not design or check a fixture."
    ),
    "registration_hole_diameter": (
        "Registration drill diameter in mm. Choose a positive diameter suitable for your alignment pins; "
        "these holes are independent of the board's Excellon hole sizes."
    ),
    "registration_depth": (
        "Final registration-hole Z in mm relative to the PCB surface Z=0; use a negative value. "
        "Independent of board-drill depth. Verify pin engagement and clearance into the spoilboard."
    ),
    "registration_positions": (
        "Enter 2-4 unique hole centers, one X,Y pair per line in mm, using exported drill/place-origin "
        "coordinates. Example: -10, 5 and 10, 5 on separate lines. Centers must be symmetric "
        "about X=0 for a flip about the Y axis. Check copper, board edges, components and clamps."
    ),
    "mill_diameter": (
        "Effective copper-isolation cutting width in mm, not necessarily the tool's shank diameter. "
        "For a V-bit, use its cutting width at the chosen depth. Must be positive."
    ),
    "isolation_width": (
        "Requested copper-isolation width in mm. pcb2gcode may generate multiple offset passes "
        "to reach this width; actual removal also depends on tool diameter and overlap. Cannot be negative."
    ),
    "overlap": (
        "Overlap between adjacent isolation passes as a percentage of tool width, from 0 to less than 100. "
        "Higher values reduce pass spacing and can increase machining time."
    ),
    "mill_depth": (
        "Copper-isolation cutting Z in mm relative to the PCB surface Z=0; use a negative value. "
        "Cut deep enough to remove copper without unnecessarily cutting into the substrate."
    ),
    "mill_feed": "Horizontal copper-isolation feed rate in mm/min. Use a positive rate suitable for the tool and PCB.",
    "plunge_feed": (
        "Vertical milling plunge feed in mm/min for isolation and outline-based milling. "
        "Board and registration drilling use the separate drill feed. Must be positive."
    ),
    "spindle": (
        "Commanded spindle speed in RPM for all generated operations. Must be a positive integer. "
        "Verify your controller's speed scaling and the tool's permitted speed."
    ),
    "spinup_time": (
        "Pause in seconds after starting the spindle, before cutting, to let it reach speed. "
        "Allowed range: 0-600 seconds."
    ),
    "spindown_time": (
        "Pause in seconds after stopping the spindle, allowing it to slow before the next step "
        "or tool change. Allowed range: 0-600 seconds; verify it has actually stopped."
    ),
    "safe_z": (
        "Retract/travel height in mm above the PCB surface Z=0, in work coordinates. "
        "Must be positive and clear the board and fixtures; the plugin cannot check clamp heights."
    ),
    "change_z": (
        "Tool-change height in mm above the PCB surface, in work coordinates. "
        "Must be at least Safe Z and within machine travel. This does not configure bCNC's "
        "machine-coordinate tool-change or probing positions."
    ),
    "drill_depth": (
        "Final board-hole drilling and mill-drilling Z in mm relative to the PCB surface Z=0; "
        "use a negative value deep enough for the board and drill tip. Also used by the "
        "single-diameter alternative, but not registration. Check clearance below the board."
    ),
    "drill_feed": (
        "Vertical drilling feed rate in mm/min for board holes, the single-diameter alternative "
        "and registration holes. Must be positive."
    ),
    "cutter_diameter": (
        "Positive end-mill diameter in mm for outline cutting and optional mill-drilling. "
        "Toolpaths compensate for this diameter; it must match the installed cutter."
    ),
    "cut_depth": (
        "Final outline-cutting Z in mm relative to the PCB surface Z=0; use a negative value. "
        "Choose enough depth to separate the board, allowing for thickness and spoilboard clearance."
    ),
    "cut_infeed": (
        "Maximum outline-based milling depth per pass in mm; must be positive. "
        "Deeper cuts are split into passes. Smaller values reduce cutting load but take longer."
    ),
    "cut_feed": "Horizontal outline and mill-drilling feed rate in mm/min. Must be positive and suitable for the cutter.",
    "bridge_width": (
        "Width in mm of holding tabs left along the outline to keep the board attached. "
        "Set width or tab count to 0 to disable tabs; otherwise remove tabs after machining."
    ),
    "bridge_count": (
        "Requested number of holding tabs around the outline, as a non-negative integer. "
        "Set to 0 to disable tabs. Inspect generated placement and ensure the board stays secured."
    ),
    "bridge_z": (
        "Z level in mm at the top of outline tabs, relative to PCB surface Z=0. "
        "With tabs enabled, it must be negative but above the final outline depth. "
        "A value closer to zero leaves thicker tabs."
    ),
    "milldrill_threshold": (
        "Board holes at or above this diameter in mm are milled using the outline cutter "
        "instead of drilled. Set 0 to disable; otherwise it must exceed the cutter diameter. "
        "Uses board-drill depth and outline milling feeds. Registration and the single-size alternative are unaffected."
    ),
}


class CncSettingsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, settings: CncSettings) -> None:
        super().__init__(parent, title="CNC settings - millimetres, mm/min, RPM")
        set_dialog_icon(self, "settings.png")
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
        executable_label = wx.StaticText(self, label="pcb2gcode executable (blank = auto-discover)")
        executable_label.SetToolTip(SETTING_TOOLTIPS["executable"])
        self.executable.SetToolTip(SETTING_TOOLTIPS["executable"])
        layout.Add(executable_label, 0, wx.LEFT, 12)
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
                ("registration_depth", "Registration depth (negative mm; PCB surface Z=0)"),
                ("registration_positions", "Hole centers in drill/place coordinates (X,Y mm; one per line)"),
            )),
        )
        defaults = asdict(settings)
        for title, operation, entries in groups:
            panel = wx.Panel(notebook)
            content = wx.BoxSizer(wx.VERTICAL)
            if title == "Common":
                check = wx.CheckBox(panel, label="Also generate bCNC programs with manual tool changes (T/M6)")
                check.SetValue(settings.bcnc_tool_changes)
                check.SetToolTip(SETTING_TOOLTIPS["bcnc_tool_changes"])
                self.operations["bcnc_tool_changes"] = check
                content.Add(check, 0, wx.ALL, 10)
                bcnc_label = wx.StaticText(panel, label="bCNC program contents")
                bcnc_label.SetToolTip(SETTING_TOOLTIPS["bcnc_operations"])
                content.Add(bcnc_label, 0, wx.LEFT, 12)
                self.bcnc_operations = wx.Choice(panel, choices=["All operations", "Drills only"])
                self.bcnc_operations.SetToolTip(SETTING_TOOLTIPS["bcnc_operations"])
                self.bcnc_operations.SetSelection(0 if settings.bcnc_operations == "all" else 1)
                content.Add(self.bcnc_operations, 0, wx.EXPAND | wx.ALL, 12)
                notice = wx.StaticText(panel, label=(
                    "Requires bCNC manual tool-change WCS or No Probe policy; never skip/send M6. "
                    "Set/probe Z0 at each change. Board flips remain separate programs. "
                    "Normal tool sizes are used; single-size drill alternative is excluded."
                    " Board drill/mill-drill tools are sorted by ascending diameter; registration stays first."
                ))
                notice.Wrap(560)
                content.Add(notice, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
            if operation:
                label = (
                    "Generate registration-hole drilling operation"
                    if operation == "registration"
                    else f"Generate {title.lower()} G-code"
                )
                check = wx.CheckBox(panel, label=label)
                check.SetValue(defaults[operation])
                check.SetToolTip(SETTING_TOOLTIPS[operation])
                self.operations[operation] = check
                content.Add(check, 0, wx.ALL, 10)
            if operation == "drilling":
                check = wx.CheckBox(panel, label="Also generate one file for all board holes using one drill size")
                check.SetValue(settings.combined_drilling)
                check.SetToolTip(SETTING_TOOLTIPS["combined_drilling"])
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
                            "for the Y-axis flip. Choose sufficient depth for the intended pin fit; verify "
                            "Edge.Cuts, copper, components, and clamps yourself."
                        ),
                    ),
                    0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12,
                )
            grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=12)
            grid.AddGrowableCol(1)
            for key, label in entries:
                field_label = wx.StaticText(panel, label=label)
                field_label.SetToolTip(SETTING_TOOLTIPS[key])
                grid.Add(field_label, 0, wx.ALIGN_CENTER_VERTICAL)
                if key == "registration_positions":
                    control = wx.TextCtrl(
                        panel, value=str(defaults[key]), style=wx.TE_MULTILINE,
                        size=wx.Size(-1, 84),
                    )
                else:
                    control = wx.TextCtrl(panel, value=str(defaults[key]))
                self.values[key] = control
                control.SetToolTip(SETTING_TOOLTIPS[key])
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
            data["bcnc_operations"] = ("all", "drills")[self.bcnc_operations.GetSelection()]
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
