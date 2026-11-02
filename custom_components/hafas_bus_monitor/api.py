"""Minimal async HAFAS client used by the Home Assistant integration.

The integration deliberately speaks the HAFAS ``mgate`` JSON protocol
directly instead of depending on a third-party HAFAS package.  This keeps the
HACS installation dependency-free and lets us handle the NAH.SH deployment
(Kiel / Schleswig-Holstein) precisely.

Only two HAFAS methods are needed:

* ``LocMatch``     – resolve a city + stop name to a HAFAS location id
* ``StationBoard`` – fetch the next departures at that location

The code is intentionally defensive: HAFAS deployments are not perfectly
uniform and fields that are optional in one response may be missing in
another.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    HAFAS_AUTH,
    HAFAS_BUS_PRODUCT_MASK,
    HAFAS_CLIENT,
    HAFAS_ENDPOINT,
    HAFAS_FALLBACK_ENDPOINT,
    HAFAS_LANGUAGE,
    HAFAS_TIMEZONE,
    HAFAS_USER_AGENT,
    HAFAS_VERSION,
    MAX_DEPARTURES,
    MAX_LOCATION_RESULTS,
)
from .util import line_matches, normalize_lines

_LOGGER = logging.getLogger(__name__)
_HAFAS_TZ = ZoneInfo(HAFAS_TIMEZONE)
_BUS_NAME_PREFIX_RE = re.compile(
    r"^(?:bus|zug|s-bahn|u-bahn|tram|fähre|faehre|regionalbus)\s+",
    re.IGNORECASE,
)


class HafasError(Exception):
    """Base class for HAFAS errors."""


class HafasConnectionError(HafasError):
    """Raised when the HAFAS endpoint cannot be reached/parsed."""


class HafasApiError(HafasError):
    """Raised when HAFAS returns a protocol error."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class HafasStop:
    """A stop resolved via HAFAS LocMatch."""

    stop_id: str
    lid: str
    name: str
    latitude: float | None = None
    longitude: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "id": self.stop_id,
            "lid": self.lid,
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


@dataclass(slots=True)
class HafasDeparture:
    """One parsed departure."""

    line: str
    line_name: str | None
    line_id: str | None
    destination: str
    departure: datetime
    planned_departure: datetime
    delay_seconds: int
    minutes_until: int
    platform: str | None
    cancelled: bool
    realtime: bool
    trip_id: str | None
    stop_name: str | None

    @property
    def delay_minutes(self) -> int:
        """Return the delay rounded to whole minutes."""
        return round(self.delay_seconds / 60)

    def as_dict(self) -> dict[str, Any]:
        """Return the attribute representation used by the sensor."""
        return {
            "line": self.line,
            "line_name": self.line_name or f"Linie {self.line}",
            "line_id": self.line_id,
            "destination": self.destination,
            "departure_time": self.departure.isoformat(),
            "departure_time_local": self.departure.strftime("%H:%M"),
            "planned_departure_time": self.planned_departure.isoformat(),
            "planned_departure_time_local": self.planned_departure.strftime("%H:%M"),
            "delay": self.delay_minutes,
            "delay_minutes": self.delay_minutes,
            "delay_seconds": self.delay_seconds,
            "minutes_until_departure": self.minutes_until,
            "platform": self.platform,
            "cancelled": self.cancelled,
            "realtime": self.realtime,
            "trip_id": self.trip_id,
            "stop_name": self.stop_name,
        }


@dataclass(slots=True)
class StopDepartures:
    """Departure board for one stop."""

    stop: HafasStop
    departures: list[HafasDeparture]
    all_departures: list[HafasDeparture]
    fetched_at: datetime
    scan_minutes: int

    @property
    def next_departure(self) -> HafasDeparture | None:
        """Return the first non-cancelled, line-filtered departure."""
        for departure in self.departures:
            if not departure.cancelled:
                return departure
        return None


def _ensure_aware(value: datetime | None) -> datetime:
    """Return a timezone-aware datetime in the HAFAS timezone."""
    if value is None:
        return datetime.now(_HAFAS_TZ)
    if value.tzinfo is None:
        return value.replace(tzinfo=_HAFAS_TZ)
    return value


def _parse_hafas_datetime(
    date_value: str | None, time_value: str | None
) -> datetime | None:
    """Parse HAFAS ``YYYYMMDD`` + ``HHMMSS`` values robustly.

    HAFAS sometimes uses hours >= 24 for trips after midnight.  Using a
    timedelta instead of ``datetime(...)`` handles that correctly.
    """
    if not date_value or not time_value:
        return None

    date_text = "".join(ch for ch in str(date_value) if ch.isdigit())
    time_text = "".join(ch for ch in str(time_value) if ch.isdigit())
    if len(date_text) < 8 or len(time_text) < 3:
        return None

    try:
        base = datetime.strptime(date_text[:8], "%Y%m%d").replace(tzinfo=_HAFAS_TZ)
        hours = int(time_text[0:2])
        minutes = int(time_text[2:4]) if len(time_text) >= 4 else 0
        seconds = int(time_text[4:6]) if len(time_text) >= 6 else 0
        return base + timedelta(hours=hours, minutes=minutes, seconds=seconds)
    except (TypeError, ValueError):
        return None


def _error_text(payload: dict[str, Any]) -> str:
    """Build a compact error message from a HAFAS error response."""
    pieces: list[str] = []
    for key in ("errTxt", "errTxtOut", "hammError", "err"):
        value = payload.get(key)
        if value and value != "OK":
            pieces.append(str(value))
    message = " | ".join(pieces) or "Unknown HAFAS error"
    if len(message) > 500:
        message = message[:497] + "..."
    return message


def _extract_service_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a HAFAS response and return the first service result."""
    if not isinstance(payload, dict):
        raise HafasConnectionError("HAFAS returned an invalid JSON document")

    if payload.get("err") and payload["err"] != "OK":
        raise HafasApiError(_error_text(payload), payload.get("err"))

    service_results = payload.get("svcResL")
    if not isinstance(service_results, list) or not service_results:
        raise HafasApiError(_error_text(payload), payload.get("err"))

    service = service_results[0]
    if not isinstance(service, dict):
        raise HafasConnectionError("HAFAS service result has an invalid structure")

    if service.get("err") and service["err"] != "OK":
        raise HafasApiError(_error_text(service), service.get("err"))

    result = service.get("res")
    if not isinstance(result, dict):
        raise HafasConnectionError("HAFAS service result does not contain data")
    return result


def _location_id_from_lid(lid: str) -> str:
    """Extract the ``L=...`` id from a HAFAS location id."""
    match = re.search(r"(?:^|@)L=([^@]+)", lid)
    return match.group(1) if match else lid


def parse_location_response(payload: dict[str, Any]) -> list[HafasStop]:
    """Parse a ``LocMatch`` response into :class:`HafasStop` objects."""
    result = _extract_service_result(payload)
    match = result.get("match") or {}
    raw_locations = match.get("locL") or []
    if not isinstance(raw_locations, list):
        return []

    stops: list[HafasStop] = []
    seen: set[str] = set()
    for raw in raw_locations:
        if not isinstance(raw, dict):
            continue
        if raw.get("type") and raw.get("type") != "S":
            continue

        lid = str(raw.get("lid") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not name:
            continue

        stop_id = str(raw.get("extId") or "").strip()
        if not stop_id:
            stop_id = _location_id_from_lid(lid)
        if not lid:
            if not stop_id:
                continue
            lid = f"A=1@L={stop_id}@"

        if stop_id in seen:
            continue
        seen.add(stop_id)

        latitude: float | None = None
        longitude: float | None = None
        coordinates = raw.get("crd")
        if isinstance(coordinates, dict):
            try:
                latitude = float(coordinates["y"]) / 1_000_000
                longitude = float(coordinates["x"]) / 1_000_000
            except (KeyError, TypeError, ValueError):
                latitude = longitude = None

        stops.append(
            HafasStop(
                stop_id=stop_id,
                lid=lid,
                name=name,
                latitude=latitude,
                longitude=longitude,
            )
        )

    return stops


def _product_for_departure(
    raw_departure: dict[str, Any],
    products: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the product (line) belonging to a departure."""
    stop = raw_departure.get("stbStop") or {}
    product_index = raw_departure.get("prodX", stop.get("dProdX"))
    try:
        index = int(product_index)
    except (TypeError, ValueError):
        return {}, {}

    if index < 0 or index >= len(products):
        return {}, {}
    product = products[index]
    if not isinstance(product, dict):
        return {}, {}
    product_context = product.get("prodCtx") or {}
    if not isinstance(product_context, dict):
        product_context = {}
    return product, product_context


def _line_from_product(
    product: dict[str, Any],
    product_context: dict[str, Any],
) -> tuple[str, str | None, str | None]:
    """Extract line label, line name and line id from a HAFAS product."""
    line = str(product_context.get("line") or "").strip()
    line_name = (
        str(product.get("name") or product_context.get("name") or "").strip() or None
    )

    if not line:
        fallback = line_name or str(product_context.get("catOut") or "").strip()
        fallback = _BUS_NAME_PREFIX_RE.sub("", fallback).strip()
        line = fallback

    line_id = str(product_context.get("lineId") or "").strip() or None
    return line or "?", line_name, line_id


def _platform_from_stop(stop: dict[str, Any], prefix: str) -> str | None:
    """Read a platform from the different HAFAS field spellings."""
    for key in (
        f"{prefix}PltfR",
        f"{prefix}PlatfR",
        f"{prefix}PltfS",
        f"{prefix}PlatfS",
    ):
        value = stop.get(key)
        if isinstance(value, dict):
            value = value.get("txt") or value.get("name")
        if value:
            return str(value).strip()
    return None


def _destination_from_departure(
    raw_departure: dict[str, Any],
    common_locations: list[dict[str, Any]],
    product_context: dict[str, Any],
) -> str:
    """Determine the destination shown on the departure board."""
    for key in ("dirTxt", "destination", "direction"):
        value = raw_departure.get(key)
        if value:
            return str(value).strip()

    nested_products = raw_departure.get("prodL") or []
    if nested_products and isinstance(nested_products[0], dict):
        try:
            target_index = int(nested_products[0].get("tLocX"))
        except (TypeError, ValueError):
            target_index = -1
        if 0 <= target_index < len(common_locations):
            target = common_locations[target_index]
            if isinstance(target, dict) and target.get("name"):
                return str(target["name"]).strip()

    return str(product_context.get("name") or "Unbekannt").strip()


def parse_station_board_response(
    payload: dict[str, Any],
    stop: HafasStop,
    *,
    now: datetime | None = None,
    scan_minutes: int = 60,
    lines: Iterable[str] | None = None,
    max_departures: int = MAX_DEPARTURES,
) -> StopDepartures:
    """Parse a ``StationBoard`` response.

    All departures are kept in ``all_departures``.  ``departures`` contains
    only the configured lines (or every line if the filter is empty).
    Cancelled departures remain visible in the attributes, but are skipped by
    the ``next_departure`` property and by the routing sensor.
    """
    reference = _ensure_aware(now)
    preferred_lines = normalize_lines(lines)
    result = _extract_service_result(payload)
    common = result.get("common") or {}
    if not isinstance(common, dict):
        common = {}

    products = common.get("prodL") or []
    common_locations = common.get("locL") or []
    if not isinstance(products, list):
        products = []
    if not isinstance(common_locations, list):
        common_locations = []

    raw_departures = result.get("jnyL") or []
    if not isinstance(raw_departures, list):
        raw_departures = []

    scan_until = reference + timedelta(minutes=max(1, int(scan_minutes)))
    seen: set[tuple[str, str, str, str]] = set()
    parsed: list[HafasDeparture] = []

    for raw in raw_departures:
        if not isinstance(raw, dict):
            continue
        stop_data = raw.get("stbStop") or {}
        if not isinstance(stop_data, dict):
            continue

        planned_raw = stop_data.get("dTimeS") or stop_data.get("dTime")
        actual_raw = stop_data.get("dTimeR") or planned_raw
        date_raw = raw.get("date") or reference.strftime("%Y%m%d")

        planned = _parse_hafas_datetime(str(date_raw), planned_raw)
        actual = _parse_hafas_datetime(str(date_raw), actual_raw) or planned
        if planned is None or actual is None:
            continue

        if actual < reference - timedelta(seconds=90):
            continue
        if actual > scan_until + timedelta(seconds=90):
            continue

        product, product_context = _product_for_departure(raw, products)
        line, line_name, line_id = _line_from_product(product, product_context)
        destination = _destination_from_departure(
            raw, common_locations, product_context
        )
        cancelled = bool(
            stop_data.get("dCncl")
            or stop_data.get("dCancelled")
            or raw.get("cancelled")
            or str(stop_data.get("dProgType") or "").upper()
            in {"CANCELLED", "CANCELED", "CANCEL"}
        )
        realtime = bool(stop_data.get("dTimeR"))
        trip_id = str(raw.get("jid") or "").strip() or None

        stop_name: str | None = None
        try:
            location_index = int(stop_data.get("locX"))
        except (TypeError, ValueError):
            location_index = -1
        if 0 <= location_index < len(common_locations):
            location = common_locations[location_index]
            if isinstance(location, dict):
                stop_name = str(location.get("name") or "").strip() or None

        dedupe_key = (
            trip_id or "",
            line,
            destination,
            actual.isoformat(),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        delay_seconds = int((actual - planned).total_seconds())
        minutes_until = max(0, int((actual - reference).total_seconds() // 60))

        parsed.append(
            HafasDeparture(
                line=line,
                line_name=line_name,
                line_id=line_id,
                destination=destination,
                departure=actual,
                planned_departure=planned,
                delay_seconds=delay_seconds,
                minutes_until=minutes_until,
                platform=_platform_from_stop(stop_data, "d"),
                cancelled=cancelled,
                realtime=realtime,
                trip_id=trip_id,
                stop_name=stop_name,
            )
        )

    parsed.sort(key=lambda departure: departure.departure)
    filtered = [
        departure
        for departure in parsed
        if line_matches(departure.line, preferred_lines)
    ]

    limit = max(1, int(max_departures))
    return StopDepartures(
        stop=stop,
        departures=filtered[:limit],
        all_departures=parsed[:limit],
        fetched_at=reference,
        scan_minutes=int(scan_minutes),
    )


class HafasClient:
    """Small async client for the NAH.SH HAFAS mgate endpoint."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        endpoint: str = HAFAS_ENDPOINT,
        fallback_endpoint: str | None = HAFAS_FALLBACK_ENDPOINT,
        user_agent: str = HAFAS_USER_AGENT,
        timeout: float = 20.0,
    ) -> None:
        self._session = session
        self._endpoints = [endpoint]
        if fallback_endpoint and fallback_endpoint != endpoint:
            self._endpoints.append(fallback_endpoint)
        self._user_agent = user_agent
        self._timeout = timeout

    async def _post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST one request to one endpoint."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        try:
            async with self._session.post(
                endpoint,
                json=body,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
            ) as response:
                text = await response.text()
                if response.status >= 400:
                    raise HafasConnectionError(
                        f"HAFAS HTTP {response.status}: {text[:300]}"
                    )
                try:
                    payload = json.loads(text)
                except (TypeError, ValueError) as err:
                    raise HafasConnectionError(
                        f"HAFAS returned no valid JSON: {text[:300]}"
                    ) from err
                if not isinstance(payload, dict):
                    raise HafasConnectionError("HAFAS returned an unexpected JSON type")
                return payload
        except TimeoutError as err:
            raise HafasConnectionError("Timeout while talking to HAFAS") from err
        except aiohttp.ClientError as err:
            raise HafasConnectionError(
                f"Connection error while talking to HAFAS: {err}"
            ) from err

    async def _request(
        self,
        method: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a HAFAS service request and return the raw response."""
        body = {
            "lang": HAFAS_LANGUAGE,
            "svcReqL": [{"meth": method, "req": request, "id": "1"}],
            "client": HAFAS_CLIENT,
            "ver": HAFAS_VERSION,
            "auth": HAFAS_AUTH,
        }

        last_error: Exception | None = None
        for endpoint in self._endpoints:
            try:
                payload = await self._post(endpoint, body)
                _extract_service_result(payload)
                return payload
            except HafasConnectionError as err:
                last_error = err
                _LOGGER.debug("HAFAS endpoint %s failed: %s", endpoint, err)
                continue
            # HafasApiError is a valid response from the API and must not be
            # hidden by trying the fallback endpoint.

        raise HafasConnectionError(
            f"All HAFAS endpoints failed: {last_error}"
        ) from last_error

    async def search_stops(
        self,
        query: str,
        *,
        city: str | None = None,
        limit: int = MAX_LOCATION_RESULTS,
    ) -> list[HafasStop]:
        """Resolve a stop name to a list of HAFAS stops."""
        clean_query = " ".join(str(query or "").split())
        if not clean_query:
            return []

        request_limit = max(20, int(limit))
        payload = await self._request(
            "LocMatch",
            {
                "input": {
                    "loc": {"type": "S", "name": clean_query},
                    "maxLoc": request_limit,
                    "field": "S",
                }
            },
        )
        stops = parse_location_response(payload)

        if city:
            city_key = city.strip().casefold()
            if city_key:
                # Keep HAFAS' relevance order inside the city, but put exact
                # city matches before fuzzy hits from other cities.
                indexed = list(enumerate(stops))
                indexed.sort(
                    key=lambda pair: (
                        not pair[1].name.casefold().startswith(city_key + " "),
                        pair[0],
                    )
                )
                stops = [item for _, item in indexed]
        return stops[: max(1, int(limit))]

    async def fetch_departures(
        self,
        stop: HafasStop,
        *,
        now: datetime | None = None,
        scan_minutes: int = 60,
        lines: Iterable[str] | None = None,
        max_jny: int = 100,
    ) -> StopDepartures:
        """Fetch and parse the next departures at ``stop``."""
        reference = _ensure_aware(now)
        payload = await self._request(
            "StationBoard",
            {
                "type": "DEP",
                "date": reference.strftime("%Y%m%d"),
                "time": reference.strftime("%H%M%S"),
                "stbLoc": {"type": "S", "lid": stop.lid},
                "jnyFltrL": [
                    {
                        "type": "PROD",
                        "mode": "INC",
                        "value": str(HAFAS_BUS_PRODUCT_MASK),
                    }
                ],
                "dur": max(1, int(scan_minutes)),
                "maxJny": max(1, int(max_jny)),
            },
        )
        return parse_station_board_response(
            payload,
            stop,
            now=reference,
            scan_minutes=scan_minutes,
            lines=lines,
        )
