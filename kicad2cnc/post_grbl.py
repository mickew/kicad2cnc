import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kicad2cnc.export import ExportError
from kicad2cnc.settings import CncSettings


_WORD = re.compile(r"([A-Za-z])([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
_TOOL = re.compile(r"T(\d+)")
_TOOL_DESCRIPTION = re.compile(
    r"\(MSG,\s*Change tool bit to "
    r"(?:drill size|mill diameter|cutter diameter)\s+([\d.]+)mm\)",
    re.IGNORECASE,
)
_COMMENTS = re.compile(r"\([^()]*\)|;.*$")
_GRBL_G_CODES = frozenset(Decimal(value) for value in (
    "0", "1", "2", "3", "4", "17", "18", "19", "20", "21", "40", "49",
    "54", "55", "56", "57", "58", "59", "80", "90", "91", "91.1", "94",
))
_MODAL_G_CODES = frozenset(Decimal(value) for value in (
    "17", "18", "19", "20", "21", "40", "49", "54", "55", "56", "57",
    "58", "59", "80", "90", "91", "91.1", "94",
))
_PARAMETERS = frozenset(("F", "I", "J", "K", "P", "R", "X", "Y", "Z"))


@dataclass(frozen=True)
class ToolBlock:
    number: int
    diameter: float
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Toolpath:
    source: Path
    operation: str
    order: int
    tools: tuple[ToolBlock, ...]


def _tool_blocks(source: Path) -> tuple[ToolBlock, ...]:
    blocks: list[tuple[int, list[str]]] = []
    current: tuple[int, list[str]] | None = None
    for line in source.read_text(encoding="utf-8").splitlines():
        match = _TOOL.fullmatch(line.strip())
        if match:
            if current is not None:
                blocks.append(current)
            current = (int(match.group(1)), [])
        elif current is not None:
            current[1].append(line)
    if current is not None:
        blocks.append(current)
    if not blocks:
        raise ExportError(f"No explicit tool-change sections found in {source.name}.")

    result: list[ToolBlock] = []
    for number, lines in blocks:
        descriptions = [
            match.group(1)
            for line in lines
            if (match := _TOOL_DESCRIPTION.search(line))
        ]
        if len(descriptions) != 1:
            raise ExportError(
                f"Expected exactly one tool diameter for T{number} in {source.name}."
            )
        try:
            diameter = float(descriptions[0])
        except ValueError as error:
            raise ExportError(f"Invalid tool diameter for T{number} in {source.name}.") from error
        if diameter <= 0:
            raise ExportError(f"Tool diameter for T{number} must be positive in {source.name}.")
        changes = sum(
            re.fullmatch(r"M0?6", _COMMENTS.sub("", line).strip(), re.IGNORECASE) is not None
            for line in lines
        )
        if changes != 1:
            raise ExportError(
                f"Expected exactly one explicit M6 tool-change block for T{number} in {source.name}."
            )
        result.append(ToolBlock(number, diameter, tuple(lines)))
    return tuple(result)


def _grbl_line(line: str, spindle: int, source: Path, mirror_x: bool = False) -> str:
    body = _COMMENTS.sub("", line).strip().upper()
    if not body:
        return ""
    words = list(_WORD.finditer(body))
    if not words or any(
        body[previous.end():word.start()].strip()
        for previous, word in zip(words, words[1:])
    ):
        raise ExportError(f"Unsupported G-code syntax in {source.name}: {line}")
    if body[:words[0].start()].strip() or body[words[-1].end():].strip():
        raise ExportError(f"Unsupported G-code syntax in {source.name}: {line}")

    retained: list[str] = []
    commands: list[Decimal] = []
    has_axis = False
    letters: set[str] = set()
    for word in words:
        letter, raw_value = word.groups()
        letters.add(letter)
        try:
            value = Decimal(raw_value)
        except InvalidOperation as error:
            raise ExportError(f"Invalid G-code number in {source.name}: {line}") from error
        if not value.is_finite():
            raise ExportError(f"Non-finite G-code number in {source.name}: {line}")
        if letter == "G":
            code = value.normalize()
            commands.append(code)
            if code not in _GRBL_G_CODES:
                raise ExportError(f"Unsupported GRBL G{raw_value} in {source.name}: {line}")
            if code in {
                Decimal("18"), Decimal("19"), Decimal("20"),
                Decimal("55"), Decimal("56"), Decimal("57"),
                Decimal("58"), Decimal("59"), Decimal("91"),
            }:
                raise ExportError(
                    f"Conflicting coordinate mode G{raw_value} in {source.name}: {line}"
                )
            if code not in _MODAL_G_CODES:
                output_code = Decimal(5) - code if mirror_x and code in (Decimal(2), Decimal(3)) else code
                retained.append(f"G{int(output_code)}")
        elif letter == "M":
            code = raw_value.lstrip("0") or "0"
            if code not in {"0", "2", "3", "5", "6", "9"}:
                raise ExportError(f"Unsupported or unsafe GRBL M{raw_value} in {source.name}: {line}")
        elif letter == "T":
            raise ExportError(f"Unexpected tool selection in {source.name}: {line}")
        elif letter == "N":
            continue
        elif letter == "S":
            if value != Decimal(spindle):
                raise ExportError(
                    f"Converter spindle speed {raw_value} does not match configured "
                    f"{spindle} RPM in {source.name}."
                )
        elif letter in _PARAMETERS:
            if letter == "F" and value <= 0:
                raise ExportError(f"Feed rate must be positive in {source.name}: {line}")
            output_value = raw_value
            if mirror_x and letter in ("X", "I"):
                output_value = format(-value, "f") if value else "0"
            retained.append(f"{letter}{output_value}")
            if letter in ("X", "Y", "Z", "I", "J", "K", "R"):
                has_axis = True
        else:
            raise ExportError(f"Unsupported G-code word {letter}{raw_value} in {source.name}: {line}")

    if commands.count(Decimal(4)) > 1:
        raise ExportError(f"Multiple dwell commands in one block in {source.name}: {line}")
    if Decimal(4) in commands and "P" not in letters:
        raise ExportError(f"GRBL dwell must have a P duration in {source.name}: {line}")
    if Decimal(4) in commands:
        p_words = [word for word in words if word.group(1).upper() == "P"]
        if (
            commands != [Decimal(4)]
            or len(p_words) != 1
            or any(letter not in {"G", "P", "N"} for letter in letters)
            or Decimal(p_words[0].group(2)) < 0
        ):
            raise ExportError(f"Invalid GRBL dwell block in {source.name}: {line}")
    if "P" in letters and Decimal(4) not in commands:
        raise ExportError(f"Unexpected P word outside a dwell in {source.name}: {line}")
    if sum(code in (Decimal(0), Decimal(1), Decimal(2), Decimal(3), Decimal(4)) for code in commands) > 1:
        raise ExportError(f"Multiple motion commands in one block in {source.name}: {line}")
    if Decimal(4) in commands:
        retained = [
            word for word in retained
            if not (word.startswith("G4") or word.startswith("P"))
        ]
    if not has_axis and any(code in (Decimal(0), Decimal(1), Decimal(2), Decimal(3)) for code in commands):
        if "F" not in letters:
            retained = [word for word in retained if not word.startswith("G")]
    if not retained:
        return ""
    if not has_axis and not any(word.startswith(("F", "P")) for word in retained):
        return ""
    return " ".join(retained)


def _operation(source: Path, cam_root: Path) -> tuple[str, int]:
    relative = source.relative_to(cam_root)
    if relative.parts[0] == "routing" and source.stem in ("front", "back", "outline"):
        operation = {
            "front": ("isolation-front", 2),
            "back": ("isolation-back", 3),
            "outline": ("outline", 4),
        }[source.stem]
        return operation
    if relative.parts[0].startswith("drill-") and source.stem in ("drill", "milldrill"):
        if relative.parts[0].startswith("drill-combined-") and source.stem == "drill":
            return "drill-all-one-size", 1
        if "registration" in relative.parts[0].lower():
            return "registration-drill", -1
        plating = "npth" if "NPTH" in relative.parts[0].upper() else "pth"
        operation = f"{source.stem}-{plating}"
        return operation, 0
    raise ExportError(f"Unrecognized CAM toolpath: {relative}")


def postprocess_gcode(
    gcode_root: Path,
    settings: CncSettings,
    *,
    mirror_non_copper_x: bool = False,
) -> tuple[Path, ...]:
    settings.validate()
    cam_root = gcode_root / "cam"
    sources = tuple(sorted(cam_root.rglob("*.ngc")))
    if not sources:
        raise ExportError("No pcb2gcode CAM toolpaths were found for GRBL post-processing.")

    toolpaths = [Toolpath(source, *_operation(source, cam_root), _tool_blocks(source)) for source in sources]
    combined = [path for path in toolpaths if path.operation == "drill-all-one-size"]
    if combined:
        tools = tuple(tool for path in combined for tool in path.tools)
        if not settings.combined_drilling or any(
            abs(tool.diameter - settings.combined_drill_diameter) > 0.000001 for tool in tools
        ):
            raise ExportError("Combined drill tools do not match the selected single diameter.")
        toolpaths = [path for path in toolpaths if path.operation != "drill-all-one-size"]
        toolpaths.append(Toolpath(
            combined[0].source, "drill-all-one-size", 1,
            (ToolBlock(tools[0].number, settings.combined_drill_diameter,
                       tuple(line for tool in tools for line in tool.lines)),),
        ))
    ordered = sorted(toolpaths, key=lambda toolpath: (toolpath.order, toolpath.operation, str(toolpath.source)))
    output = gcode_root / "grbl"
    output.mkdir()
    files: list[Path] = []
    manifest: list[str] = []
    sequence = 0
    for toolpath in ordered:
        for tool in toolpath.tools:
            sequence += 1
            safe_diameter = f"{tool.diameter:g}".replace(".", "p")
            destination = output / f"{sequence:02d}-{toolpath.operation}-{safe_diameter}mm.nc"
            source_name = toolpath.source.name.encode("ascii", "backslashreplace").decode("ascii")
            if toolpath.operation == "drill-all-one-size":
                source_name = "drill-combined-*; all board drill CAM sources"
            mirror_x = mirror_non_copper_x and toolpath.operation != "isolation-back"
            body = [
                _grbl_line(line, settings.spindle, toolpath.source, mirror_x)
                for line in tool.lines
            ]
            body = [line for line in body if line]
            if not any(
                re.search(r"\bG[123]\b.*\b[XYZ][+-]?(?:\d|\.\d)", line)
                for line in body
            ):
                raise ExportError(
                    f"No cutting moves for tool T{tool.number} in {toolpath.source.name}."
                )
            header = [
                "(KiCad to CNC - GRBL v1.1 command subset; review and simulate before use.)",
                f"(Operation: {toolpath.operation}; source: {source_name}.)",
                f"(Tool: {tool.diameter:g} mm; converter tool T{tool.number}.)",
                "(With spindle stopped, install this tool and set/probe Z0 against the PCB surface.)",
                "(Verify G54 origin, homing, travel, workholding, spindle direction, and clearance.)",
                "G21",
                "G90",
                "G94",
                "G17",
                "G91.1",
                "G54",
                "G40",
                "G49",
                "M5",
                "M9",
                f"G0 Z{settings.change_z:.3f}",
            ]
            if mirror_x:
                header.insert(
                    3,
                    "(Back-only setup: X-mirrored to match B.Cu; place board with B.Cu upward.)",
                )
            if toolpath.operation == "drill-all-one-size":
                header.insert(1, "(ALTERNATIVE: replaces normal board drill/mill-drill files; do not run both.)")
                header.insert(2, "(All board holes use this tool diameter, not the designed diameters.)")
            if settings.spinup_time:
                header.append(f"M3 S{settings.spindle}")
                header.append(f"G4 P{settings.spinup_time:g}")
            else:
                header.append(f"M3 S{settings.spindle}")
            footer = [
                f"G0 Z{settings.change_z:.3f}",
                "M5",
                "M9",
            ]
            if settings.spindown_time:
                footer.append(f"G4 P{settings.spindown_time:g}")
            footer.extend(("M30", ""))
            destination.write_text(
                "\n".join([*header, *body, *footer]),
                encoding="ascii",
            )
            files.append(destination)
            alternative = "ALTERNATIVE ONLY - " if toolpath.operation == "drill-all-one-size" else ""
            manifest.append(
                f"{sequence:02d}. {alternative}{destination.name} — {toolpath.operation}, "
                f"{tool.diameter:g} mm tool (source T{tool.number}; {toolpath.source.relative_to(cam_root)})."
            )

    registration_notes = (
        [
            "The first file drills the configured through-PCB registration holes.",
            "They must be symmetric about X=0 for the 180-degree Y-axis flip.",
            "Their copper, component, edge, and clamp clearances are not checked.",
            "Manually inspect their positions before machining.",
        ]
        if settings.registration
        else [
            "No registration holes are generated. Double-sided alignment is manual.",
        ]
    )
    orientation_notes = (
        [
            "Back-only mode: B.Cu isolation, outline, board drills, and optional",
            "registration paths use matching X reflection about X=0. Place the board",
            "with B.Cu upward and do not flip it between these operations.",
            "This is a coordinate transform, not automatic board registration; establish",
            "the reflected work origin and verify every position against the PCB.",
        ]
        if mirror_non_copper_x
        else [
            "Back copper is mirrored about X=0; flipping the board 180 degrees about the",
            "Y axis matches this coordinate transform. The physical alignment setup must",
            "be independently verified.",
        ]
    )
    if mirror_non_copper_x:
        if settings.registration:
            machining_order = (
                "For this B.Cu-up single-sided job, drill registration holes first, "
                "then any board holes, B.Cu isolation, and outline last when present. "
                "Do not flip the board."
            )
        else:
            machining_order = (
                "For this B.Cu-up single-sided job, drill board holes first, then B.Cu "
                "isolation, and outline last when present. Do not flip the board."
            )
    elif any(toolpath.operation == "isolation-back" for toolpath in ordered):
        drill_order = (
            "Drill registration holes first, then board holes"
            if settings.registration else "Drill board holes"
        )
        machining_order = (
            f"{drill_order} and front isolation; flip 180 "
            "degrees about the Y axis using a verified fixture, re-zero, then run back "
            "isolation. Cut the outline last when present."
        )
    else:
        drill_order = (
            "Drill registration holes first, then board holes"
            if settings.registration else "Drill board holes"
        )
        machining_order = (
            f"{drill_order}, run the selected front-side "
            "isolation, and cut the outline last when present."
        )
    readme = [
        "KiCad to CNC — GRBL v1.1 per-tool job",
        "",
        "These files use the GRBL v1.1 supported command subset. They have not been",
        "checked against your controller firmware, CNC travel, spindle, workholding,",
        "tool runout, stock thickness, or physical board setup. Run GRBL $C check mode",
        "where available, simulate every file, then dry-run above the stock before cutting.",
        "",
        "Each file contains exactly one tool operation. Change tools manually between",
        "files with the spindle stopped. Re-set/probe Z=0 on the PCB top surface after",
        "each tool change. Do not remove tool stops or skip files to automate a job.",
        "The program uses mm, G54, absolute XY, and the configured drill/place origin.",
        *orientation_notes,
        machining_order,
        *registration_notes,
        "Secure the board and verify the full X/Y/Z travel before use.",
        *(
            [
                "",
                "SINGLE-DIAMETER ALTERNATIVE: drill-all-one-size combines all board PTH/NPTH",
                "holes using the selected drill diameter, including holes normally mill-drilled.",
                "Run it INSTEAD OF the normal board drill/mill-drill files, never in addition.",
                "It changes designed hole diameters. Registration holes are NOT included;",
                "use their separate operation when enabled. Other operation order is unchanged.",
                "Its combined CAM sources are in cam/drill-combined-*.",
            ] if combined else []
        ),
        "",
        "Configured spindle: " + str(settings.spindle) + " RPM",
        f"Safe retract/change height: Z{settings.change_z:g} mm",
        f"Spindle spin-up/shutdown dwell: {settings.spinup_time:g}/{settings.spindown_time:g} seconds",
        "",
        *manifest,
    ]
    (output / "README_job.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")
    return tuple(files)
