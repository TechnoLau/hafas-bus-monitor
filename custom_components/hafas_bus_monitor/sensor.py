"""Sensor platform for HAFAS Bus Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ALL_DEPARTURES,
    ATTR_BEST,
    ATTR_CITY,
    ATTR_DEPARTURE_COUNT,
    ATTR_DEPARTURES,
    ATTR_ERROR,
    ATTR_LAST_UPDATE,
    ATTR_LINES,
    ATTR_NEXT_DEPARTURE,
    ATTR_OPTIONS,
    ATTR_SCAN_MINUTES,
    ATTR_SELECTION_METHOD,
    ATTR_STOP,
    ATTR_STOP_ID,
    ATTR_WALKING_MINUTES,
    CONF_CITY,
    CONF_DESTINATION_FILTER,
    CONF_LINES,
    CONF_ROUTING_ENABLED,
    CONF_SCAN_MINUTES,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    CONF_STOPS,
    CONF_WALKING_MINUTES,
    DOMAIN,
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
    """Next departure and departure list for one stop."""

    _attr_icon = "mdi:bus-clock"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "min"

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
    def available(self) -> bool:
        """Return true when this stop has current data."""
        return super().available and self._stop_data is not None

    @property
    def native_value(self) -> int | None:
        """Return minutes until the next filtered departure."""
        data = self._stop_data
        if data is None:
            return None
        next_departure = data.next_departure
        if next_departure is None:
            return None
        return next_departure.minutes_until

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose line, destination, time and delay for every departure."""
        data = self._stop_data
        departures = data.departures if data else []
        all_departures = data.all_departures if data else []
        next_departure = data.next_departure if data else None

        return {
            ATTR_STOP: self._stop.get(CONF_STOP_NAME),
            ATTR_STOP_ID: self._stop.get(CONF_STOP_ID),
            ATTR_CITY: self._stop.get("city") or self._config.get(CONF_CITY),
            ATTR_LINES: list(self._stop.get(CONF_LINES) or []),
            "destination_filter": self._stop.get(CONF_DESTINATION_FILTER) or None,
            ATTR_WALKING_MINUTES: int(self._stop.get(CONF_WALKING_MINUTES) or 0),
            ATTR_SCAN_MINUTES: int(self._config.get(CONF_SCAN_MINUTES) or 0),
            ATTR_DEPARTURES: [item.as_dict() for item in departures],
            ATTR_ALL_DEPARTURES: [item.as_dict() for item in all_departures],
            ATTR_DEPARTURE_COUNT: len(departures),
            ATTR_NEXT_DEPARTURE: next_departure.as_dict() if next_departure else None,
            ATTR_LAST_UPDATE: data.fetched_at.isoformat() if data else None,
            ATTR_ERROR: self.coordinator.stop_error(str(self._stop[CONF_STOP_ID])),
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
        fetched_at = None
        if self.coordinator.data:
            fetched_at = self.coordinator.data.get("fetched_at")
        if fetched_at is None:
            return RoutingResult(best=None, options=[], reason="no_data")

        stop_data = {
            str(stop[CONF_STOP_ID]): self.coordinator.stop_data(str(stop[CONF_STOP_ID]))
            for stop in self._config.get(CONF_STOPS, [])
        }
        # Filter only the successfully loaded boards; evaluate_routing handles
        # missing values explicitly.
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
                    "destination_filter": stop.get(CONF_DESTINATION_FILTER) or None,
                }
                for stop in stops
            ],
            ATTR_LAST_UPDATE: (
                self.coordinator.data.get("fetched_at").isoformat()
                if self.coordinator.data and self.coordinator.data.get("fetched_at")
                else None
            ),
        }
