"""Config, options and stop-subentry flows for HAFAS Bus Monitor."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HafasClient, HafasError, HafasStop
from .const import (
    CONF_CITY,
    CONF_HOLIDAY_ENTITY,
    CONF_LINE_TARGETS,
    CONF_LINES,
    CONF_ROUTING_ENABLED,
    CONF_SCAN_MINUTES,
    CONF_STOP_CITY,
    CONF_STOP_ID,
    CONF_STOP_INDEX,
    CONF_STOP_LID,
    CONF_STOP_NAME,
    CONF_STOP_QUERY,
    CONF_TARGETS,
    CONF_UPDATE_INTERVAL,
    CONF_WALKING_MINUTES,
    DEFAULT_CITY,
    DEFAULT_LINES,
    DEFAULT_ROUTING_ENABLED,
    DEFAULT_SCAN_MINUTES,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WALKING_MINUTES,
    DOMAIN,
    MAX_LOCATION_RESULTS,
    MAX_SCAN_MINUTES,
    MAX_UPDATE_INTERVAL,
    MAX_WALKING_MINUTES,
    MIN_SCAN_MINUTES,
    MIN_UPDATE_INTERVAL,
    MIN_WALKING_MINUTES,
    SUBENTRY_TYPE_STOP,
)
from .util import (
    lines_to_text,
    merged_config,
    normalize_lines,
    normalize_string_list,
)

_LOGGER = logging.getLogger(__name__)


def _text_selector() -> selector.TextSelector:
    """Return a normal single-line text selector."""
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    )


def _number_selector(minimum: int, maximum: int, unit: str) -> selector.NumberSelector:
    """Return a compact number selector."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def _optional_entity_selector(domains: list[str]) -> vol.Any:
    """Allow an empty value or an entity from the given domains."""
    return vol.Any(
        vol.In([None, ""]),
        selector.EntitySelector(selector.EntitySelectorConfig(domain=domains)),
    )


def _int_value(value: Any, default: int) -> int:
    """Convert an optional form value to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _stop_label(index: int, stop: HafasStop) -> dict[str, str]:
    """Return a readable SelectSelector option."""
    return {"value": str(index), "label": f"{stop.name} ({stop.stop_id})"}


def _global_schema(settings: dict[str, Any]) -> vol.Schema:
    """Return the global polling and holiday settings form."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SCAN_MINUTES,
                default=settings.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES),
            ): _number_selector(MIN_SCAN_MINUTES, MAX_SCAN_MINUTES, "min"),
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=settings.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): _number_selector(MIN_UPDATE_INTERVAL, MAX_UPDATE_INTERVAL, "s"),
            vol.Required(
                CONF_ROUTING_ENABLED,
                default=settings.get(CONF_ROUTING_ENABLED, DEFAULT_ROUTING_ENABLED),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_HOLIDAY_ENTITY,
                default=settings.get(CONF_HOLIDAY_ENTITY) or "",
            ): _optional_entity_selector(["binary_sensor", "input_boolean"]),
        }
    )


def _parse_global(
    user_input: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Parse global settings without resetting unrelated values."""
    return {
        CONF_SCAN_MINUTES: _int_value(
            user_input.get(CONF_SCAN_MINUTES),
            int(current.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)),
        ),
        CONF_UPDATE_INTERVAL: _int_value(
            user_input.get(CONF_UPDATE_INTERVAL),
            int(current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)),
        ),
        CONF_ROUTING_ENABLED: bool(
            user_input.get(
                CONF_ROUTING_ENABLED,
                current.get(CONF_ROUTING_ENABLED, DEFAULT_ROUTING_ENABLED),
            )
        ),
        CONF_HOLIDAY_ENTITY: (
            str(user_input.get(CONF_HOLIDAY_ENTITY) or "").strip() or None
        ),
    }


class HafasBusMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the hub entry; stops are added as subentries."""

    VERSION = 2

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {
            CONF_SCAN_MINUTES: DEFAULT_SCAN_MINUTES,
            CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_ROUTING_ENABLED: DEFAULT_ROUTING_ENABLED,
            CONF_HOLIDAY_ENTITY: None,
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the global options flow."""
        return HafasBusMonitorOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the stop subentry flow."""
        return {SUBENTRY_TYPE_STOP: HafasStopSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the main entry with global settings only."""
        if user_input is not None:
            settings = _parse_global(user_input, self._settings)
            return self.async_create_entry(
                title="HAFAS Bus Monitor",
                data=settings,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_global_schema(self._settings),
            description_placeholders={},
        )


class HafasBusMonitorOptionsFlow(OptionsFlow):
    """Edit the global polling and holiday settings."""

    def _entry(self) -> ConfigEntry:
        """Return the config entry on old and new Home Assistant versions."""
        entry = getattr(self, "config_entry", None)
        if entry is not None:
            return entry
        entry = self.hass.config_entries.async_get_entry(self.handler)
        if entry is None:
            raise RuntimeError("Config entry for options flow not found")
        return entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show global settings."""
        config = merged_config(self._entry().data, self._entry().options)
        if user_input is not None:
            return self.async_create_entry(
                title="HAFAS Bus Monitor",
                data=_parse_global(user_input, config),
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_global_schema(config),
        )


class HafasStopSubentryFlow(ConfigSubentryFlow):
    """Add one stop/tile as a config subentry."""

    def __init__(self) -> None:
        self._city = DEFAULT_CITY
        self._query = ""
        self._matches: list[HafasStop] = []
        self._candidate: HafasStop | None = None
        self._lines: list[str] = []
        self._line_targets: dict[str, list[str]] = {}
        self._destinations: dict[str, list[str]] = {}
        self._target_queue: list[str] = []
        self._target_index = 0
        self._reconfiguring = False
        self._existing_targets: dict[str, list[str]] = {}

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing stop subentry (lines, targets and walking time)."""
        subentry = self._get_reconfigure_subentry()
        data = dict(subentry.data)
        self._reconfiguring = True
        self._city = str(data.get(CONF_STOP_CITY) or DEFAULT_CITY)
        self._lines = list(data.get(CONF_LINES) or [])
        self._existing_targets = dict(data.get(CONF_LINE_TARGETS) or {})
        self._candidate = HafasStop(
            stop_id=str(data.get(CONF_STOP_ID) or ""),
            lid=str(data.get(CONF_STOP_LID) or ""),
            name=str(data.get(CONF_STOP_NAME) or ""),
        )
        return await self.async_step_lines()

    # ---------------------------------------------------------------- city
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1: choose/enter the city."""
        errors: dict[str, str] = {}
        if user_input is not None:
            city = str(user_input.get(CONF_CITY) or "").strip()
            if not city:
                errors["base"] = "city_required"
            else:
                self._city = city
                return await self.async_step_stop()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CITY, default=self._city): _text_selector(),
                }
            ),
            errors=errors,
        )

    # --------------------------------------------------------------- stop
    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2: search for the stop."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = str(user_input.get(CONF_STOP_QUERY) or "").strip()
            if not query:
                errors["base"] = "stop_required"
            else:
                self._query = query
                try:
                    matches = await self._search_matches()
                except HafasError as err:
                    _LOGGER.warning("HAFAS stop search failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if not matches:
                        errors["base"] = "no_stops"
                    elif len(matches) == 1:
                        self._candidate = matches[0]
                        return await self.async_step_lines()
                    else:
                        self._matches = matches
                        return await self.async_step_select_stop()

        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_QUERY, default=""): _text_selector(),
                }
            ),
            errors=errors,
            description_placeholders={"city": self._city},
        )

    async def async_step_select_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2b: select among multiple HAFAS matches."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                index = int(user_input[CONF_STOP_INDEX])
                self._candidate = self._matches[index]
            except (KeyError, IndexError, TypeError, ValueError):
                errors["base"] = "invalid_stop"
            else:
                return await self.async_step_lines()

        return self.async_show_form(
            step_id="select_stop",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_INDEX, default="0"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                _stop_label(index, stop)
                                for index, stop in enumerate(self._matches)
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "count": str(len(self._matches)),
                "query": self._query,
            },
        )

    # --------------------------------------------------------------- lines
    async def async_step_lines(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 3: choose the bus lines."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._lines = normalize_lines(user_input.get(CONF_LINES))
            await self._prepare_targets()
            if self._target_queue:
                return await self.async_step_targets()
            return await self.async_step_walking()

        return self.async_show_form(
            step_id="lines",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_LINES,
                        default=lines_to_text(self._lines) or DEFAULT_LINES,
                    ): _text_selector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "stop": self._candidate.name if self._candidate else self._query,
            },
        )

    async def _prepare_targets(self) -> None:
        """Discover destinations for the selected lines."""
        self._line_targets = {
            line: list(self._existing_targets.get(line, [])) for line in self._lines
        }
        self._destinations = {line: [] for line in self._lines}
        self._target_queue = []
        self._target_index = 0
        if not self._candidate or not self._lines:
            return

        client = HafasClient(async_get_clientsession(self.hass))
        try:
            destinations = await client.get_destinations(self._candidate, self._lines)
        except HafasError as err:
            _LOGGER.warning("HAFAS destination discovery failed: %s", err)
            return

        self._destinations = {line: destinations.get(line, []) for line in self._lines}
        self._target_queue = [line for line in self._lines if self._destinations[line]]

    # -------------------------------------------------------------- targets
    async def async_step_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 4: choose destinations per line."""
        if self._target_index >= len(self._target_queue):
            return await self.async_step_walking()

        line = self._target_queue[self._target_index]
        options = [
            {"value": destination, "label": destination}
            for destination in self._destinations.get(line, [])
        ]

        if user_input is not None:
            selected = normalize_string_list(user_input.get(CONF_TARGETS))
            allowed = {
                destination.casefold(): destination
                for destination in self._destinations.get(line, [])
            }
            self._line_targets[line] = [
                allowed[item.casefold()]
                for item in selected
                if item.casefold() in allowed
            ]
            self._target_index += 1
            return await self.async_step_targets()

        defaults = [
            target
            for target in self._line_targets.get(line, [])
            if target in {item["value"] for item in options}
        ]
        return self.async_show_form(
            step_id="targets",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TARGETS, default=defaults
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={
                "line": line,
                "stop": self._candidate.name if self._candidate else "",
            },
        )

    # -------------------------------------------------------------- walking
    async def async_step_walking(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 5: walking time and create the stop subentry."""
        if self._candidate is None:
            return self.async_abort(reason="invalid_flow")

        errors: dict[str, str] = {}
        if user_input is not None:
            current_subentry_id = (
                self._get_reconfigure_subentry().subentry_id
                if self._reconfiguring
                else None
            )
            for subentry in self._get_entry().subentries.values():
                if subentry.subentry_id == current_subentry_id:
                    continue
                if (
                    subentry.subentry_type == SUBENTRY_TYPE_STOP
                    and subentry.data.get(CONF_STOP_ID) == self._candidate.stop_id
                ):
                    errors["base"] = "already_configured"
                    break
            else:
                data = {
                    CONF_STOP_CITY: self._city,
                    CONF_STOP_ID: self._candidate.stop_id,
                    CONF_STOP_LID: self._candidate.lid,
                    CONF_STOP_NAME: self._candidate.name,
                    CONF_LINES: self._lines,
                    CONF_LINE_TARGETS: dict(self._line_targets),
                    CONF_WALKING_MINUTES: _int_value(
                        user_input.get(CONF_WALKING_MINUTES),
                        DEFAULT_WALKING_MINUTES,
                    ),
                }
                if self._reconfiguring:
                    return self.async_update_and_abort(
                        self._get_entry(),
                        self._get_reconfigure_subentry(),
                        title=self._candidate.name,
                        data=data,
                    )
                return self.async_create_entry(
                    title=self._candidate.name,
                    data=data,
                    unique_id=f"nahsh:{self._candidate.stop_id}",
                )

        return self.async_show_form(
            step_id="walking",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_WALKING_MINUTES,
                        default=int(
                            self._get_reconfigure_subentry().data.get(
                                CONF_WALKING_MINUTES, DEFAULT_WALKING_MINUTES
                            )
                            if self._reconfiguring
                            else DEFAULT_WALKING_MINUTES
                        ),
                    ): _number_selector(
                        MIN_WALKING_MINUTES, MAX_WALKING_MINUTES, "min"
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "stop": self._candidate.name,
                "lines": ", ".join(self._lines) or "alle Linien",
            },
        )

    # -------------------------------------------------------------- helpers
    async def _search_matches(self) -> list[HafasStop]:
        """Search HAFAS for the entered stop."""
        term = self._query
        if not term.casefold().startswith(self._city.casefold() + " "):
            term = f"{self._city} {term}"
        client = HafasClient(async_get_clientsession(self.hass))
        return await client.search_stops(
            term,
            city=self._city,
            limit=MAX_LOCATION_RESULTS,
        )
