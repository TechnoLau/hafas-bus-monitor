"""Routing logic for the "fastest bus after school" sensor.

The integration does not know the final destination travel time.  It therefore
compares the earliest departure that can still be reached on foot.  A
departure is only considered when the configured walking time fits between
"now" and the real-time departure.  This is the information the routing
sensor exposes; a later version could additionally compare journey arrival
times via HAFAS TripSearch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .api import HafasDeparture, StopDepartures
from .const import (
    CONF_LINE_TARGETS,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_WALKING_MINUTES,
    DISPLAY_MINUTES_THRESHOLD,
)
from .util import line_color, short_stop_name


@dataclass(slots=True)
class RouteCandidate:
    """One stop's best reachable departure."""

    stop_id: str
    stop_name: str
    stop_short: str
    city: str | None
    walk_minutes: int
    line_targets: dict[str, list[str]]
    line: str
    line_color: str
    destination: str
    departure: datetime
    minutes_until: int
    time_text: str
    leave_in_minutes: int
    catchable: bool
    delay: int
    platform: str | None
    cancelled: bool

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for attributes."""
        return {
            "stop_id": self.stop_id,
            "stop": self.stop_name,
            "stop_short": self.stop_short,
            "city": self.city,
            "walk_minutes": self.walk_minutes,
            "line_targets": self.line_targets,
            "line": self.line,
            "line_color": self.line_color,
            "destination": self.destination,
            "departure_time": self.departure.isoformat(),
            "departure_time_local": self.departure.strftime("%H:%M"),
            "minutes_until": self.minutes_until,
            "time_text": self.time_text,
            "leave_in_minutes": self.leave_in_minutes,
            "catchable": self.catchable,
            "delay": self.delay,
            "platform": self.platform,
            "cancelled": self.cancelled,
        }


@dataclass(slots=True)
class RoutingResult:
    """Result of comparing all configured stops."""

    best: RouteCandidate | None
    options: list[dict[str, Any]]
    reason: str | None

    @property
    def state(self) -> str:
        """Return the human-readable sensor state."""
        if self.best is None:
            return "Keine Verbindung"
        stop = self.best.stop_short or self.best.stop_name
        if self.best.minutes_until < DISPLAY_MINUTES_THRESHOLD:
            return f"Linie {self.best.line} ab {stop} in {self.best.minutes_until} Min"
        return f"Linie {self.best.line} ab {stop} um {self.best.departure:%H:%M}"


def _candidate_from_departure(
    departure: HafasDeparture,
    stop: dict[str, Any],
    now: datetime,
    *,
    catchable: bool,
) -> RouteCandidate:
    """Build a route candidate from a departure."""
    walk_minutes = max(0, int(stop.get(CONF_WALKING_MINUTES) or 0))
    seconds_until = max(0, int((departure.departure - now).total_seconds()))
    minutes_until = seconds_until // 60
    leave_in_minutes = max(0, minutes_until - walk_minutes)
    city = str(stop.get("city") or "").strip() or None

    return RouteCandidate(
        stop_id=str(stop.get(CONF_STOP_ID) or ""),
        stop_name=str(stop.get(CONF_STOP_NAME) or ""),
        stop_short=short_stop_name(str(stop.get(CONF_STOP_NAME) or ""), city),
        city=city,
        walk_minutes=walk_minutes,
        line_targets=dict(stop.get(CONF_LINE_TARGETS) or {}),
        line=departure.line,
        line_color=line_color(departure.line),
        destination=departure.destination,
        departure=departure.departure,
        minutes_until=minutes_until,
        time_text=(
            f"in {minutes_until} Min"
            if minutes_until < DISPLAY_MINUTES_THRESHOLD
            else f"um {departure.departure:%H:%M}"
        ),
        leave_in_minutes=leave_in_minutes,
        catchable=catchable,
        delay=departure.delay_minutes,
        platform=departure.platform,
        cancelled=departure.cancelled,
    )


def evaluate_routing(
    stops: list[dict[str, Any]],
    stop_data: dict[str, StopDepartures] | None,
    now: datetime,
) -> RoutingResult:
    """Compare all stops and return the earliest catchable departure.

    ``stop_data`` is keyed by the stop id stored in the config entry.  Missing
    or failed stops are still included in the options list with
    ``catchable: false`` so dashboards can explain why a stop was skipped.
    """
    data = stop_data or {}
    options: list[dict[str, Any]] = []
    candidates: list[RouteCandidate] = []
    any_departures = False

    for stop in stops:
        stop_id = str(stop.get(CONF_STOP_ID) or "")
        city = str(stop.get("city") or "").strip() or None
        walk_minutes = max(0, int(stop.get(CONF_WALKING_MINUTES) or 0))
        line_targets = dict(stop.get(CONF_LINE_TARGETS) or {})
        stop_name = str(stop.get(CONF_STOP_NAME) or stop_id)
        stop_short = short_stop_name(stop_name, city)
        departures = data.get(stop_id)

        if departures is None:
            options.append(
                {
                    "stop_id": stop_id,
                    "stop": stop_name,
                    "stop_short": stop_short,
                    "city": city,
                    "walk_minutes": walk_minutes,
                    "line_targets": line_targets,
                    "catchable": False,
                    "error": "no_data",
                }
            )
            continue

        board_active = [item for item in departures.departures if not item.cancelled]
        if board_active:
            any_departures = True

        active = board_active

        chosen: HafasDeparture | None = None
        for departure in active:
            seconds_until = (departure.departure - now).total_seconds()
            if seconds_until < 0:
                continue
            if seconds_until >= walk_minutes * 60:
                chosen = departure
                break

        if chosen is None:
            # Expose the next (uncatchable) departure, if there is one, so the
            # dashboard can show e.g. "next bus in 2 min, walk takes 5 min".
            next_departure = active[0] if active else None
            if next_departure is not None:
                options.append(
                    _candidate_from_departure(
                        next_departure, stop, now, catchable=False
                    ).as_dict()
                    | {"error": "too_short_walk_time"}
                )
            else:
                options.append(
                    {
                        "stop_id": stop_id,
                        "stop": stop_name,
                        "stop_short": stop_short,
                        "city": city,
                        "walk_minutes": walk_minutes,
                        "line_targets": line_targets,
                        "catchable": False,
                        "error": "no_departures",
                    }
                )
            continue

        candidate = _candidate_from_departure(chosen, stop, now, catchable=True)
        candidates.append(candidate)
        options.append(candidate.as_dict())

    if not stops:
        return RoutingResult(best=None, options=[], reason="no_stops")

    if not candidates:
        if not any_departures:
            reason = "no_departures"
        else:
            reason = "no_catchable_departure"
        return RoutingResult(best=None, options=options, reason=reason)

    # Earliest actual departure wins.  A shorter walk only breaks ties.
    best = min(
        candidates,
        key=lambda candidate: (
            candidate.departure.timestamp(),
            candidate.walk_minutes,
        ),
    )
    return RoutingResult(best=best, options=options, reason=None)
