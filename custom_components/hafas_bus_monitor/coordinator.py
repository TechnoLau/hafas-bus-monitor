"""Data update coordinator for HAFAS Bus Monitor."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import HafasClient, HafasStop, StopDepartures
from .const import (
    ACTIVE_END_HOUR,
    ACTIVE_START_HOUR,
    CONF_HOLIDAY_ENTITY,
    CONF_LINE_TARGETS,
    CONF_SCAN_MINUTES,
    CONF_STOP_ID,
    CONF_STOP_LID,
    CONF_STOP_NAME,
    CONF_STOPS,
    CONF_UPDATE_INTERVAL,
    DOMAIN,
    HAFAS_TIMEZONE,
)
from .util import merged_config

_LOGGER = logging.getLogger(__name__)


class HafasDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the departure boards of all configured stops."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HafasClient,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.entry = entry
        self.client = client
        self.config = config or merged_config(entry.data, entry.options)

        update_seconds = int(self.config[CONF_UPDATE_INTERVAL])
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=update_seconds),
            always_update=True,
        )
        self._last_errors: dict[str, str] = {}

    @property
    def stops(self) -> list[dict[str, Any]]:
        """Return the normalized stop list."""
        return list(self.config.get(CONF_STOPS) or [])

    def stop_data(self, stop_id: str) -> StopDepartures | None:
        """Return the most recent board for a stop."""
        if not self.data:
            return None
        stops = self.data.get("stops") or {}
        if not isinstance(stops, dict):
            return None
        value = stops.get(stop_id)
        return value if isinstance(value, StopDepartures) else None

    def stop_error(self, stop_id: str) -> str | None:
        """Return the last error for a stop, if any."""
        if not self.data:
            return None
        errors = self.data.get("errors") or {}
        if not isinstance(errors, dict):
            return None
        return errors.get(stop_id)

    @property
    def pause_reason(self) -> str | None:
        """Return 'holiday' or 'outside_hours' while polling is paused."""
        if not self.data:
            return None
        reason = self.data.get("paused")
        return str(reason) if reason else None

    def _pause_reason(self, now: datetime) -> str | None:
        """Return why polling should be skipped, if applicable."""
        if now.hour < ACTIVE_START_HOUR or now.hour >= ACTIVE_END_HOUR:
            return "outside_hours"

        holiday_entity = self.config.get(CONF_HOLIDAY_ENTITY)
        if holiday_entity:
            state = self.hass.states.get(str(holiday_entity))
            if state is not None and state.state == "on":
                return "holiday"
        return None

    async def _fetch_stop(
        self,
        stop: dict[str, Any],
        now: datetime,
    ) -> StopDepartures:
        """Fetch one stop board."""
        hafas_stop = HafasStop(
            stop_id=str(stop[CONF_STOP_ID]),
            lid=str(stop[CONF_STOP_LID]),
            name=str(stop[CONF_STOP_NAME]),
        )
        return await self.client.fetch_departures(
            hafas_stop,
            now=now,
            scan_minutes=int(self.config[CONF_SCAN_MINUTES]),
            lines=stop.get("lines") or [],
            line_targets=stop.get(CONF_LINE_TARGETS) or {},
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all configured stops concurrently."""
        now = dt_util.now(ZoneInfo(HAFAS_TIMEZONE))
        stops = self.stops
        if not stops:
            raise UpdateFailed("No stops configured")

        pause_reason = self._pause_reason(now)
        if pause_reason:
            self._last_errors = {}
            return {
                "stops": {},
                "errors": {},
                "fetched_at": now,
                "paused": pause_reason,
            }

        outcomes = await asyncio.gather(
            *(self._fetch_stop(stop, now) for stop in stops),
            return_exceptions=True,
        )

        results: dict[str, StopDepartures] = {}
        errors: dict[str, str] = {}
        for stop, outcome in zip(stops, outcomes, strict=False):
            stop_id = str(stop[CONF_STOP_ID])
            if isinstance(outcome, Exception):
                message = f"{type(outcome).__name__}: {outcome}"
                errors[stop_id] = message[:500]
                _LOGGER.debug(
                    "Could not update stop %s (%s): %s",
                    stop.get(CONF_STOP_NAME),
                    stop_id,
                    outcome,
                )
            else:
                results[stop_id] = outcome

        if errors != self._last_errors:
            if errors:
                names = {
                    str(stop[CONF_STOP_ID]): str(
                        stop.get(CONF_STOP_NAME) or stop[CONF_STOP_ID]
                    )
                    for stop in stops
                }
                _LOGGER.warning(
                    "HAFAS update failed for %s of %s stop(s): %s",
                    len(errors),
                    len(stops),
                    "; ".join(
                        f"{names.get(stop_id, stop_id)}: {message}"
                        for stop_id, message in errors.items()
                    ),
                )
            elif self._last_errors:
                _LOGGER.info("HAFAS update recovered for all stops")
            self._last_errors = errors

        if not results:
            raise UpdateFailed("Could not fetch departures for any configured stop")

        return {
            "stops": results,
            "errors": errors,
            "fetched_at": now,
            "paused": None,
        }
