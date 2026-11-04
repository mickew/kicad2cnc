import json
import math
import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from kicad2cnc.registration import parse_registration_positions


@dataclass(frozen=True)
class CncSettings:
    executable: str = ""
    bcnc_tool_changes: bool = False
    bcnc_operations: str = "all"
    isolation: bool = True
    drilling: bool = True
    combined_drilling: bool = False
    combined_drill_diameter: float = 0.8
    outline: bool = True
    registration: bool = False
    registration_hole_diameter: float = 2.0
    registration_depth: float = -1.8
    registration_positions: str = ""
    mill_diameter: float = 0.2
    isolation_width: float = 0.2
    overlap: float = 50.0
    mill_depth: float = -0.05
    mill_feed: float = 120.0
    plunge_feed: float = 60.0
    spindle: int = 10000
    spinup_time: float = 1.0
    spindown_time: float = 1.0
    safe_z: float = 3.0
    change_z: float = 10.0
    drill_depth: float = -1.8
    drill_feed: float = 80.0
    cutter_diameter: float = 1.0
    cut_depth: float = -1.8
    cut_infeed: float = 0.4
    cut_feed: float = 100.0
    bridge_width: float = 1.0
    bridge_count: int = 4
    bridge_z: float = -1.0
    milldrill_threshold: float = 0.0

    def validate(self) -> None:
        defaults = asdict(CncSettings())
        values = asdict(self)
        for key, value in values.items():
            default = defaults[key]
            if type(value) is not type(default):
                raise ValueError(f"Invalid type for CNC setting: {key}")
            if isinstance(value, (float, int)) and not isinstance(value, bool):
                if not math.isfinite(value):
                    raise ValueError(f"CNC setting must be finite: {key}")
        if not any((self.isolation, self.drilling, self.outline, self.registration)):
            raise ValueError("Select at least one CNC operation.")
        if self.bcnc_operations not in ("all", "drills"):
            raise ValueError("bCNC operations must be all or drills.")
        if self.bcnc_tool_changes and self.bcnc_operations == "drills" and not (
            self.drilling or self.registration
        ):
            raise ValueError("Enable drilling or registration for drills-only bCNC output.")
        for name in (
            "mill_diameter", "mill_feed", "plunge_feed", "spindle", "safe_z",
            "change_z", "drill_feed", "cutter_diameter", "cut_infeed", "cut_feed",
        ):
            if values[name] <= 0:
                raise ValueError(f"{name} must be greater than zero.")
        if any(value >= 0 for value in (
            self.mill_depth, self.drill_depth, self.cut_depth, self.registration_depth,
        )):
            raise ValueError("Cutting depths must be negative, relative to the PCB surface Z=0.")
        if not 0 <= self.overlap < 100:
            raise ValueError("Overlap must be at least 0 and less than 100 percent.")
        if min(self.isolation_width, self.bridge_width, self.bridge_count, self.milldrill_threshold) < 0:
            raise ValueError("Isolation width, bridge sizes/count, and mill-drill threshold cannot be negative.")
        if self.change_z < self.safe_z:
            raise ValueError("Tool-change Z must be at least safe Z.")
        if not 0 <= self.spinup_time <= 600 or not 0 <= self.spindown_time <= 600:
            raise ValueError("Spindle spin-up and shutdown dwell must be between 0 and 600 seconds.")
        if self.bridge_width > 0 and self.bridge_count > 0 and not self.cut_depth < self.bridge_z < 0:
            raise ValueError("Bridge Z must be above the outline depth and below the PCB surface.")
        if self.milldrill_threshold and self.milldrill_threshold <= self.cutter_diameter:
            raise ValueError("Mill-drill threshold must exceed the cutter diameter.")
        if self.combined_drilling:
            if not self.drilling:
                raise ValueError("Enable drilling to generate the additional single-diameter drill file.")
            if self.combined_drill_diameter <= 0:
                raise ValueError("Combined drill diameter must be greater than zero.")
        if self.registration:
            if self.registration_hole_diameter <= 0:
                raise ValueError("Registration-hole diameter must be greater than zero.")
            parse_registration_positions(self.registration_positions)


def settings_path(board: Path) -> Path:
    return board.with_suffix(".kicad2cnc.json")


def load_settings(board: Path) -> CncSettings:
    path = settings_path(board)
    if not path.exists():
        return CncSettings()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {field.name for field in fields(CncSettings)}:
        raise ValueError(f"Invalid CNC settings file: {path}")
    if "registration_depth" not in data:
        data["registration_depth"] = data.get("drill_depth", CncSettings().drill_depth)
    settings = CncSettings(**data)
    settings.validate()
    return settings


def save_settings(board: Path, settings: CncSettings) -> None:
    settings.validate()
    settings_path(board).write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")


def find_converter(configured: str = "") -> Path:
    if configured:
        path = Path(configured)
    else:
        found = shutil.which("pcb2gcode")
        path = Path(found) if found else (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / r"kicad2cnc\tools\pcb2gcode-2.4.0\pcb2gcode-2.4.0\pcb2gcode.exe"
        )
    if not path.is_absolute() or not path.is_file():
        raise ValueError(
            "pcb2gcode was not found. Open CNC settings and select pcb2gcode.exe. "
            "Install the official Windows package using tools\\install-pcb2gcode.ps1."
        )
    return path
