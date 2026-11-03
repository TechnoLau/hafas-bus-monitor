"""HAFAS Bus Monitor integration setup."""

from __future__ import annotations

import asyncio
import logging
from types import MappingProxyType

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import HafasClient
from .const import (
    CONF_CITY,
    CONF_LINE_TARGETS,
    CONF_LINES,
    CONF_STOP_CITY,
    CONF_STOP_ID,
    CONF_STOP_LID,
    CONF_STOP_NAME,
    CONF_STOPS,
    CONF_WALKING_MINUTES,
    DEFAULT_CITY,
    DOMAIN,
    SERVICE_REFRESH,
    SUBENTRY_TYPE_STOP,
)
from .coordinator import HafasDataUpdateCoordinator
from .util import merged_config, stops_from_subentries

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


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


def _config_for_entry(entry: ConfigEntry) -> dict:
    """Merge global settings and stops from config subentries."""
    config = merged_config(entry.data, entry.options)
    subentry_stops = stops_from_subentries(
        entry.subentries.values(),
        str(config.get(CONF_CITY) or ""),
    )
    if subentry_stops:
        config[CONF_STOPS] = subentry_stops
    elif entry.subentries:
        config[CONF_STOPS] = []
    return config


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one HAFAS Bus Monitor hub entry."""
    config = _config_for_entry(entry)

    client = HafasClient(async_get_clientsession(hass))
    coordinator = HafasDataUpdateCoordinator(hass, entry, client, config)

    # An entry without stops is valid: the user adds stops with the + button
    # on the integration page.  The coordinator returns an empty data set.
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
    """Migrate v1 stop lists to config subentries."""
    if entry.version >= 2:
        return True

    legacy_config = merged_config(entry.data, entry.options)
    legacy_stops = list(legacy_config.get(CONF_STOPS) or [])
    data = dict(entry.data)
    options = dict(entry.options)
    data.pop(CONF_STOPS, None)
    options.pop(CONF_STOPS, None)

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=2,
    )

    existing_ids = {
        subentry.unique_id
        for subentry in entry.subentries.values()
        if subentry.unique_id
    }
    for stop in legacy_stops:
        unique_id = f"nahsh:{stop[CONF_STOP_ID]}"
        if unique_id in existing_ids:
            continue
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data=MappingProxyType(
                    {
                        CONF_STOP_CITY: stop.get(CONF_STOP_CITY) or DEFAULT_CITY,
                        CONF_STOP_ID: stop[CONF_STOP_ID],
                        CONF_STOP_LID: stop[CONF_STOP_LID],
                        CONF_STOP_NAME: stop[CONF_STOP_NAME],
                        CONF_LINES: list(stop.get(CONF_LINES) or []),
                        CONF_LINE_TARGETS: dict(stop.get(CONF_LINE_TARGETS) or {}),
                        CONF_WALKING_MINUTES: int(stop.get(CONF_WALKING_MINUTES) or 0),
                    }
                ),
                subentry_type=SUBENTRY_TYPE_STOP,
                title=str(stop[CONF_STOP_NAME]),
                unique_id=unique_id,
            ),
        )
        existing_ids.add(unique_id)

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry after options or subentries changed."""
    await hass.config_entries.async_reload(entry.entry_id)
