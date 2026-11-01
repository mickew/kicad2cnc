import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path


_COORDINATE = re.compile(
    r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)
_TOLERANCE = Decimal("0.000001")


def parse_registration_positions(value: str) -> tuple[tuple[float, float], ...]:
    lines = [line for line in value.splitlines() if line.strip()]
    if not 2 <= len(lines) <= 4:
        raise ValueError("Enter 2-4 registration-hole coordinates, one X,Y pair per line.")

    positions: list[tuple[Decimal, Decimal]] = []
    for line in lines:
        match = _COORDINATE.fullmatch(line)
        if match is None:
            raise ValueError(f"Invalid registration coordinate: {line!r}. Use X,Y in mm.")
        try:
            x, y = (Decimal(part) for part in match.groups())
        except InvalidOperation as error:
            raise ValueError(f"Invalid registration coordinate: {line!r}.") from error
        if not x.is_finite() or not y.is_finite():
            raise ValueError("Registration coordinates must be finite.")
        if abs(x) > Decimal("100000") or abs(y) > Decimal("100000"):
            raise ValueError("Registration coordinates must be within +/-100000 mm.")
        positions.append((x, y))

    normalized = [
        (x.quantize(_TOLERANCE), y.quantize(_TOLERANCE))
        for x, y in positions
    ]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Registration-hole coordinates must be unique.")
    for x, y in normalized:
        if not any(
            abs(other_x + x) <= _TOLERANCE and abs(other_y - y) <= _TOLERANCE
            for other_x, other_y in normalized
        ):
            raise ValueError(
                "Registration holes must be symmetric about X=0 for the back-side flip."
            )
    return tuple((float(x), float(y)) for x, y in positions)


def write_registration_excellon(
    path: Path,
    positions: tuple[tuple[float, float], ...],
    diameter: float,
) -> None:
    if not math.isfinite(diameter) or diameter <= 0:
        raise ValueError("Registration-hole diameter must be finite and positive.")
    if not 2 <= len(positions) <= 4:
        raise ValueError("Registration-hole file requires 2-4 positions.")
    tool_diameter = f"{diameter:.6f}"
    if float(tool_diameter) <= 0:
        raise ValueError("Registration-hole diameter must be at least 0.000001 mm.")
    lines = [
        "M48",
        "; KiCad to CNC registration holes; metric absolute coordinates",
        "FMAT,2",
        "METRIC",
        f"T1C{tool_diameter}",
        "%",
        "G90",
        "G05",
        "T1",
    ]
    lines.extend(f"X{x:.6f}Y{y:.6f}" for x, y in positions)
    lines.append("M30")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
