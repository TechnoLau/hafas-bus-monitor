"""Sensor platform for HAFAS Bus Monitor."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import HafasDeparture
from .const import (
    ACTIVE_HOURS_TEXT,
    ATTR_ACTIVE_HOURS,
    ATTR_ALL_DEPARTURES,
    ATTR_BEST,
    ATTR_CITY,
    ATTR_DEPARTURE_COUNT,
    ATTR_DEPARTURES,
    ATTR_ERROR,
    ATTR_LAST_UPDATE,
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
    CONF_LINE_TARGETS,
    CONF_LINES,
    CONF_ROUTING_ENABLED,
    CONF_SCAN_MINUTES,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_STOPS,
    CONF_WALKING_MINUTES,
    DOMAIN,
    MAX_DEPARTURES,
    SELECTION_METHOD,
    VERSION,
)
from .coordinator import HafasDataUpdateCoordinator
from .routing import RoutingResult, evaluate_routing
from .util import short_stop_name


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up stop and routing sensors from a config entry."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: HafasDataUpdateCoordinator = runtime["coordinator"]
    config: dict[str, Any] = runtime["config"]

    entities: list[SensorEntity] = [
        HafasStopSensor(coordinator, entry, config, stop)
        for stop in config.get(CONF_STOPS, [])
    ]
    if config.get(CONF_ROUTING_ENABLED, True):
        entities.append(HafasRoutingSensor(coordinator, entry, config))

    async_add_entities(entities)


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
                f"{departure.line} → {departure.destination} · "
                f"{departure.departure:%H:%M}"
            ),
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
    def device_info(self) -> DeviceInfo:
        """Return device information shared by all entities of this entry."""
        city = str(self._config.get(CONF_CITY) or "").strip()
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="HAFAS",
            manufacturer="NAH.SH / HAFAS",
            model=f"Busabfahrten {city}".strip(),
            sw_version=VERSION,
            configuration_url="https://www.nah.sh/",
        )


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
        self._short_name = short_stop_name(
            str(stop.get(CONF_STOP_NAME) or ""),
            str(stop.get("city") or config.get(CONF_CITY) or ""),
        )
        self._attr_name = self._short_name or "Haltestelle"
        self._attr_unique_id = (
            f"{entry.entry_id}_{stop.get(CONF_STOP_ID, 'stop')}_departures"
        )

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
        """Return the tile text: line, destination and departure time."""
        if self._pause_label is not None:
            return self._pause_label
        payloads = self._departure_payloads
        for payload in payloads:
            if payload["reachable"] and not payload["cancelled"]:
                return (
                    f"{payload['display_short']} · "
                    f"{payload['minutes_until_departure']} Min"
                )
        if self._stop_data is None:
            return None
        return "Keine erreichbare Abfahrt"

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
        ][:MAX_DEPARTURES]

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
            ][:MAX_DEPARTURES]

        return {
            ATTR_STOP: self._stop.get(CONF_STOP_NAME),
            ATTR_STOP_ID: self._stop.get(CONF_STOP_ID),
            ATTR_CITY: self._stop.get("city") or self._config.get(CONF_CITY),
            ATTR_LINES: list(self._stop.get(CONF_LINES) or []),
            ATTR_LINE_TARGETS: dict(self._stop.get(CONF_LINE_TARGETS) or {}),
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
