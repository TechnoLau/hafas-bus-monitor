"""Holiday-mode switch for HAFAS Bus Monitor."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HafasDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the holiday-mode switch."""
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator: HafasDataUpdateCoordinator = runtime["coordinator"]
    config: dict[str, Any] = runtime["config"]
    async_add_entities([HafasHolidaySwitch(coordinator, entry, config)])


class HafasHolidaySwitch(
    CoordinatorEntity[HafasDataUpdateCoordinator], SwitchEntity, RestoreEntity
):
    """Manual holiday mode; on pauses all HAFAS polling."""

    _attr_has_entity_name = True
    _attr_name = "Ferienmodus"
    _attr_icon = "mdi:school"

    def __init__(
        self,
        coordinator: HafasDataUpdateCoordinator,
        entry: ConfigEntry,
        config: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._config = config
        self._attr_unique_id = f"{entry.entry_id}_holiday_mode"

    @property
    def device_info(self):
        """Do not attach a device; the friendly name stays 'Ferienmodus'."""
        return None

    @property
    def suggested_object_id(self) -> str:
        """Return the historical hafas_ferienmodus entity id."""
        return "hafas_ferienmodus"

    @property
    def is_on(self) -> bool:
        """Return true while holiday mode is active."""
        return self.coordinator.holiday_override

    async def async_added_to_hass(self) -> None:
        """Restore the last holiday-mode state."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            self.coordinator.set_holiday_override(True)
            await self.coordinator.async_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Pause polling."""
        self.coordinator.set_holiday_override(True)
        self.async_write_ha_state()
        await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Resume polling."""
        self.coordinator.set_holiday_override(False)
        self.async_write_ha_state()
        await self.coordinator.async_refresh()
