"""Tests for the HAFAS response parser and the live NAH.SH endpoint."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loader import load_pure_modules

load_pure_modules()

from hafas_bus_monitor.api import (
    HafasClient,
    HafasStop,
    parse_location_response,
    parse_station_board_response,
)

TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 2, 21, 20, 0, tzinfo=TZ)


def _departure_payload() -> dict:
    """Return a compact StationBoard response with real-world fields."""
    common = {
        "prodL": [
            {
                "name": "Bus 61",
                "prodCtx": {
                    "line": "61",
                    "lineId": "de:NAHSH:01002|61:",
                    "name": "Bus 61",
                },
            },
            {
                "name": "Bus 32",
                "prodCtx": {
                    "line": "32",
                    "lineId": "de:NAHSH:01002|32:",
                    "name": "Bus 32",
                },
            },
        ],
        "locL": [
            {
                "name": "Kiel Hospitalstraße",
                "lid": "A=1@O=Kiel Hospitalstraße@L=9049091@",
            }
        ],
    }
    return {
        "svcResL": [
            {
                "meth": "StationBoard",
                "res": {
                    "common": common,
                    "jnyL": [
                        {
                            "jid": "1|88154|0|100|2112026",
                            "date": "20261102",
                            "prodX": 0,
                            "dirTxt": "Kiel Hbf",
                            "stbStop": {
                                "locX": 0,
                                "dTimeS": "212300",
                                "dTimeR": "212500",
                                "dPltfR": {"txt": "A"},
                                "dProgType": "PROGNOSED",
                            },
                        },
                        {
                            "jid": "1|73326|1|100|2112026",
                            "date": "20261102",
                            "prodX": 1,
                            "dirTxt": "Holtenau",
                            "stbStop": {
                                "locX": 0,
                                "dTimeS": "212800",
                                "dTimeR": "212800",
                                "dPltfS": {"txt": "B"},
                            },
                        },
                        {
                            "jid": "1|88154|0|100|2112026",
                            "date": "20261102",
                            "prodX": 0,
                            "dirTxt": "Kiel Hbf",
                            "stbStop": {
                                "locX": 0,
                                "dTimeS": "212300",
                                "dTimeR": "212500",
                                "dPltfR": {"txt": "A"},
                            },
                        },
                    ],
                },
            }
        ]
    }


class StationBoardParsingTest(unittest.TestCase):
    """Validate the data contract used by the sensors."""

    def setUp(self) -> None:
        self.stop = HafasStop(
            stop_id="9049091",
            lid="A=1@O=Kiel Hospitalstraße@L=9049091@",
            name="Kiel Hospitalstraße",
        )

    def test_parses_line_destination_delay_and_platform(self) -> None:
        board = parse_station_board_response(
            _departure_payload(),
            self.stop,
            now=NOW,
            scan_minutes=60,
            lines=["61"],
        )
        self.assertEqual(len(board.all_departures), 2)  # duplicate jid removed
        self.assertEqual(len(board.departures), 1)
        departure = board.departures[0]
        self.assertEqual(departure.line, "61")
        self.assertEqual(departure.destination, "Kiel Hbf")
        self.assertEqual(departure.delay_minutes, 2)
        self.assertEqual(departure.delay_seconds, 120)
        self.assertEqual(departure.platform, "A")
        self.assertEqual(departure.departure.hour, 21)
        self.assertEqual(departure.departure.minute, 25)
        self.assertEqual(departure.minutes_until, 5)
        self.assertTrue(departure.realtime)
        self.assertFalse(departure.cancelled)
        self.assertEqual(departure.as_dict()["line"], "61")

    def test_empty_line_filter_shows_all_lines(self) -> None:
        board = parse_station_board_response(
            _departure_payload(),
            self.stop,
            now=NOW,
            scan_minutes=60,
            lines=[],
        )
        self.assertEqual([item.line for item in board.departures], ["61", "32"])

    def test_cancelled_departure_is_skipped_by_next_departure(self) -> None:
        payload = _departure_payload()
        payload["svcResL"][0]["res"]["jnyL"][0]["stbStop"]["dCncl"] = True
        board = parse_station_board_response(
            payload,
            self.stop,
            now=NOW,
            scan_minutes=60,
            lines=["61"],
        )
        self.assertEqual(len(board.departures), 1)
        self.assertTrue(board.departures[0].cancelled)
        self.assertIsNone(board.next_departure)

    def test_hafas_planning_before_now_is_ignored(self) -> None:
        old_now = datetime(2026, 11, 2, 22, 30, 0, tzinfo=TZ)
        board = parse_station_board_response(
            _departure_payload(),
            self.stop,
            now=old_now,
            scan_minutes=60,
            lines=[],
        )
        self.assertEqual(board.departures, [])

    def test_line_target_filter(self) -> None:
        board = parse_station_board_response(
            _departure_payload(),
            self.stop,
            now=NOW,
            scan_minutes=60,
            lines=["61"],
            line_targets={"61": ["Kiel Hbf"]},
        )
        self.assertEqual([item.line for item in board.departures], ["61"])
        self.assertEqual(board.departures[0].destination, "Kiel Hbf")

    def test_line_target_without_match_hides_departure(self) -> None:
        board = parse_station_board_response(
            _departure_payload(),
            self.stop,
            now=NOW,
            scan_minutes=60,
            lines=["61"],
            line_targets={"61": ["Russee"]},
        )
        self.assertEqual(board.departures, [])
        self.assertEqual(len(board.all_departures), 2)

    def test_location_response(self) -> None:
        payload = {
            "svcResL": [
                {
                    "meth": "LocMatch",
                    "res": {
                        "match": {
                            "locL": [
                                {
                                    "type": "S",
                                    "name": "Kiel Hospitalstraße",
                                    "extId": "9049091",
                                    "lid": "A=1@O=Kiel Hospitalstraße@L=9049091@",
                                    "isMainMast": True,
                                    "crd": {"x": 10140156, "y": 54328223},
                                },
                                {
                                    "type": "S",
                                    "name": "Kiel Hospitalstraße",
                                    "extId": "9049091",
                                    "lid": "A=1@O=Kiel Hospitalstraße@L=9049091@",
                                },
                                {"type": "A", "name": "Kiel, Straße 1"},
                            ]
                        }
                    },
                }
            ]
        }
        stops = parse_location_response(payload)
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0].stop_id, "9049091")
        self.assertAlmostEqual(stops[0].latitude or 0, 54.328223)


class LiveNahshTest(unittest.IsolatedAsyncioTestCase):
    """Optional live check; enable with HAFAS_LIVE_TEST=1."""

    @unittest.skipUnless(
        os.environ.get("HAFAS_LIVE_TEST") == "1",
        "set HAFAS_LIVE_TEST=1 to call the public NAH.SH endpoint",
    )
    async def test_live_stop_search_and_departures(self) -> None:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            client = HafasClient(session)
            stops = await client.search_stops("Kiel Hospitalstraße", city="Kiel")
            self.assertTrue(stops)
            self.assertEqual(stops[0].stop_id, "9049091")

            board = await client.fetch_departures(
                stops[0],
                scan_minutes=60,
                lines=[],
            )
            self.assertEqual(board.stop.stop_id, "9049091")
            # Buses may be sparse at night, but the API response itself must
            # parse without an exception.
            for departure in board.departures:
                self.assertTrue(departure.line)
                self.assertTrue(departure.destination)
                self.assertGreaterEqual(departure.minutes_until, 0)

            destinations = await client.get_destinations(
                stops[0], ["61", "62"], scan_minutes=180
            )
            self.assertIn("61", destinations)
            self.assertIn("62", destinations)


if __name__ == "__main__":
    unittest.main()
