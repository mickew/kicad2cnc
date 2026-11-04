import hashlib
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from collections.abc import Callable


class ExportError(RuntimeError):
    """An export failed or produced incomplete output."""


@dataclass(frozen=True)
class ExportResult:
    directory: Path
    files: tuple[Path, ...]
    log: str


def gerber_matches_layer(path: Path, layer: str) -> bool:
    if path.stat().st_size == 0:
        return False
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            match = re.fullmatch(r"%TF\.FileFunction,([^*]+)\*%\s*", line)
            if match:
                function = match.group(1).split(",")
                if layer == "F.Cu":
                    return function == ["Copper", "L1", "Top"]
                if layer == "B.Cu":
                    return len(function) == 3 and function[0] == "Copper" and function[2] == "Bot"
                if layer == "Edge.Cuts":
                    return function[0] == "Profile"
                return False
            if line.startswith("%FSL"):
                break
    return False


def _publish_job(stage: Path, destination: Path, log: list[str]) -> None:
    for attempt in range(11):
        try:
            stage.rename(destination)
            return
        except OSError as error:
            if getattr(error, "winerror", None) not in (5, 32, 33):
                raise ExportError(
                    f"Could not publish completed job to {destination}: {error}"
                ) from error
            if attempt == 10:
                raise ExportError(
                    f"Windows blocked publication of the completed job to {destination} "
                    f"after 5 seconds of retries: {error}\n"
                    "Close any viewer or CNC sender using the export directory, check its "
                    "write permissions, or choose another output directory and export again. "
                    "No final job was published."
                ) from error
            log.append(
                f"Windows blocked job-folder rename (error {error.winerror}); "
                f"retrying publication ({attempt + 1}/10)."
            )
            time.sleep(0.5)


def export_board(
    cli: Path, board: Path, output: Path, layers: tuple[str, ...],
    *, convert: Callable[[Path], str] | None = None,
) -> ExportResult:
    if not cli.is_file():
        raise ExportError(f"KiCad CLI not found: {cli}. Check the KiCad installation.")
    if not board.is_absolute() or not board.is_file():
        raise ExportError(f"Save the board before exporting: {board}")
    if not output.is_absolute():
        raise ExportError("Choose an absolute output directory.")
    if not layers or any(not layer or "," in layer for layer in layers):
        raise ExportError("Select at least one valid Gerber layer.")
    original = hashlib.sha256(board.read_bytes()).digest()
    output.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    # Publish only a complete job. Failed runs never mix with earlier exports.
    with TemporaryDirectory(prefix=".kicad2cnc-", dir=output) as staging:
        stage = Path(staging)
        gerbers = stage / "gerbers"
        drills = stage / "drill"
        commands = (
            [
                str(cli), "pcb", "export", "gerbers",
                "--layers", ",".join(layers), "--no-protel-ext",
                "--use-drill-file-origin", "--precision", "6",
                "--output", str(gerbers) + os.sep, str(board),
            ],
            [
                str(cli), "pcb", "export", "drill", "--format", "excellon",
                "--excellon-units", "mm", "--excellon-zeros-format", "decimal",
                "--excellon-oval-format", "route", "--excellon-separate-th",
                "--drill-origin", "plot",
                "--output", str(drills) + os.sep, str(board),
            ],
        )
        for command in commands:
            log.append(subprocess.list2cmdline(command))
            try:
                completed = subprocess.run(
                    command, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=180, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ExportError(f"Could not run KiCad export: {error}\n\n" + "\n".join(log)) from error
            log.extend((completed.stdout, completed.stderr))
            if completed.returncode:
                raise ExportError(
                    f"KiCad export failed (exit {completed.returncode}).\n\n" + "\n".join(log)
                )
        for layer in layers:
            expected = gerbers / f"{board.stem}-{layer.replace('.', '_')}.gbr"
            if not expected.is_file() or expected.stat().st_size == 0:
                # KiCad uses custom layer names in filenames; X2 identifies the actual layer.
                matches = [
                    path for path in gerbers.glob("*.gbr")
                    if gerber_matches_layer(path, layer)
                ]
                if len(matches) != 1:
                    raise ExportError(f"KiCad did not produce the requested layer: {layer}\n\n" + "\n".join(log))
        drill_files = tuple(drills / f"{board.stem}-{kind}.drl" for kind in ("PTH", "NPTH"))
        if any(not file.is_file() or file.stat().st_size == 0 for file in drill_files):
            raise ExportError("KiCad did not produce valid Excellon drill files.\n\n" + "\n".join(log))
        if convert is not None:
            log.append(convert(stage))
        if hashlib.sha256(board.read_bytes()).digest() != original:
            raise ExportError("The saved board changed during export. Export again without editing the board.")
        name = f"{board.stem}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}"
        destination = output / name
        _publish_job(stage, destination, log)
    return ExportResult(
        destination,
        tuple(sorted(path for path in destination.rglob("*") if path.is_file())),
        "\n".join(log),
    )
