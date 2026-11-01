import tempfile
import unittest
from pathlib import Path

from kicad2cnc.registration import parse_registration_positions, write_registration_excellon


class RegistrationTests(unittest.TestCase):
    def test_parses_symmetric_two_and_four_hole_patterns(self) -> None:
        self.assertEqual(
            parse_registration_positions("5, -2\n-5, -2"),
            ((5.0, -2.0), (-5.0, -2.0)),
        )
        self.assertEqual(
            parse_registration_positions(
                "5, -2\n-5, -2\n5, 2\n-5, 2"
            ),
            ((5.0, -2.0), (-5.0, -2.0), (5.0, 2.0), (-5.0, 2.0)),
        )
        self.assertEqual(
            parse_registration_positions("0, 0\n5, 2\n-5, 2"),
            ((0.0, 0.0), (5.0, 2.0), (-5.0, 2.0)),
        )

    def test_rejects_bad_count_duplicates_nonfinite_and_asymmetry(self) -> None:
        for value in (
            "",
            "1, 2",
            "1, 2\n-1, 2\n0, 0\n0, 1\n1, 1",
            "1, 2\n1, 2",
            "1, 2\n-1, 2\n0, nan",
            "1, 2\n-2, 1",
            "0, 1\n0.000002, 1",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_registration_positions(value)

    def test_writes_metric_absolute_excellon_tool_and_positions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registration.drl"
            positions = parse_registration_positions("5, -2\n-5, -2")
            write_registration_excellon(path, positions, 2.5)
            self.assertEqual(
                path.read_text(encoding="ascii"),
                "M48\n"
                "; KiCad to CNC registration holes; metric absolute coordinates\n"
                "FMAT,2\nMETRIC\nT1C2.500000\n%\nG90\nG05\nT1\n"
                "X5.000000Y-2.000000\nX-5.000000Y-2.000000\nM30\n",
            )

    def test_rejects_invalid_tool_diameter_or_hole_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registration.drl"
            for positions, diameter in (
                (((1.0, 2.0), (-1.0, 2.0)), 0.0),
                (((1.0, 2.0), (-1.0, 2.0)), 0.0000001),
                (((1.0, 2.0),), 2.0),
            ):
                with self.subTest(diameter=diameter), self.assertRaises(ValueError):
                    write_registration_excellon(path, positions, diameter)


if __name__ == "__main__":
    unittest.main()
