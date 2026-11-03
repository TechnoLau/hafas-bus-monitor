"""Sensor platform for HAFAS Bus Monitor."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import HafasDeparture
from .const import (
    ACTIVE_HOURS_TEXT,
    ATTR_ACTIVE_HOURS,
    ATTR_ALL_DEPARTURES,
    ATTR_BEST,
    ATTR_CITY,
    ATTR_DEPARTURE_COUNT,
    ATTR_DEPARTURES,
    ATTR_DISTANCE_M,
    ATTR_ERROR,
    ATTR_LAST_UPDATE,
    ATTR_LINE_COLORS,
    ATTR_LINE_TARGETS,
    ATTR_LINES,
    ATTR_MINUTES_UNTIL_DEPARTURE,
    ATTR_NEXT_DEPARTURE,
    ATTR_OPTIONS,
    ATTR_PAUSED_REASON,
    ATTR_SCAN_MINUTES,
    ATTR_SELECTION_METHOD,
    ATTR_STOP,
    ATTR_STOP_ID,
    ATTR_UNREACHABLE_DEPARTURES,
    ATTR_WALKING_MINUTES,
    CONF_CITY,
    CONF_DEVICE_TRACKER,
    CONF_GEOCODED_SENSOR,
    CONF_LINE_TARGETS,
    CONF_LINES,
    CONF_ROUTING_ENABLED,
    CONF_SCAN_MINUTES,
    CONF_STOP_ID,
    CONF_STOP_LAT,
    CONF_STOP_LON,
    CONF_STOP_NAME,
    CONF_STOPS,
    CONF_SUBENTRY_ID,
    CONF_WALKING_MINUTES,
    DISPLAY_MINUTES_THRESHOLD,
    DOMAIN,
    MAX_ALL_DEPARTURES,
    MAX_DEPARTURES,
    MAX_UNREACHABLE_DEPARTURES,
    SELECTION_METHOD,
)
from .coordinator import HafasDataUpdateCoordinator
from .routing import RoutingResult, evaluate_routing
from .util import haversine_m, line_color, short_stop_name


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up stop and routing sensors from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: HafasDataUpdateCoordinator = runtime["coordinator"]
    config: dict[str, Any] = runtime["config"]

    stops = list(config.get(CONF_STOPS, []))
    if not stops:
        return

    for stop in stops:
        entity = HafasStopSensor(coordinator, entry, config, stop)
        subentry_id = stop.get(CONF_SUBENTRY_ID)
        if subentry_id:
            async_add_entities([entity], config_subentry_id=str(subentry_id))
        else:
            async_add_entities([entity])

    if config.get(CONF_ROUTING_ENABLED, True):
        async_add_entities([HafasRoutingSensor(coordinator, entry, config)])
    if config.get(CONF_DEVICE_TRACKER) or config.get(CONF_GEOCODED_SENSOR):
        async_add_entities([HafasNearestStopSensor(coordinator, entry, config)])


def _pause_label(reason: str | None) -> str | None:
    """Return a short dashboard label for a paused coordinator."""
    if reason == "holiday":
        return "Ferien"
    if reason == "outside_hours":
        return "Ruhezeit"
    return None


def _departure_payload(
    departure: HafasDeparture,
    now: datetime,
    walking_minutes: int,
    *,
    stop_name: str | None = None,
) -> dict[str, Any]:
    """Return every parsed field plus reachability information."""
    payload = departure.as_dict()
    seconds_until = max(0, int((departure.departure - now).total_seconds()))
    minutes_until = seconds_until // 60
    reachable = (not departure.cancelled) and seconds_until >= walking_minutes * 60
    payload.update(
        {
            "walking_minutes": walking_minutes,
            "minutes_until_departure": minutes_until,
            "leave_in_minutes": max(0, minutes_until - walking_minutes),
            "reachable": reachable,
            "display_short": (
                f"{departure.line} | {departure.destination} · "
                f"{departure.departure:%H:%M}"
            ),
            "line_destination": f"{departure.line} | {departure.destination}",
            "time_text": (
                f"in {minutes_until} min"
                if minutes_until < DISPLAY_MINUTES_THRESHOLD
                else departure.departure.strftime("%H:%M")
            ),
            "line_color": line_color(departure.line),
        }
    )
    return payload


class _HafasBaseSensor(CoordinatorEntity[HafasDataUpdateCoordinator], SensorEntity):
    """Common base for the integration's sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HafasDataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._config = config

    @property
    def _pause_reason(self) -> str | None:
        """Return the coordinator's pause reason, if any."""
        return self.coordinator.pause_reason

    @property
    def _pause_label(self) -> str | None:
        """Return 'Ferien' or 'Ruhezeit' while paused."""
        return _pause_label(self._pause_reason)

    @property
    def device_info(self):
        """Do not attach a device; the friendly name stays the stop/function name."""
        return None


class HafasStopSensor(_HafasBaseSensor):
    """Next reachable departure plus a complete departure data set."""

    _attr_icon = "mdi:bus-clock"

    def __init__(
        self,
        coordinator: HafasDataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict[str, Any],
        stop: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry, config)
        self._stop = stop
        self._subentry_id = stop.get(CONF_SUBENTRY_ID)
        self._short_name = short_stop_name(
            str(stop.get(CONF_STOP_NAME) or ""),
            str(stop.get("city") or config.get(CONF_CITY) or ""),
        )
        self._attr_name = self._short_name or "Haltestelle"
        self._attr_unique_id = (
            f"{entry.entry_id}_{stop.get(CONF_STOP_ID, 'stop')}_departures"
        )
        self._last_next_trip: str | None = None
        self._last_next_minutes: int | None = None

    @property
    def device_info(self):
        """Keep stop entities without a device so the friendly name is just the stop."""
        return None

    @property
    def suggested_object_id(self) -> str:
        """Return the historical hafas_<stop> entity id."""
        return f"hafas_{slugify(self._short_name) or 'stop'}"

    @property
    def _stop_data(self):
        """Return this stop's current board."""
        return self.coordinator.stop_data(str(self._stop[CONF_STOP_ID]))

    @property
    def _walking_minutes(self) -> int:
        """Return the configured walking time."""
        return max(0, int(self._stop.get(CONF_WALKING_MINUTES) or 0))

    @property
    def _departure_payloads(self) -> list[dict[str, Any]]:
        """Return all line/target-filtered departures with details."""
        data = self._stop_data
        if data is None:
            return []
        return [
            _departure_payload(
                departure,
                data.fetched_at,
                self._walking_minutes,
                stop_name=str(self._stop.get(CONF_STOP_NAME) or ""),
            )
            for departure in data.departures
        ]

    @property
    def available(self) -> bool:
        """Return true when paused or when this stop has current data."""
        return super().available and (
            self._pause_reason is not None or self._stop_data is not None
        )

    @property
    def native_value(self) -> str | None:
        """Return the tile text: line, destination and departure time.

        Within the same trip the minute countdown never increases.  HAFAS
        real-time corrections can move a departure a minute or two later;
        without this guard the tile would visibly jump backwards.
        """
        if self._pause_label is not None:
            self._last_next_trip = None
            self._last_next_minutes = None
            return self._pause_label

        payloads = self._departure_payloads
        next_payload = None
        for payload in payloads:
            if payload["reachable"] and not payload["cancelled"]:
                next_payload = payload
                break

        if next_payload is None:
            self._last_next_trip = None
            self._last_next_minutes = None
            if self._stop_data is None:
                return None
            return "Keine erreichbare Abfahrt"

        trip_key = str(
            next_payload.get("trip_id")
            or f"{next_payload['line']}|{next_payload['departure_time']}"
        )
        actual_minutes = int(next_payload["minutes_until_departure"])
        display_minutes = actual_minutes
        if trip_key == self._last_next_trip and self._last_next_minutes is not None:
            display_minutes = min(actual_minutes, self._last_next_minutes)
        self._last_next_trip = trip_key
        self._last_next_minutes = display_minutes

        if display_minutes < DISPLAY_MINUTES_THRESHOLD:
            time_text = f"in {display_minutes} min"
        else:
            time_text = next_payload["time_text"]
        return f"{next_payload['line_destination']} · {time_text}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the complete parsed HAFAS data for dashboards/automations."""
        data = self._stop_data
        payloads = self._departure_payloads
        all_reachable = [
            payload
            for payload in payloads
            if payload["reachable"] and not payload["cancelled"]
        ]
        next_departure = all_reachable[0] if all_reachable else None
        reachable = all_reachable[:MAX_DEPARTURES]
        unreachable = [
            payload
            for payload in payloads
            if not payload["reachable"] and not payload["cancelled"]
        ][:MAX_UNREACHABLE_DEPARTURES]

        fetched_at = data.fetched_at if data is not None else None
        if fetched_at is None and self.coordinator.data:
            fetched_at = self.coordinator.data.get("fetched_at")

        all_departures: list[dict[str, Any]] = []
        if data is not None:
            all_departures = [
                _departure_payload(
                    departure,
                    data.fetched_at,
                    self._walking_minutes,
                    stop_name=str(self._stop.get(CONF_STOP_NAME) or ""),
                )
                for departure in data.all_departures
            ][:MAX_ALL_DEPARTURES]

        return {
            ATTR_STOP: self._stop.get(CONF_STOP_NAME),
            ATTR_STOP_ID: self._stop.get(CONF_STOP_ID),
            ATTR_CITY: self._stop.get("city") or self._config.get(CONF_CITY),
            ATTR_LINES: list(self._stop.get(CONF_LINES) or []),
            ATTR_LINE_TARGETS: dict(self._stop.get(CONF_LINE_TARGETS) or {}),
            ATTR_LINE_COLORS: {
                **{
                    line: line_color(line)
                    for line in (self._stop.get(CONF_LINES) or [])
                },
                **{payload["line"]: payload["line_color"] for payload in payloads},
            },
            ATTR_WALKING_MINUTES: self._walking_minutes,
            ATTR_SCAN_MINUTES: int(self._config.get(CONF_SCAN_MINUTES) or 0),
            ATTR_DEPARTURES: reachable,
            ATTR_UNREACHABLE_DEPARTURES: unreachable,
            ATTR_ALL_DEPARTURES: all_departures,
            ATTR_DEPARTURE_COUNT: len(reachable),
            ATTR_NEXT_DEPARTURE: next_departure,
            ATTR_MINUTES_UNTIL_DEPARTURE: (
                next_departure["minutes_until_departure"] if next_departure else None
            ),
            ATTR_LAST_UPDATE: fetched_at.isoformat() if fetched_at else None,
            ATTR_ERROR: self.coordinator.stop_error(str(self._stop[CONF_STOP_ID])),
            ATTR_PAUSED_REASON: self._pause_reason,
            ATTR_ACTIVE_HOURS: ACTIVE_HOURS_TEXT,
            "paused": self._pause_reason is not None,
        }


class HafasRoutingSensor(_HafasBaseSensor):
    """Compare all stops and show the fastest reachable bus."""

    _attr_icon = "mdi:bus-marker"

    def __init__(
        self,
        coordinator: HafasDataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry, config)
        self._attr_name = "Schnellste Verbindung"
        self._attr_unique_id = f"{entry.entry_id}_fastest_connection"

    @property
    def suggested_object_id(self) -> str:
        """Return the historical hafas_schnellste_verbindung entity id."""
        return "hafas_schnellste_verbindung"

    @property
    def _routing(self) -> RoutingResult:
        """Evaluate routing against the coordinator's latest fetch time."""
        if self._pause_reason is not None:
            return RoutingResult(best=None, options=[], reason=self._pause_reason)

        fetched_at = None
        if self.coordinator.data:
            fetched_at = self.coordinator.data.get("fetched_at")
        if fetched_at is None:
            return RoutingResult(best=None, options=[], reason="no_data")

        stop_data = {
            str(stop[CONF_STOP_ID]): self.coordinator.stop_data(str(stop[CONF_STOP_ID]))
            for stop in self._config.get(CONF_STOPS, [])
        }
        loaded = {
            stop_id: board for stop_id, board in stop_data.items() if board is not None
        }
        return evaluate_routing(
            list(self._config.get(CONF_STOPS, [])),
            loaded,
            fetched_at,
        )

    @property
    def native_value(self) -> str:
        """Return e.g. 'Linie 61 ab Kunsthalle in 4 Min'."""
        if self._pause_label is not None:
            return self._pause_label
        return self._routing.state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the winning route and all compared options."""
        routing = self._routing
        stops = self._config.get(CONF_STOPS, [])
        return {
            ATTR_BEST: routing.best.as_dict() if routing.best else None,
            ATTR_OPTIONS: routing.options,
            "reason": routing.reason,
            ATTR_SELECTION_METHOD: SELECTION_METHOD,
            ATTR_LINE_COLORS: {
                option["line"]: option["line_color"]
                for option in routing.options
                if option.get("line_color")
            },
            "stops": [
                {
                    ATTR_STOP_ID: stop.get(CONF_STOP_ID),
                    ATTR_STOP: stop.get(CONF_STOP_NAME),
                    ATTR_WALKING_MINUTES: int(stop.get(CONF_WALKING_MINUTES) or 0),
                    ATTR_LINES: list(stop.get(CONF_LINES) or []),
                    ATTR_LINE_TARGETS: dict(stop.get(CONF_LINE_TARGETS) or {}),
                }
                for stop in stops
            ],
            ATTR_LAST_UPDATE: (
                self.coordinator.data.get("fetched_at").isoformat()
                if self.coordinator.data and self.coordinator.data.get("fetched_at")
                else None
            ),
            ATTR_PAUSED_REASON: self._pause_reason,
            ATTR_ACTIVE_HOURS: ACTIVE_HOURS_TEXT,
            "paused": self._pause_reason is not None,
        }


class HafasNearestStopSensor(_HafasBaseSensor):
    """Show departures of the configured stop nearest to the phone GPS."""

    _attr_name = "Nächste Haltestelle"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(
        self,
        coordinator: HafasDataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict[str, Any],
    ) -> None:
        super().__init__(coordinator, entry, config)
        self._attr_unique_id = f"{entry.entry_id}_nearest_stop"
        self._last_next_trip: str | None = None
        self._last_next_minutes: int | None = None

    @property
    def suggested_object_id(self) -> str:
        """Return the historical hafas_naechste_haltestelle entity id."""
        return "hafas_naechste_haltestelle"

    @property
    def _tracker_state(self):
        """Return the configured tracker state, if present."""
        tracker = self._config.get(CONF_DEVICE_TRACKER)
        return self.hass.states.get(str(tracker)) if tracker else None

    @property
    def _geocoded_state(self):
        """Return the configured geocoded-location sensor state."""
        sensor = self._config.get(CONF_GEOCODED_SENSOR)
        return self.hass.states.get(str(sensor)) if sensor else None

    def _parse_location(self, value: Any) -> tuple[float, float] | None:
        """Parse the Location attribute used by companion geocoded sensors."""
        if value is None:
            return None
        parsed: Any = value
        if isinstance(value, str):
            text = value.strip()
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = text.strip("[]() ")
                parts = [part.strip() for part in parsed.split(",")]
                if len(parts) < 2:
                    return None
                parsed = parts[:2]
        if isinstance(parsed, dict):
            latitude = parsed.get("latitude") or parsed.get("lat")
            longitude = parsed.get("longitude") or parsed.get("lon")
        elif isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
            latitude, longitude = parsed[0], parsed[1]
        else:
            return None
        try:
            lat = float(latitude)
            lon = float(longitude)
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        if lat == 0 and lon == 0:
            return None
        return lat, lon

    def _coordinates_from_state(self, state) -> tuple[float, float] | None:
        """Extract valid coordinates from a state object."""
        if state is None:
            return None
        try:
            latitude = float(state.attributes["latitude"])
            longitude = float(state.attributes["longitude"])
        except (KeyError, TypeError, ValueError):
            coordinates = self._parse_location(
                state.attributes.get("Location") or state.attributes.get("location")
            )
            return coordinates
        if latitude == 0 and longitude == 0:
            return None
        return latitude, longitude

    def _zone_for_state(self, state) -> Any | None:
        """Return a zone matching a tracker state name, if possible."""
        if state is None:
            return None
        key = str(state.state or "").strip().casefold()
        if not key or key in {"not_home", "unknown", "unavailable"}:
            return None
        for zone in self.hass.states.async_all("zone"):
            zone_key = zone.entity_id.split(".", 1)[-1].casefold()
            zone_name = str(
                zone.attributes.get("friendly_name") or zone.name or ""
            ).casefold()
            if key in {zone_key, zone_name}:
                return zone
        return None

    @property
    def _position(self) -> tuple[float, float, str] | None:
        """Return coordinates and their source (tracker or zone centre)."""
        tracker_state = self._tracker_state
        coordinates = self._coordinates_from_state(tracker_state)
        if coordinates is not None:
            return coordinates[0], coordinates[1], "tracker"

        geocoded_coordinates = self._coordinates_from_state(self._geocoded_state)
        if geocoded_coordinates is not None:
            return geocoded_coordinates[0], geocoded_coordinates[1], "geocoded"

        zone = self._zone_for_state(tracker_state)
        zone_coordinates = self._coordinates_from_state(zone)
        if zone_coordinates is not None:
            return (
                zone_coordinates[0],
                zone_coordinates[1],
                f"zone:{zone.entity_id}",
            )
        return None

    @property
    def _tracker_position(self) -> tuple[float, float] | None:
        """Return latitude/longitude from the configured tracker/person."""
        position = self._position
        return (position[0], position[1]) if position else None

    @property
    def _nearest_stop(self) -> tuple[dict[str, Any], float] | None:
        """Return the nearest configured stop and distance in meters."""
        position = self._tracker_position
        if position is None:
            return None
        latitude, longitude = position
        nearest: tuple[dict[str, Any], float] | None = None
        for stop in self._config.get(CONF_STOPS, []):
            stop_lat = stop.get(CONF_STOP_LAT)
            stop_lon = stop.get(CONF_STOP_LON)
            if stop_lat is None or stop_lon is None:
                continue
            distance = haversine_m(
                latitude,
                longitude,
                float(stop_lat),
                float(stop_lon),
            )
            if nearest is None or distance < nearest[1]:
                nearest = (stop, distance)
        return nearest

    @property
    def _nearest_payloads(self) -> tuple[list[dict[str, Any]], str | None]:
        """Return reachable departures and the stop name for the nearest stop."""
        nearest = self._nearest_stop
        if nearest is None:
            return [], None
        stop, _distance = nearest
        data = self.coordinator.stop_data(str(stop.get(CONF_STOP_ID)))
        if data is None:
            return [], str(stop.get(CONF_STOP_NAME) or "")
        walking = max(0, int(stop.get(CONF_WALKING_MINUTES) or 0))
        payloads = [
            _departure_payload(
                departure,
                data.fetched_at,
                walking,
                stop_name=str(stop.get(CONF_STOP_NAME) or ""),
            )
            for departure in data.departures
        ]
        reachable = [
            payload
            for payload in payloads
            if payload["reachable"] and not payload["cancelled"]
        ]
        return reachable, str(stop.get(CONF_STOP_NAME) or "")

    @property
    def native_value(self) -> str | None:
        """Return next departure at the nearest configured stop."""
        if self._pause_label is not None:
            return self._pause_label
        if self._tracker_position is None:
            tracker_state = self._tracker_state
            geocoded_state = self._geocoded_state
            tracker_configured = self._config.get(CONF_DEVICE_TRACKER)
            geocoded_configured = self._config.get(CONF_GEOCODED_SENSOR)
            if tracker_configured and tracker_state is None and not geocoded_configured:
                return "Tracker nicht gefunden"
            if (
                geocoded_configured
                and geocoded_state is None
                and not tracker_configured
            ):
                return "Geocoded-Sensor nicht gefunden"
            if (
                tracker_configured
                and tracker_state is None
                and geocoded_configured
                and geocoded_state is None
            ):
                return "GPS-Quelle nicht gefunden"
            return "Keine GPS-Koordinaten"
        nearest = self._nearest_stop
        if nearest is None:
            return "Keine Koordinaten"
        stop, _distance = nearest
        short = short_stop_name(
            str(stop.get(CONF_STOP_NAME) or ""),
            str(stop.get(CONF_CITY) or ""),
        )
        payloads, _ = self._nearest_payloads
        if payloads:
            first = payloads[0]
            return f"{short}: {first['line_destination']} · {first['time_text']}"
        if self.coordinator.stop_data(str(stop.get(CONF_STOP_ID))) is None:
            return f"{short}: Keine Daten"
        return f"{short}: Keine erreichbare Abfahrt"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the nearest stop, distance and full departure data."""
        nearest = self._nearest_stop
        stop = nearest[0] if nearest else None
        distance = round(nearest[1]) if nearest else None
        payloads, _ = self._nearest_payloads
        next_departure = payloads[0] if payloads else None
        return {
            ATTR_STOP: stop.get(CONF_STOP_NAME) if stop else None,
            ATTR_STOP_ID: stop.get(CONF_STOP_ID) if stop else None,
            ATTR_DISTANCE_M: distance,
            ATTR_WALKING_MINUTES: (
                int(stop.get(CONF_WALKING_MINUTES) or 0) if stop else None
            ),
            "device_tracker": self._config.get(CONF_DEVICE_TRACKER),
            "geocoded_sensor": self._config.get(CONF_GEOCODED_SENSOR),
            "tracker_state": (
                self._tracker_state.state if self._tracker_state else None
            ),
            "geocoded_state": (
                self._geocoded_state.state if self._geocoded_state else None
            ),
            "position_source": (self._position[2] if self._position else None),
            "zone": (
                self._zone_for_state(self._tracker_state).entity_id
                if self._zone_for_state(self._tracker_state)
                else None
            ),
            ATTR_DEPARTURES: payloads,
            ATTR_DEPARTURE_COUNT: len(payloads),
            ATTR_NEXT_DEPARTURE: next_departure,
            ATTR_MINUTES_UNTIL_DEPARTURE: (
                next_departure["minutes_until_departure"] if next_departure else None
            ),
            ATTR_LINE_COLORS: {
                payload["line"]: payload["line_color"] for payload in payloads
            },
            ATTR_LAST_UPDATE: (
                self.coordinator.data.get("fetched_at").isoformat()
                if self.coordinator.data and self.coordinator.data.get("fetched_at")
                else None
            ),
            ATTR_PAUSED_REASON: self._pause_reason,
            ATTR_ACTIVE_HOURS: ACTIVE_HOURS_TEXT,
            "paused": self._pause_reason is not None,
        }
