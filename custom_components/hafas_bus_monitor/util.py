"""Small, Home-Assistant-independent helpers for HAFAS Bus Monitor."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from typing import Any, Final

from .const import (
    CONF_CITY,
    CONF_DESTINATION_FILTER,
    CONF_HOLIDAY_ENTITY,
    CONF_LINE_TARGETS,
    CONF_LINES,
    CONF_ROUTING_ENABLED,
    CONF_SCAN_MINUTES,
    CONF_STOP_CITY,
    CONF_STOP_ID,
    CONF_STOP_LID,
    CONF_STOP_NAME,
    CONF_STOPS,
    CONF_SUBENTRY_ID,
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
    SUBENTRY_TYPE_STOP,
)

_LINE_SPLIT_RE = re.compile(r"[,;/\s]+")

# Stable, high-contrast colors for the same line across all stops/graphs.
LINE_COLORS: Final = (
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#bfef45",
    "#fabed4",
    "#469990",
    "#dcbeff",
    "#9a6324",
)


def line_color(line: str) -> str:
    """Return a stable color for a line label.

    Numeric lines use their number modulo the palette, so consecutive lines
    such as 61/62 get clearly different colors.  Alphanumeric lines use a
    stable hash.
    """
    cleaned = str(line or "?").strip()
    if cleaned.isdigit():
        return LINE_COLORS[int(cleaned) % len(LINE_COLORS)]
    digest = hashlib.sha1(cleaned.casefold().encode()).hexdigest()
    return LINE_COLORS[int(digest[:8], 16) % len(LINE_COLORS)]


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


def normalize_string_list(value: Iterable[str] | str | None) -> list[str]:
    """Normalize a list of destination names without splitting spaces."""
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [value]
    else:
        raw_items = list(value)

    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def normalize_line_targets(value: Any) -> dict[str, list[str]]:
    """Normalize the per-line destination mapping from an entry.

    HAFAS destination names are kept verbatim so they can be compared with the
    values returned by the API.  An empty list means "all destinations".
    """
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[str]] = {}
    for raw_line, raw_targets in value.items():
        line = str(raw_line or "").strip()
        if not line:
            continue
        result[line] = normalize_string_list(raw_targets)
    return result


def targets_for_line(line: str, line_targets: dict[str, list[str]] | None) -> list[str]:
    """Return the configured destination filter for a HAFAS line."""
    for configured_line, targets in (line_targets or {}).items():
        if line_matches(line, [configured_line]):
            return list(targets)
    return []


def destination_allowed(
    line: str,
    destination: str,
    line_targets: dict[str, list[str]] | None,
) -> bool:
    """Check a departure destination against the per-line target filter."""
    targets = targets_for_line(line, line_targets)
    if not targets:
        return True
    wanted = str(destination or "").strip().casefold()
    return any(target.casefold() == wanted for target in targets)


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
    lines = normalize_lines(stop.get(CONF_LINES))
    line_targets = normalize_line_targets(stop.get(CONF_LINE_TARGETS))

    # Migrate the old single destination filter from v1: apply it to every
    # configured line.  New entries store line_targets instead.
    old_filter = str(stop.get(CONF_DESTINATION_FILTER) or "").strip()
    if not line_targets and old_filter and lines:
        line_targets = {line: [old_filter] for line in lines}

    return {
        CONF_STOP_ID: str(stop.get(CONF_STOP_ID) or stop.get(CONF_STOP_LID) or ""),
        CONF_STOP_LID: str(stop.get(CONF_STOP_LID) or ""),
        CONF_STOP_NAME: str(stop.get(CONF_STOP_NAME) or ""),
        CONF_STOP_CITY: str(stop.get(CONF_STOP_CITY) or default_city),
        CONF_LINES: lines,
        CONF_LINE_TARGETS: line_targets,
        CONF_WALKING_MINUTES: _clamp(
            _as_int(stop.get(CONF_WALKING_MINUTES), DEFAULT_WALKING_MINUTES),
            MIN_WALKING_MINUTES,
            MAX_WALKING_MINUTES,
        ),
    }


def stops_from_subentries(subentries: Any, default_city: str) -> list[dict[str, Any]]:
    """Convert config subentries of type ``stop`` into normalized stops."""
    stops: list[dict[str, Any]] = []
    seen: set[str] = set()
    for subentry in subentries or []:
        if getattr(subentry, "subentry_type", None) != SUBENTRY_TYPE_STOP:
            continue
        stop = normalize_stop(dict(subentry.data), default_city)
        if (
            not stop[CONF_STOP_ID]
            or not stop[CONF_STOP_LID]
            or not stop[CONF_STOP_NAME]
        ):
            continue
        if stop[CONF_STOP_ID] in seen:
            continue
        seen.add(stop[CONF_STOP_ID])
        stop[CONF_SUBENTRY_ID] = subentry.subentry_id
        stops.append(stop)
    return stops


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
        CONF_HOLIDAY_ENTITY: None,
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
    holiday_entity = str(config.get(CONF_HOLIDAY_ENTITY) or "").strip()
    config[CONF_HOLIDAY_ENTITY] = holiday_entity or None
    return config
