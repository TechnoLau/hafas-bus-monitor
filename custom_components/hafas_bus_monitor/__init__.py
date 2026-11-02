"""HAFAS Bus Monitor integration setup."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import HafasClient
from .const import CONF_STOPS, DOMAIN, SERVICE_REFRESH
from .coordinator import HafasDataUpdateCoordinator
from .util import merged_config

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration-level refresh service."""
    hass.data.setdefault(DOMAIN, {})

    async def _async_refresh(_call: ServiceCall) -> None:
        runtimes = [
            runtime
            for runtime in hass.data.get(DOMAIN, {}).values()
            if isinstance(runtime, dict) and runtime.get("coordinator") is not None
        ]
        if not runtimes:
            return
        await asyncio.gather(
            *(runtime["coordinator"].async_request_refresh() for runtime in runtimes),
            return_exceptions=True,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH,
            _async_refresh,
            schema=vol.Schema({}),
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one HAFAS Bus Monitor config entry."""
    config = merged_config(entry.data, entry.options)
    if not config[CONF_STOPS]:
        raise ConfigEntryNotReady("No valid stops are configured")

    client = HafasClient(async_get_clientsession(hass))
    coordinator = HafasDataUpdateCoordinator(hass, entry, client, config)

    # This raises ConfigEntryNotReady automatically if the first update fails.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "config": config,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries.

    Version 1 is the first public version, so there is nothing to migrate yet.
    The hook is present to make future option/data migrations easier.
    """
    _LOGGER.debug("Migrating HAFAS Bus Monitor entry from version %s", entry.version)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry after options changed."""
    await hass.config_entries.async_reload(entry.entry_id)
