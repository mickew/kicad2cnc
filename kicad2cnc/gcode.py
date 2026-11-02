import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from threading import Thread

from kicad2cnc.export import ExportError, gerber_matches_layer
from kicad2cnc.registration import parse_registration_positions, write_registration_excellon
from kicad2cnc.settings import CncSettings


WARNING = (
    "GRBL v1.1 FILES - REVIEW AND SIMULATION REQUIRED\n"
    "Syntax is post-processed for GRBL v1.1; your controller and machine are not verified.\n"
    "Files are separate manual tool operations. Set the tool and Z0 again for each file.\n"
    "Registration holes are optional manual through-holes; inspect their clearances and fit.\n"
    "Automatic placement and fixture alignment are not provided.\n"
    "Z=0 is the PCB top surface. Check origin, units, depths, travel, spindle, tabs,\n"
    "workholding, and front/back alignment. Simulate, GRBL-check, and dry-run before cutting.\n"
)


def layer_file(job: Path, layer: str) -> Path | None:
    matches = [
        path for path in (job / "gerbers").glob("*.gbr")
        if gerber_matches_layer(path, layer)
    ]
    if len(matches) > 1:
        raise ExportError(f"Multiple Gerbers identify layer {layer}.")
    return matches[0] if matches else None


def _cam_drill_text(source: Path) -> str:
    data = source.read_text(encoding="utf-8")
    coordinate = r"X[+-]?\d+(?:\.\d+)?Y[+-]?\d+(?:\.\d+)?"
    # Older Gerbv understands G85 slots, but not KiCad's equivalent route blocks.
    route = (
        rf"^G00({coordinate})[ \t]*\n"
        rf"M15[ \t]*\nG01({coordinate})[ \t]*\nM16[ \t]*\nG05[ \t]*(?=\n|$)"
    )
    data = re.sub(route, r"\1G85\2", data, flags=re.MULTILINE)
    if re.search(r"^(?:G0[0123]|M1[56])", data, re.MULTILINE):
        raise ExportError(
            f"Unsupported Excellon routing in {source.name}. "
            "Only KiCad straight oval-slot route blocks are supported; "
            "use export-only mode for other routed geometry."
        )
    return data


def generate_gcode(
    job: Path,
    executable: Path,
    settings: CncSettings,
    report: Callable[[str], None] = lambda _text: None,
) -> str:
    settings.validate()
    if not executable.is_file():
        raise ExportError(f"pcb2gcode executable not found: {executable}")
    root = job / "gcode"
    root.mkdir()
    cam_root = root / "cam"
    logs: list[str] = []

    def run(arguments: list[str], cwd: Path, timeout: int) -> str:
        command = [str(executable), *arguments]
        report(subprocess.list2cmdline(command) + "\n")
        try:
            with subprocess.Popen(
                command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ) as process:
                lines: list[str] = []

                def read_output() -> None:
                    if process.stdout is not None:
                        for line in process.stdout:
                            lines.append(line)
                            report(line)

                reader = Thread(target=read_output, daemon=True)
                reader.start()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    reader.join()
                    raise ExportError(f"pcb2gcode timed out after {timeout} seconds.")
                reader.join()
                text = "".join(lines)
                logs.append(subprocess.list2cmdline(command) + "\n" + text)
                if process.returncode:
                    raise ExportError(
                        f"pcb2gcode failed (exit {process.returncode}).\n\n" + "\n".join(logs)
                    )
                return text
        except OSError as error:
            raise ExportError(f"Could not launch pcb2gcode: {error}") from error

    version = run(["--version"], root, 15)
    help_text = run(["--help"], root, 15)
    required = ("metricoutput", "nog81", "nog64", "nog91-1", "mill-diameters", "drill-side")
    missing = [option for option in required if f"--{option}" not in help_text]
    if missing:
        raise ExportError("Unsupported pcb2gcode build; missing options: " + ", ".join(missing))
    common: dict[str, str | float | int] = {
        "metric": "true", "metricoutput": "true", "zero-start": "false",
        "nog81": "true", "nog64": "true", "nog91-1": "true",
        "zsafe": settings.safe_z, "zchange": settings.change_z,
        "spinup-time": settings.spinup_time, "spindown-time": settings.spindown_time,
        "tolerance": 0.01,
    }
    front_copper = layer_file(job, "F.Cu")
    back_copper = layer_file(job, "B.Cu")
    back_only = back_copper is not None and front_copper is None
    routing: dict[str, str | float | int] = {}
    if settings.isolation:
        if front_copper:
            routing["front"] = str(front_copper)
        if back_copper:
            routing["back"] = str(back_copper)
        if not routing:
            raise ExportError("Isolation requires a selected F.Cu or B.Cu Gerber.")
    if settings.outline:
        source = layer_file(job, "Edge.Cuts")
        if source is None:
            raise ExportError("Outline cutting requires the Edge.Cuts Gerber.")
        routing["outline"] = str(source)
    outputs: list[Path] = []
    has_slots = False

    def convert(name: str, inputs: dict[str, str | float | int], options: dict[str, str | float | int]) -> None:
        directory = cam_root / name
        directory.mkdir(parents=True)
        config: dict[str, str | float | int] = {**common, **options}
        expected: list[str] = []
        for kind, source in inputs.items():
            extension = ".drl" if kind == "drill" else ".gbr"
            filename = kind + extension
            if kind == "drill":
                (directory / filename).write_text(
                    _cam_drill_text(Path(str(source))), encoding="utf-8",
                )
            else:
                # Gerbv in the Windows build predates X2. Attributes do not affect geometry.
                data = Path(str(source)).read_text(encoding="utf-8")
                data = re.sub(r"%T[AFOD][^%]*\*%", "", data)
                (directory / filename).write_text(data, encoding="utf-8")
            config[kind] = filename
            expected.append("drill.ngc" if kind == "drill" else f"{kind}.ngc")
        if "drill" in inputs and "min-milldrill-hole-diameter" in options:
            drill_text = Path(str(inputs["drill"])).read_text(encoding="utf-8")
            diameters = [
                float(value) for value in re.findall(r"^T\d+C([\d.]+)", drill_text, re.MULTILINE)
            ]
            if not diameters:
                raise ExportError("No tool diameters found in the metric Excellon file.")
            if min(diameters) >= settings.milldrill_threshold:
                expected.remove("drill.ngc")
            if max(diameters) >= settings.milldrill_threshold:
                expected.append("milldrill.ngc")
        (directory / "millproject").write_text(
            "\n".join(f"{key}={value}" for key, value in config.items()) + "\n",
            encoding="utf-8",
        )
        report(f"\nConverting {name}...\n")
        run([], directory, 300)
        for filename in expected:
            path = directory / filename
            if not path.is_file() or path.stat().st_size == 0:
                raise ExportError(f"pcb2gcode did not produce {name}\\{filename}.\n" + "\n".join(logs))
            code = re.sub(r"\([^)]*\)", "", path.read_text(encoding="utf-8"))
            if not re.search(r"\bG0?1\b", code):
                raise ExportError(
                    f"No cutting moves in {name}\\{filename}. "
                    "Deselect empty copper layers or check the input geometry.\n" + "\n".join(logs)
                )
            outputs.append(path)

    mill_options = {
        "mill-diameters": settings.mill_diameter, "isolation-width": settings.isolation_width,
        "milling-overlap": f"{settings.overlap}%", "zwork": settings.mill_depth,
        "mill-infeed": abs(settings.mill_depth), "mill-feed": settings.mill_feed,
        "mill-vertfeed": settings.plunge_feed, "mill-speed": settings.spindle,
    }
    cut_options = {
        "cutter-diameter": settings.cutter_diameter, "zcut": settings.cut_depth,
        "cut-feed": settings.cut_feed, "cut-vertfeed": settings.plunge_feed,
        "cut-infeed": settings.cut_infeed, "cut-speed": settings.spindle,
        "cut-side": "front", "bridges": settings.bridge_width,
        "bridgesnum": settings.bridge_count, "zbridges": settings.bridge_z,
    }
    if routing:
        convert("routing", routing, {**mill_options, **cut_options})
    if settings.drilling:
        drills = sorted((job / "drill").glob("*.drl"))
        if not drills:
            raise ExportError("No Excellon files found for drilling.")
        for index, source in enumerate(drills):
            data = _cam_drill_text(source)
            if "G85" in data:
                has_slots = True
                report(
                    f"Converting oval slots in {source.name} using G85 CAM input. "
                    "Review slot chain-drilling or mill-drilling paths before machining.\n"
                )
            # KiCad emits header-only files when a hole category is absent.
            if not re.search(r"^X[+-]?\d", data, re.MULTILINE):
                report(f"Skipping empty drill file: {source.name}\n")
                continue
            drill_options: dict[str, str | float | int] = {
                **cut_options, "drill-side": "front", "zdrill": settings.drill_depth,
                "drill-feed": settings.drill_feed, "drill-speed": settings.spindle,
            }
            if settings.milldrill_threshold:
                drill_options.update({
                    "min-milldrill-hole-diameter": f"{settings.milldrill_threshold}mm",
                    "milldrill-diameter": settings.cutter_diameter,
                    "zmilldrill": settings.drill_depth,
                })
            convert(f"drill-{index + 1}-{source.stem}", {"drill": str(source)}, drill_options)
            if settings.combined_drilling:
                combined_source = cam_root / f"single-diameter-{index + 1}.drl"
                data = source.read_text(encoding="utf-8")
                data, count = re.subn(
                    r"^(T\d+C)[\d.]+",
                    lambda match: f"{match.group(1)}{settings.combined_drill_diameter:.6f}",
                    data, flags=re.MULTILINE,
                )
                if not count:
                    raise ExportError(f"No tool diameters found in {source.name}.")
                combined_source.write_text(data, encoding="utf-8")
                convert(
                    f"drill-combined-{index + 1}",
                    {"drill": str(combined_source)},
                    {
                        **cut_options, "drill-side": "front",
                        "zdrill": settings.drill_depth, "drill-feed": settings.drill_feed,
                        "drill-speed": settings.spindle,
                    },
                )
    if settings.registration:
        registration_source = cam_root / "registration-input.drl"
        positions = parse_registration_positions(settings.registration_positions)
        write_registration_excellon(
            registration_source, positions, settings.registration_hole_diameter,
        )
        registration_options: dict[str, str | float | int] = {
            **cut_options,
            "drill-side": "front",
            "zdrill": settings.drill_depth,
            "drill-feed": settings.drill_feed,
            "drill-speed": settings.spindle,
        }
        convert(
            "drill-registration-PTH",
            {"drill": str(registration_source)},
            registration_options,
        )
    if not outputs:
        raise ExportError("No CNC operations produced toolpaths. Check selected layers and drill holes.")
    from kicad2cnc.post_grbl import postprocess_gcode

    grbl_files = postprocess_gcode(
        root, settings, mirror_non_copper_x=back_only,
    )
    if not grbl_files:
        raise ExportError("No GRBL tool files were generated.")
    mode_warning = (
        "B.Cu-only mode: board drills, outline, and registration paths are X-mirrored "
        "to match the back-copper toolpath. Machine with B.Cu facing up; no board flip "
        "is needed, and registration holes are optional for a single-sided job.\n"
        if back_only
        else ""
    )
    combined_warning = (
        f"Single-diameter alternative: {settings.combined_drill_diameter:g} mm for all board "
        "holes; designed diameters are changed. Run drill-all-one-size INSTEAD OF normal "
        "board drill/mill-drill files, never in addition. Registration holes stay separate.\n"
        if settings.combined_drilling else ""
    )
    slot_warning = (
        "Oval slots are present: drilling uses overlapping plunges (chain drilling), not "
        "continuous milling, unless selected by the mill-drill threshold. The combined "
        "single-diameter alternative always drills. Verify slot finish and tool suitability.\n"
        if has_slots else ""
    )
    warning = WARNING + mode_warning + combined_warning + slot_warning
    (root / "REVIEW_BEFORE_MACHINING.txt").write_text(
        warning + "\npcb2gcode:\n" + version + "\n"
        + "\nCAM-only source toolpaths are in gcode/cam/.\n"
        + f"Post-processed GRBL files are in gcode/grbl/ ({len(grbl_files)} separate tool files).\n",
        encoding="utf-8",
    )
    text = "\n".join(logs)
    (root / "conversion.log").write_text(text, encoding="utf-8")
    return warning + "\n" + text
