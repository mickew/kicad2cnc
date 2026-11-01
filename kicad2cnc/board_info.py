from dataclasses import dataclass
from pathlib import Path

from kipy import KiCad
from kipy.board import BoardLayer


@dataclass(frozen=True)
class BoardInfo:
    filename: str
    layers: tuple[str, ...]
    saved_file_exists: bool
    version: str

    @property
    def save_notice(self) -> str:
        if not self.saved_file_exists:
            return (
                "Save this board in the PCB Editor before exporting. "
                "No saved board file was found."
            )
        return (
            "Save the board in the PCB Editor before exporting. KiCad 10's IPC API "
            "does not report unsaved changes; CLI exports read the "
            "saved file, not the live editor."
        )


def read_board_info(kicad: KiCad) -> BoardInfo:
    version = kicad.get_version()
    if version.major != 10:
        raise RuntimeError(
            f"This plugin currently targets KiCad 10.x; connected to {version.full_version}."
        )
    board = kicad.get_board()
    filename = Path(board.name) if board.name else None
    directory = board.document.project.path
    if filename is not None and not filename.is_absolute():
        filename = Path(directory) / filename if directory else None
    layers = tuple(
        BoardLayer.Name(layer).removeprefix("BL_").replace("_", ".")
        for layer in board.get_enabled_layers()
    )
    return BoardInfo(
        filename=str(filename) if filename is not None else "(not saved)",
        layers=layers,
        saved_file_exists=filename is not None and filename.is_file(),
        version=version.full_version,
    )
