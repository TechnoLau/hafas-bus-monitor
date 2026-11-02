"""Small, Home-Assistant-independent helpers for HAFAS Bus Monitor."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .const import (
    CONF_CITY,
    CONF_DESTINATION_FILTER,
    CONF_LINES,
    CONF_ROUTING_ENABLED,
    CONF_SCAN_MINUTES,
    CONF_STOP_CITY,
    CONF_STOP_ID,
    CONF_STOP_LID,
    CONF_STOP_NAME,
    CONF_STOPS,
    CONF_UPDATE_INTERVAL,
    CONF_WALKING_MINUTES,
    DEFAULT_CITY,
    DEFAULT_ROUTING_ENABLED,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WALKING_MINUTES,
    MAX_SCAN_MINUTES,
    MAX_UPDATE_INTERVAL,
    MAX_WALKING_MINUTES,
    MIN_SCAN_MINUTES,
    MIN_UPDATE_INTERVAL,
    MIN_WALKING_MINUTES,
)

_LINE_SPLIT_RE = re.compile(r"[,;/\s]+")


def normalize_lines(value: str | Iterable[str] | None) -> list[str]:
    """Return a clean, de-duplicated list of line labels.

    ``"61, 62"``, ``"61 62"``, ``"61;62"`` and ``["61", "62"]`` all yield
    ``["61", "62"]``.  An empty value means "all lines".
    """
    if value is None:
        return []
    if isinstance(value, str):
        raw_parts = _LINE_SPLIT_RE.split(value)
    else:
        raw_parts = []
        for item in value:
            raw_parts.extend(_LINE_SPLIT_RE.split(str(item)))

    lines: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        line = str(part).strip()
        if not line:
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return lines


def lines_to_text(lines: Iterable[str] | None) -> str:
    """Format a line list for a text form field."""
    return ", ".join(normalize_lines(lines))


def line_matches(line: str, preferred_lines: Iterable[str] | None) -> bool:
    """Check a HAFAS line label against the configured list.

    Matching is case-insensitive.  ``"061"`` also matches ``"61"`` so that
    operators with zero-padded line numbers behave as expected.  An empty
    preferred list deliberately means "show every line".
    """
    preferred = normalize_lines(preferred_lines)
    if not preferred:
        return True

    candidate = str(line or "").strip().casefold()
    if not candidate:
        return False

    for item in preferred:
        wanted = item.strip().casefold()
        if candidate == wanted:
            return True
        if (
            candidate.isdigit()
            and wanted.isdigit()
            and candidate.lstrip("0") == wanted.lstrip("0")
        ):
            return True
    return False


def short_stop_name(name: str, city: str | None = None) -> str:
    """Strip a leading city name from a HAFAS stop name.

    HAFAS returns names such as ``"Kiel Hospitalstraße"``.  For the friendly
    entity name and the routing state we prefer ``"Hospitalstraße"``.
    """
    cleaned = str(name or "").strip()
    cleaned_city = str(city or "").strip()
    if cleaned_city and cleaned.casefold().startswith(cleaned_city.casefold() + " "):
        return cleaned[len(cleaned_city) + 1 :].strip() or cleaned
    return cleaned


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def normalize_stop(stop: dict[str, Any], default_city: str) -> dict[str, Any]:
    """Normalize one stop dictionary from a config entry."""
    return {
        CONF_STOP_ID: str(stop.get(CONF_STOP_ID) or stop.get(CONF_STOP_LID) or ""),
        CONF_STOP_LID: str(stop.get(CONF_STOP_LID) or ""),
        CONF_STOP_NAME: str(stop.get(CONF_STOP_NAME) or ""),
        CONF_STOP_CITY: str(stop.get(CONF_STOP_CITY) or default_city),
        CONF_LINES: normalize_lines(stop.get(CONF_LINES)),
        CONF_DESTINATION_FILTER: str(stop.get(CONF_DESTINATION_FILTER) or "").strip(),
        CONF_WALKING_MINUTES: _clamp(
            _as_int(stop.get(CONF_WALKING_MINUTES), DEFAULT_WALKING_MINUTES),
            MIN_WALKING_MINUTES,
            MAX_WALKING_MINUTES,
        ),
    }


def merged_config(
    entry_data: dict[str, Any], entry_options: dict[str, Any]
) -> dict[str, Any]:
    """Merge entry data/options and fill in safe defaults.

    Options are applied on top of data so that older entries keep working
    after new options were introduced.  Stops are normalized and invalid
    entries are dropped.
    """
    config: dict[str, Any] = {
        CONF_CITY: DEFAULT_CITY,
        CONF_SCAN_MINUTES: DEFAULT_SCAN_MINUTES,
        CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
        CONF_ROUTING_ENABLED: DEFAULT_ROUTING_ENABLED,
        CONF_STOPS: [],
    }
    config.update(entry_data or {})
    config.update(entry_options or {})

    city = str(config.get(CONF_CITY) or DEFAULT_CITY).strip() or DEFAULT_CITY
    stops: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_stop in config.get(CONF_STOPS) or []:
        if not isinstance(raw_stop, dict):
            continue
        stop = normalize_stop(raw_stop, city)
        if (
            not stop[CONF_STOP_ID]
            or not stop[CONF_STOP_LID]
            or not stop[CONF_STOP_NAME]
        ):
            continue
        if stop[CONF_STOP_ID] in seen:
            continue
        seen.add(stop[CONF_STOP_ID])
        stops.append(stop)

    config[CONF_CITY] = city
    config[CONF_STOPS] = stops
    config[CONF_SCAN_MINUTES] = _clamp(
        _as_int(config.get(CONF_SCAN_MINUTES), DEFAULT_SCAN_MINUTES),
        MIN_SCAN_MINUTES,
        MAX_SCAN_MINUTES,
    )
    config[CONF_UPDATE_INTERVAL] = _clamp(
        _as_int(config.get(CONF_UPDATE_INTERVAL), DEFAULT_UPDATE_INTERVAL),
        MIN_UPDATE_INTERVAL,
        MAX_UPDATE_INTERVAL,
    )
    config[CONF_ROUTING_ENABLED] = bool(
        config.get(CONF_ROUTING_ENABLED, DEFAULT_ROUTING_ENABLED)
    )
    return config
