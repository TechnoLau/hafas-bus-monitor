"""Stop selection for the next-departure sensor."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STOP_ID, CONF_STOP_NAME, DOMAIN
from .coordinator import HafasDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the stop selector."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: HafasDataUpdateCoordinator = runtime["coordinator"]
    if coordinator.stops:
        async_add_entities([HafasStopSelect(coordinator, entry)])


class HafasStopSelect(
    CoordinatorEntity[HafasDataUpdateCoordinator], SelectEntity, RestoreEntity
):
    """Select which configured stop the next-departure sensor shows."""

    _attr_has_entity_name = True
    _attr_name = "Haltestelle"
    _attr_icon = "mdi:bus-stop"

    def __init__(
        self,
        coordinator: HafasDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_stop_selector"

    @property
    def suggested_object_id(self) -> str:
        """Return the historical hafas_haltestelle entity id."""
        return "hafas_haltestelle"

    @property
    def device_info(self):
        """Do not attach a device."""
        return None

    @property
    def options(self) -> list[str]:
        """Return configured stop names."""
        return [str(stop.get(CONF_STOP_NAME) or "") for stop in self.coordinator.stops]

    @property
    def current_option(self) -> str | None:
        """Return the selected stop name."""
        stop = self.coordinator.selected_stop()
        return str(stop.get(CONF_STOP_NAME) or "") if stop else None

    @property
    def available(self) -> bool:
        """Return true while at least one stop is configured."""
        return bool(self.options)

    async def async_select_option(self, option: str) -> None:
        """Select a stop by its configured name."""
        for stop in self.coordinator.stops:
            if str(stop.get(CONF_STOP_NAME) or "") == option:
                self.coordinator.set_selected_stop(str(stop.get(CONF_STOP_ID)))
                self.async_write_ha_state()
                return

    async def async_added_to_hass(self) -> None:
        """Restore the last selected stop after a restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in self.options:
            for stop in self.coordinator.stops:
                if str(stop.get(CONF_STOP_NAME) or "") == last_state.state:
                    self.coordinator.set_selected_stop(str(stop.get(CONF_STOP_ID)))
                    break
