"""Tests for the fastest-connection routing logic."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loader import load_pure_modules

load_pure_modules()

from hafas_bus_monitor.api import (
    HafasDeparture,
    HafasStop,
    StopDepartures,
)
from hafas_bus_monitor.routing import evaluate_routing

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 2, 13, 0, 0, tzinfo=TZ)


def _departure(
    line: str,
    destination: str,
    minutes: int,
    *,
    delay: int = 0,
    cancelled: bool = False,
    stop_name: str = "Kiel Hospitalstraße",
) -> HafasDeparture:
    departure = NOW + timedelta(minutes=minutes)
    planned = departure - timedelta(minutes=delay)
    return HafasDeparture(
        line=line,
        line_name=f"Bus {line}",
        line_id=f"line-{line}",
        destination=destination,
        departure=departure,
        planned_departure=planned,
        delay_seconds=delay * 60,
        minutes_until=minutes,
        platform="A",
        cancelled=cancelled,
        realtime=True,
        trip_id=f"{line}-{minutes}",
        stop_name=stop_name,
    )


def _board(
    stop_id: str,
    name: str,
    departures: list[HafasDeparture],
) -> StopDepartures:
    return StopDepartures(
        stop=HafasStop(stop_id=stop_id, lid=f"lid-{stop_id}", name=name),
        departures=departures,
        all_departures=departures,
        fetched_at=NOW,
        scan_minutes=60,
    )


def _stops() -> list[dict]:
    return [
        {
            "id": "hospital",
            "name": "Kiel Hospitalstraße",
            "city": "Kiel",
            "lines": ["61", "62"],
            "line_targets": {},
            "walking_minutes": 3,
        },
        {
            "id": "kunsthalle",
            "name": "Kiel Kunsthalle",
            "city": "Kiel",
            "lines": ["61", "62"],
            "line_targets": {},
            "walking_minutes": 6,
        },
    ]


class RoutingTest(unittest.TestCase):
    """Validate the fastest-connection comparison."""

    def test_earliest_catchable_departure_wins(self) -> None:
        data = {
            "hospital": _board(
                "hospital",
                "Kiel Hospitalstraße",
                [_departure("61", "Kiel Hbf", 5)],
            ),
            "kunsthalle": _board(
                "kunsthalle",
                "Kiel Kunsthalle",
                [_departure("62", "Russee", 4)],
            ),
        }
        # Kunsthalle's bus at 4 min is too early for a 6 min walk, so the
        # Hospitalstraße bus at 5 min (3 min walk) must win.
        result = evaluate_routing(_stops(), data, NOW)
        self.assertIsNotNone(result.best)
        assert result.best is not None
        self.assertEqual(result.best.stop_id, "hospital")
        self.assertEqual(result.best.line, "61")
        self.assertEqual(result.state, "Linie 61 ab Hospitalstraße in 5 min")

    def test_earlier_bus_wins_when_walk_fits(self) -> None:
        data = {
            "hospital": _board(
                "hospital",
                "Kiel Hospitalstraße",
                [_departure("61", "Kiel Hbf", 5)],
            ),
            "kunsthalle": _board(
                "kunsthalle",
                "Kiel Kunsthalle",
                [_departure("62", "Russee", 4)],
            ),
        }
        stops = _stops()
        stops[1]["walking_minutes"] = 2
        result = evaluate_routing(stops, data, NOW)
        assert result.best is not None
        self.assertEqual(result.best.stop_id, "kunsthalle")
        self.assertEqual(result.state, "Linie 62 ab Kunsthalle in 4 min")
        self.assertEqual(result.best.leave_in_minutes, 2)

    def test_zero_minutes_is_shown_as_sofort(self) -> None:
        data = {
            "hospital": _board(
                "hospital",
                "Kiel Hospitalstraße",
                [_departure("61", "Mettenhof", 0)],
            )
        }
        stops = _stops()[:1]
        stops[0]["walking_minutes"] = 0
        result = evaluate_routing(stops, data, NOW)
        assert result.best is not None
        self.assertEqual(result.state, "Linie 61 ab Hospitalstraße Sofort")
        self.assertEqual(result.best.time_text, "Sofort")

    def test_skips_uncatchable_bus_and_takes_next(self) -> None:
        data = {
            "hospital": _board(
                "hospital",
                "Kiel Hospitalstraße",
                [
                    _departure("61", "Kiel Hbf", 2),
                    _departure("61", "Kiel Hbf", 12),
                ],
            )
        }
        result = evaluate_routing(_stops()[:1], data, NOW)
        assert result.best is not None
        self.assertEqual(result.best.minutes_until, 12)

    def test_no_catchable_departure(self) -> None:
        data = {
            "hospital": _board(
                "hospital",
                "Kiel Hospitalstraße",
                [_departure("61", "Kiel Hbf", 1)],
            )
        }
        result = evaluate_routing(_stops()[:1], data, NOW)
        self.assertIsNone(result.best)
        self.assertEqual(result.reason, "no_catchable_departure")
        self.assertEqual(result.state, "Keine Verbindung")

    def test_cancelled_departure_is_ignored(self) -> None:
        data = {
            "hospital": _board(
                "hospital",
                "Kiel Hospitalstraße",
                [
                    _departure("61", "Kiel Hbf", 3, cancelled=True),
                    _departure("61", "Kiel Hbf", 13),
                ],
            )
        }
        result = evaluate_routing(_stops()[:1], data, NOW)
        assert result.best is not None
        self.assertEqual(result.best.minutes_until, 13)

    def test_over_threshold_uses_clock_time(self) -> None:
        data = {
            "hospital": _board(
                "hospital",
                "Kiel Hospitalstraße",
                [_departure("61", "Mettenhof", 25)],
            )
        }
        result = evaluate_routing(_stops()[:1], data, NOW)
        assert result.best is not None
        self.assertEqual(
            result.state,
            "Linie 61 ab Hospitalstraße um 13:25",
        )

    def test_line_targets_are_exposed(self) -> None:
        data = {
            "hospital": _board(
                "hospital",
                "Kiel Hospitalstraße",
                [_departure("61", "Mettenhof", 8)],
            )
        }
        stops = _stops()[:1]
        stops[0]["line_targets"] = {"61": ["Mettenhof"]}
        result = evaluate_routing(stops, data, NOW)
        assert result.best is not None
        self.assertEqual(result.best.line_targets, {"61": ["Mettenhof"]})
        self.assertEqual(result.best.as_dict()["line_targets"], {"61": ["Mettenhof"]})

    def test_missing_stop_data_is_documented(self) -> None:
        result = evaluate_routing(
            _stops(), {"hospital": _board("hospital", "Kiel Hospitalstraße", [])}, NOW
        )
        self.assertIsNone(result.best)
        self.assertEqual(result.reason, "no_departures")
        self.assertEqual(len(result.options), 2)
        self.assertEqual(result.options[1]["error"], "no_data")


if __name__ == "__main__":
    unittest.main()
