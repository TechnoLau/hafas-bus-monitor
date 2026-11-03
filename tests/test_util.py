"""Tests for config normalization and destination filters."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loader import load_pure_modules

load_pure_modules()

from hafas_bus_monitor.util import (
    destination_allowed,
    line_color,
    normalize_line_targets,
    normalize_stop,
    targets_for_line,
)


class DestinationNormalizationTest(unittest.TestCase):
    """Validate the v1 -> v2 migration and multi-word destinations."""

    def test_multi_word_destination_is_not_split(self) -> None:
        targets = normalize_line_targets({"61": ["Kiel Hbf", "Mettenhof"]})
        self.assertEqual(targets, {"61": ["Kiel Hbf", "Mettenhof"]})
        self.assertTrue(destination_allowed("61", "Kiel Hbf", targets))
        self.assertFalse(destination_allowed("61", "Russee", targets))

    def test_line_matching_with_zero_padding(self) -> None:
        targets = {"061": ["Kiel Hbf"]}
        self.assertEqual(targets_for_line("61", targets), ["Kiel Hbf"])
        self.assertTrue(destination_allowed("61", "Kiel Hbf", targets))

    def test_old_destination_filter_is_migrated(self) -> None:
        stop = normalize_stop(
            {
                "id": "1",
                "lid": "lid",
                "name": "Kiel Hospitalstraße",
                "lines": ["61", "62"],
                "destination_filter": "Russee",
                "walking_minutes": 3,
            },
            "Kiel",
        )
        self.assertEqual(
            stop["line_targets"],
            {"61": ["Russee"], "62": ["Russee"]},
        )

    def test_line_color_is_stable(self) -> None:
        self.assertEqual(line_color("61"), line_color("61"))
        self.assertEqual(line_color(" N42 "), line_color("n42"))

    def test_empty_targets_mean_all_destinations(self) -> None:
        self.assertTrue(destination_allowed("61", "Irgendwo", {"61": []}))
        self.assertTrue(destination_allowed("61", "Irgendwo", {}))


if __name__ == "__main__":
    unittest.main()
