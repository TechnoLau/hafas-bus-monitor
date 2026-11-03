"""Config and options flow for HAFAS Bus Monitor."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HafasClient, HafasError, HafasStop
from .const import (
    CONF_ADD_ANOTHER,
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
    CONF_STOPS,
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
)
from .util import lines_to_text, merged_config, normalize_lines, normalize_string_list

_LOGGER = logging.getLogger(__name__)


def _text_selector() -> selector.TextSelector:
    """Return a normal single-line text selector."""
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    )


def _number_selector(
    minimum: int,
    maximum: int,
    unit: str,
) -> selector.NumberSelector:
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


def _stop_label(index: int, stop: HafasStop) -> dict[str, str]:
    """Return a readable SelectSelector option."""
    return {
        "value": str(index),
        "label": f"{stop.name} ({stop.stop_id})",
    }


def _configured_stop_label(index: int, stop: dict[str, Any]) -> dict[str, str]:
    """Return a readable SelectSelector option for a stored stop."""
    return {
        "value": str(index),
        "label": (
            f"{stop.get(CONF_STOP_NAME, '')} ({stop.get(CONF_STOP_ID, '')})"
        ).strip(),
    }


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


class _TargetSelectionMixin:
    """Shared per-line destination selection for config and options flows."""

    _pending: dict[str, Any] | None
    _pending_candidate: HafasStop | None
    _line_targets: dict[str, list[str]]
    _destinations: dict[str, list[str]]
    _target_queue: list[str]
    _target_index: int
    _target_edit_index: int | None

    async def _begin_targets(self) -> ConfigFlowResult:
        """Discover destinations and start the per-line target steps."""
        candidate = self._pending_candidate
        pending = self._pending
        if candidate is None or pending is None:
            return self.async_abort(reason="invalid_flow")

        lines = list(pending.get(CONF_LINES) or [])
        existing_targets: dict[str, list[str]] = {}
        if self._target_edit_index is not None and 0 <= self._target_edit_index < len(
            getattr(self, "_stops", [])
        ):
            existing_targets = dict(
                self._stops[self._target_edit_index].get(CONF_LINE_TARGETS) or {}
            )
        self._line_targets = {
            line: list(existing_targets.get(line, [])) for line in lines
        }
        self._destinations = {line: [] for line in lines}
        self._target_queue = []
        self._target_index = 0

        if lines:
            client = HafasClient(async_get_clientsession(self.hass))
            try:
                destinations = await client.get_destinations(candidate, lines)
            except HafasError as err:
                _LOGGER.warning("HAFAS destination discovery failed: %s", err)
            else:
                self._destinations = {
                    line: destinations.get(line, []) for line in lines
                }
                self._target_queue = [
                    line for line in lines if self._destinations[line]
                ]

        if not self._target_queue:
            return await self._finish_targets()
        return await self.async_step_targets()

    async def async_step_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for destination filters one selected line at a time."""
        if self._target_index >= len(self._target_queue):
            return await self._finish_targets()

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
                        CONF_TARGETS,
                        default=defaults,
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
                "stop": (
                    self._pending_candidate.name
                    if self._pending_candidate is not None
                    else str((self._pending or {}).get(CONF_STOP_QUERY, ""))
                ),
            },
        )

    async def _finish_targets(self) -> ConfigFlowResult:
        """Store the stop with its per-line targets and continue."""
        candidate = self._pending_candidate
        pending = self._pending
        targets = {line: list(values) for line, values in self._line_targets.items()}
        edit_index = self._target_edit_index
        self._pending_candidate = None
        self._pending = None
        self._line_targets = {}
        self._destinations = {}
        self._target_queue = []
        self._target_index = 0
        self._target_edit_index = None
        if candidate is None or pending is None:
            return self.async_abort(reason="invalid_flow")
        if edit_index is not None:
            if 0 <= edit_index < len(getattr(self, "_stops", [])):
                self._stops[edit_index][CONF_LINE_TARGETS] = targets
            return await self._target_complete()
        if not self._add_stop(candidate, pending, targets):
            return self.async_abort(reason="already_configured")
        return await self._target_complete()

    async def _target_complete(self) -> ConfigFlowResult:
        """Continue after target selection; implemented by the concrete flow."""
        raise NotImplementedError


class HafasBusMonitorConfigFlow(_TargetSelectionMixin, ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._settings: dict[str, Any] = {
            CONF_CITY: DEFAULT_CITY,
            CONF_LINES: DEFAULT_LINES,
            CONF_SCAN_MINUTES: DEFAULT_SCAN_MINUTES,
            CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_ROUTING_ENABLED: DEFAULT_ROUTING_ENABLED,
            CONF_HOLIDAY_ENTITY: None,
        }
        self._stops: list[dict[str, Any]] = []
        self._pending: dict[str, Any] | None = None
        self._pending_candidate: HafasStop | None = None
        self._matches: list[HafasStop] = []
        self._line_targets: dict[str, list[str]] = {}
        self._destinations: dict[str, list[str]] = {}
        self._target_queue: list[str] = []
        self._target_index = 0
        self._target_edit_index: int | None = None

    async def _target_complete(self) -> ConfigFlowResult:
        """Continue with the next stop prompt after targets are selected."""
        return await self.async_step_add_stop()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return HafasBusMonitorOptionsFlow()

    # ------------------------------------------------------------------ user
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the city, stop and global polling settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._settings, pending = self._parse_settings(user_input)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self._pending = pending
                try:
                    matches = await self._search_matches(pending)
                except HafasError as err:
                    _LOGGER.warning("HAFAS stop search failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if not matches:
                        errors["base"] = "no_stops"
                    elif len(matches) == 1:
                        if any(
                            stop[CONF_STOP_ID] == matches[0].stop_id
                            for stop in self._stops
                        ):
                            errors["base"] = "duplicate_stop"
                        else:
                            self._pending_candidate = matches[0]
                            return await self._begin_targets()
                    else:
                        self._matches = matches
                        return await self.async_step_select_stop()

        return self.async_show_form(
            step_id="user",
            data_schema=self._user_schema(),
            errors=errors,
        )

    # ------------------------------------------------------------ select stop
    async def async_step_select_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose between multiple HAFAS matches."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not self._matches or self._pending is None:
                return self.async_abort(reason="invalid_flow")
            try:
                index = int(user_input[CONF_STOP_INDEX])
                stop = self._matches[index]
            except (KeyError, IndexError, TypeError, ValueError):
                errors["base"] = "invalid_stop"
            else:
                if any(item[CONF_STOP_ID] == stop.stop_id for item in self._stops):
                    errors["base"] = "duplicate_stop"
                else:
                    self._pending_candidate = stop
                    self._matches = []
                    return await self._begin_targets()

        return self.async_show_form(
            step_id="select_stop",
            data_schema=self._select_stop_schema(),
            errors=errors,
            description_placeholders={
                "count": str(len(self._matches)),
                "query": str((self._pending or {}).get(CONF_STOP_QUERY, "")),
            },
        )

    # --------------------------------------------------------------- add more
    async def async_step_add_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask whether another stop should be added."""
        if user_input is not None:
            if user_input.get(CONF_ADD_ANOTHER):
                return await self.async_step_stop()
            return await self._async_finish()

        return self.async_show_form(
            step_id="add_stop",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ADD_ANOTHER,
                        default=len(self._stops) == 1,
                    ): selector.BooleanSelector()
                }
            ),
            description_placeholders={
                "count": str(len(self._stops)),
                "stops": ", ".join(
                    str(stop.get(CONF_STOP_NAME)) for stop in self._stops
                ),
            },
        )

    # ------------------------------------------------------------ extra stop
    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for an additional stop."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                pending = self._parse_stop_input(user_input)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self._pending = pending
                try:
                    matches = await self._search_matches(pending)
                except HafasError as err:
                    _LOGGER.warning("HAFAS stop search failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if not matches:
                        errors["base"] = "no_stops"
                    elif len(matches) == 1:
                        if any(
                            stop[CONF_STOP_ID] == matches[0].stop_id
                            for stop in self._stops
                        ):
                            errors["base"] = "duplicate_stop"
                        else:
                            self._pending_candidate = matches[0]
                            return await self._begin_targets()
                    else:
                        self._matches = matches
                        return await self.async_step_select_stop()

        return self.async_show_form(
            step_id="stop",
            data_schema=self._stop_schema(),
            errors=errors,
        )

    # ---------------------------------------------------------------- helpers
    def _parse_settings(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        city = str(user_input.get(CONF_CITY) or "").strip()
        if not city:
            raise ValueError("city_required")
        pending = self._parse_stop_input(user_input)
        settings = {
            CONF_CITY: city,
            CONF_LINES: lines_to_text(pending[CONF_LINES]),
            CONF_SCAN_MINUTES: _int_value(
                user_input.get(CONF_SCAN_MINUTES), DEFAULT_SCAN_MINUTES
            ),
            CONF_UPDATE_INTERVAL: _int_value(
                user_input.get(CONF_UPDATE_INTERVAL), DEFAULT_UPDATE_INTERVAL
            ),
            CONF_ROUTING_ENABLED: bool(
                user_input.get(CONF_ROUTING_ENABLED, DEFAULT_ROUTING_ENABLED)
            ),
            CONF_HOLIDAY_ENTITY: (
                str(user_input.get(CONF_HOLIDAY_ENTITY) or "").strip() or None
            ),
        }
        return settings, pending

    def _parse_stop_input(self, user_input: dict[str, Any]) -> dict[str, Any]:
        city = str(user_input.get(CONF_CITY) or "").strip()
        if not city:
            raise ValueError("city_required")
        query = str(user_input.get(CONF_STOP_QUERY) or "").strip()
        if not query:
            raise ValueError("stop_required")
        return {
            CONF_CITY: city,
            CONF_STOP_QUERY: query,
            CONF_LINES: normalize_lines(user_input.get(CONF_LINES)),
            CONF_WALKING_MINUTES: _int_value(
                user_input.get(CONF_WALKING_MINUTES), DEFAULT_WALKING_MINUTES
            ),
        }

    async def _search_matches(self, pending: dict[str, Any]) -> list[HafasStop]:
        city = str(pending[CONF_CITY])
        query = str(pending[CONF_STOP_QUERY])
        term = query
        if not query.casefold().startswith(city.casefold() + " "):
            term = f"{city} {query}"
        client = HafasClient(async_get_clientsession(self.hass))
        return await client.search_stops(
            term,
            city=city,
            limit=MAX_LOCATION_RESULTS,
        )

    def _add_stop(
        self,
        candidate: HafasStop,
        pending: dict[str, Any],
        line_targets: dict[str, list[str]],
    ) -> bool:
        if any(stop[CONF_STOP_ID] == candidate.stop_id for stop in self._stops):
            return False
        self._stops.append(
            {
                CONF_STOP_ID: candidate.stop_id,
                CONF_STOP_LID: candidate.lid,
                CONF_STOP_NAME: candidate.name,
                CONF_STOP_CITY: pending[CONF_CITY],
                CONF_LINES: list(pending[CONF_LINES]),
                CONF_LINE_TARGETS: dict(line_targets),
                CONF_WALKING_MINUTES: pending[CONF_WALKING_MINUTES],
            }
        )
        self._settings[CONF_CITY] = pending[CONF_CITY]
        self._settings[CONF_LINES] = lines_to_text(pending[CONF_LINES])
        return True

    async def _async_finish(self) -> ConfigFlowResult:
        primary = self._stops[0]
        await self.async_set_unique_id(f"nahsh:{primary[CONF_STOP_ID]}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=str(primary[CONF_STOP_NAME]),
            data={
                CONF_CITY: self._settings[CONF_CITY],
                CONF_STOPS: self._stops,
                CONF_SCAN_MINUTES: self._settings[CONF_SCAN_MINUTES],
                CONF_UPDATE_INTERVAL: self._settings[CONF_UPDATE_INTERVAL],
                CONF_ROUTING_ENABLED: self._settings[CONF_ROUTING_ENABLED],
                CONF_HOLIDAY_ENTITY: self._settings[CONF_HOLIDAY_ENTITY],
            },
        )

    def _user_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_CITY, default=self._settings.get(CONF_CITY, DEFAULT_CITY)
                ): _text_selector(),
                vol.Required(CONF_STOP_QUERY, default=""): _text_selector(),
                vol.Optional(
                    CONF_LINES, default=self._settings.get(CONF_LINES, DEFAULT_LINES)
                ): _text_selector(),
                vol.Required(
                    CONF_WALKING_MINUTES, default=DEFAULT_WALKING_MINUTES
                ): _number_selector(MIN_WALKING_MINUTES, MAX_WALKING_MINUTES, "min"),
                vol.Required(
                    CONF_SCAN_MINUTES,
                    default=self._settings.get(CONF_SCAN_MINUTES, DEFAULT_SCAN_MINUTES),
                ): _number_selector(MIN_SCAN_MINUTES, MAX_SCAN_MINUTES, "min"),
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=self._settings.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ): _number_selector(MIN_UPDATE_INTERVAL, MAX_UPDATE_INTERVAL, "s"),
                vol.Required(
                    CONF_ROUTING_ENABLED,
                    default=self._settings.get(
                        CONF_ROUTING_ENABLED, DEFAULT_ROUTING_ENABLED
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_HOLIDAY_ENTITY,
                    default=self._settings.get(CONF_HOLIDAY_ENTITY) or "",
                ): _optional_entity_selector(["binary_sensor", "input_boolean"]),
            }
        )

    def _stop_schema(self) -> vol.Schema:
        previous = self._stops[-1] if self._stops else None
        default_city = (
            str(previous.get(CONF_STOP_CITY))
            if previous
            else str(self._settings.get(CONF_CITY, DEFAULT_CITY))
        )
        default_lines = (
            lines_to_text(previous.get(CONF_LINES))
            if previous
            else str(self._settings.get(CONF_LINES, DEFAULT_LINES))
        )
        return vol.Schema(
            {
                vol.Required(CONF_CITY, default=default_city): _text_selector(),
                vol.Required(CONF_STOP_QUERY, default=""): _text_selector(),
                vol.Optional(CONF_LINES, default=default_lines): _text_selector(),
                vol.Required(
                    CONF_WALKING_MINUTES, default=DEFAULT_WALKING_MINUTES
                ): _number_selector(MIN_WALKING_MINUTES, MAX_WALKING_MINUTES, "min"),
            }
        )

    def _select_stop_schema(self) -> vol.Schema:
        options = [_stop_label(index, stop) for index, stop in enumerate(self._matches)]
        return vol.Schema(
            {
                vol.Required(CONF_STOP_INDEX, default="0"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )


class HafasBusMonitorOptionsFlow(_TargetSelectionMixin, OptionsFlow):
    """Manage stops and polling settings of an existing entry."""

    def __init__(self) -> None:
        self._loaded = False
        self._settings: dict[str, Any] = {}
        self._stops: list[dict[str, Any]] = []
        self._pending: dict[str, Any] | None = None
        self._pending_candidate: HafasStop | None = None
        self._matches: list[HafasStop] = []
        self._line_targets: dict[str, list[str]] = {}
        self._destinations: dict[str, list[str]] = {}
        self._target_queue: list[str] = []
        self._target_index = 0
        self._target_edit_index: int | None = None
        self._edit_index: int | None = None

    async def _target_complete(self) -> ConfigFlowResult:
        """Return to the options menu after targets are selected."""
        return await self.async_step_init()

    def _entry(self) -> ConfigEntry:
        """Return the config entry in a way that works on old and new HA."""
        entry = getattr(self, "config_entry", None)
        if entry is not None:
            return entry
        entry = self.hass.config_entries.async_get_entry(self.handler)
        if entry is None:
            raise RuntimeError("Config entry for options flow not found")
        return entry

    def _load(self) -> None:
        if self._loaded:
            return
        entry = self._entry()
        config = merged_config(entry.data, entry.options)
        self._settings = {
            CONF_CITY: config[CONF_CITY],
            CONF_SCAN_MINUTES: config[CONF_SCAN_MINUTES],
            CONF_UPDATE_INTERVAL: config[CONF_UPDATE_INTERVAL],
            CONF_ROUTING_ENABLED: config[CONF_ROUTING_ENABLED],
            CONF_HOLIDAY_ENTITY: config[CONF_HOLIDAY_ENTITY],
        }
        self._stops = [dict(stop) for stop in config[CONF_STOPS]]
        self._loaded = True

    # ------------------------------------------------------------------ menu
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        self._load()
        if not self._stops:
            return await self.async_step_add_stop()

        menu = ["settings", "add_stop", "edit_stop", "edit_targets"]
        if len(self._stops) > 1:
            menu.append("remove_stop")
        menu.append("save")
        return self.async_show_menu(step_id="init", menu_options=menu)

    # -------------------------------------------------------------- settings
    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit polling and routing settings."""
        self._load()
        if user_input is not None:
            self._settings[CONF_SCAN_MINUTES] = _int_value(
                user_input.get(CONF_SCAN_MINUTES),
                int(self._settings[CONF_SCAN_MINUTES]),
            )
            self._settings[CONF_UPDATE_INTERVAL] = _int_value(
                user_input.get(CONF_UPDATE_INTERVAL),
                int(self._settings[CONF_UPDATE_INTERVAL]),
            )
            self._settings[CONF_ROUTING_ENABLED] = bool(
                user_input.get(
                    CONF_ROUTING_ENABLED,
                    self._settings[CONF_ROUTING_ENABLED],
                )
            )
            self._settings[CONF_HOLIDAY_ENTITY] = (
                str(user_input.get(CONF_HOLIDAY_ENTITY) or "").strip() or None
            )
            return await self.async_step_init()

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_MINUTES,
                        default=self._settings[CONF_SCAN_MINUTES],
                    ): _number_selector(MIN_SCAN_MINUTES, MAX_SCAN_MINUTES, "min"),
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self._settings[CONF_UPDATE_INTERVAL],
                    ): _number_selector(MIN_UPDATE_INTERVAL, MAX_UPDATE_INTERVAL, "s"),
                    vol.Required(
                        CONF_ROUTING_ENABLED,
                        default=self._settings[CONF_ROUTING_ENABLED],
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_HOLIDAY_ENTITY,
                        default=self._settings.get(CONF_HOLIDAY_ENTITY) or "",
                    ): _optional_entity_selector(["binary_sensor", "input_boolean"]),
                }
            ),
        )

    # -------------------------------------------------------------- add stop
    async def async_step_add_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add another stop."""
        self._load()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                pending = self._parse_stop_input(user_input)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self._pending = pending
                try:
                    matches = await self._search_matches(pending)
                except HafasError as err:
                    _LOGGER.warning("HAFAS stop search failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    if not matches:
                        errors["base"] = "no_stops"
                    elif len(matches) == 1:
                        if any(
                            stop[CONF_STOP_ID] == matches[0].stop_id
                            for stop in self._stops
                        ):
                            errors["base"] = "duplicate_stop"
                        else:
                            self._pending_candidate = matches[0]
                            return await self._begin_targets()
                    else:
                        self._matches = matches
                        return await self.async_step_select_stop()

        return self.async_show_form(
            step_id="add_stop",
            data_schema=self._stop_schema(),
            errors=errors,
        )

    async def async_step_select_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose one of multiple HAFAS matches."""
        self._load()
        errors: dict[str, str] = {}
        if user_input is not None:
            if not self._matches or self._pending is None:
                return self.async_abort(reason="invalid_flow")
            try:
                index = int(user_input[CONF_STOP_INDEX])
                stop = self._matches[index]
            except (KeyError, IndexError, TypeError, ValueError):
                errors["base"] = "invalid_stop"
            else:
                if any(item[CONF_STOP_ID] == stop.stop_id for item in self._stops):
                    errors["base"] = "duplicate_stop"
                else:
                    self._pending_candidate = stop
                    self._matches = []
                    return await self._begin_targets()

        options = [_stop_label(index, stop) for index, stop in enumerate(self._matches)]
        return self.async_show_form(
            step_id="select_stop",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_INDEX, default="0"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "count": str(len(self._matches)),
                "query": str((self._pending or {}).get(CONF_STOP_QUERY, "")),
            },
        )

    # ---------------------------------------------------------- edit targets
    async def async_step_edit_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a stop whose per-line destinations should be edited."""
        self._load()
        if not self._stops:
            return await self.async_step_init()

        if user_input is not None:
            try:
                index = int(user_input[CONF_STOP_INDEX])
                stop = self._stops[index]
            except (IndexError, KeyError, TypeError, ValueError):
                pass
            else:
                self._target_edit_index = index
                self._pending = {
                    CONF_CITY: str(stop.get(CONF_STOP_CITY) or ""),
                    CONF_STOP_QUERY: "",
                    CONF_LINES: list(stop.get(CONF_LINES) or []),
                    CONF_WALKING_MINUTES: int(stop.get(CONF_WALKING_MINUTES) or 0),
                }
                self._pending_candidate = HafasStop(
                    stop_id=str(stop.get(CONF_STOP_ID) or ""),
                    lid=str(stop.get(CONF_STOP_LID) or ""),
                    name=str(stop.get(CONF_STOP_NAME) or ""),
                )
                return await self._begin_targets()

        return self.async_show_form(
            step_id="edit_targets",
            data_schema=self._edit_stop_select_schema(),
        )

    # ------------------------------------------------------------- edit stop
    async def async_step_edit_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the stop to edit."""
        self._load()
        if user_input is not None:
            try:
                self._edit_index = int(user_input[CONF_STOP_INDEX])
                self._stops[self._edit_index]
            except (IndexError, KeyError, TypeError, ValueError):
                self._edit_index = None
            else:
                return await self.async_step_edit_stop_form()

        return self.async_show_form(
            step_id="edit_stop",
            data_schema=self._edit_stop_select_schema(),
        )

    async def async_step_edit_stop_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit lines and walking time of one stop."""
        self._load()
        if self._edit_index is None or not (0 <= self._edit_index < len(self._stops)):
            return await self.async_step_init()

        stop = self._stops[self._edit_index]
        if user_input is not None:
            new_lines = normalize_lines(user_input.get(CONF_LINES))
            old_targets = dict(stop.get(CONF_LINE_TARGETS) or {})
            stop[CONF_LINES] = new_lines
            stop[CONF_LINE_TARGETS] = {
                line: list(old_targets.get(line, [])) for line in new_lines
            }
            stop[CONF_WALKING_MINUTES] = _int_value(
                user_input.get(CONF_WALKING_MINUTES),
                int(stop.get(CONF_WALKING_MINUTES) or 0),
            )
            self._edit_index = None
            return await self.async_step_init()

        return self.async_show_form(
            step_id="edit_stop_form",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_LINES,
                        default=lines_to_text(stop.get(CONF_LINES)),
                    ): _text_selector(),
                    vol.Required(
                        CONF_WALKING_MINUTES,
                        default=int(stop.get(CONF_WALKING_MINUTES) or 0),
                    ): _number_selector(
                        MIN_WALKING_MINUTES, MAX_WALKING_MINUTES, "min"
                    ),
                }
            ),
            description_placeholders={
                "stop": str(stop.get(CONF_STOP_NAME, "")),
            },
        )

    # ----------------------------------------------------------- remove stop
    async def async_step_remove_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove a stop."""
        self._load()
        if len(self._stops) <= 1:
            return await self.async_step_init()
        if user_input is not None:
            try:
                index = int(user_input[CONF_STOP_INDEX])
                self._stops.pop(index)
            except (IndexError, KeyError, TypeError, ValueError):
                pass
            else:
                return await self.async_step_init()

        return self.async_show_form(
            step_id="remove_stop",
            data_schema=self._remove_stop_schema(),
        )

    # ------------------------------------------------------------------ save
    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Persist options and let the update listener reload the entry."""
        self._load()
        if not self._stops:
            return await self.async_step_add_stop()

        return self.async_create_entry(
            title="HAFAS Bus Monitor",
            data={
                CONF_CITY: str(self._stops[0].get(CONF_STOP_CITY) or DEFAULT_CITY),
                CONF_STOPS: self._stops,
                CONF_SCAN_MINUTES: self._settings[CONF_SCAN_MINUTES],
                CONF_UPDATE_INTERVAL: self._settings[CONF_UPDATE_INTERVAL],
                CONF_ROUTING_ENABLED: self._settings[CONF_ROUTING_ENABLED],
                CONF_HOLIDAY_ENTITY: self._settings[CONF_HOLIDAY_ENTITY],
            },
        )

    # ---------------------------------------------------------------- helpers
    def _parse_stop_input(self, user_input: dict[str, Any]) -> dict[str, Any]:
        city = str(user_input.get(CONF_CITY) or "").strip()
        if not city:
            raise ValueError("city_required")
        query = str(user_input.get(CONF_STOP_QUERY) or "").strip()
        if not query:
            raise ValueError("stop_required")
        return {
            CONF_CITY: city,
            CONF_STOP_QUERY: query,
            CONF_LINES: normalize_lines(user_input.get(CONF_LINES)),
            CONF_WALKING_MINUTES: _int_value(
                user_input.get(CONF_WALKING_MINUTES), DEFAULT_WALKING_MINUTES
            ),
        }

    async def _search_matches(self, pending: dict[str, Any]) -> list[HafasStop]:
        city = str(pending[CONF_CITY])
        query = str(pending[CONF_STOP_QUERY])
        term = query
        if not query.casefold().startswith(city.casefold() + " "):
            term = f"{city} {query}"
        client = HafasClient(async_get_clientsession(self.hass))
        return await client.search_stops(
            term,
            city=city,
            limit=MAX_LOCATION_RESULTS,
        )

    def _add_stop(
        self,
        candidate: HafasStop,
        pending: dict[str, Any],
        line_targets: dict[str, list[str]],
    ) -> bool:
        if any(stop[CONF_STOP_ID] == candidate.stop_id for stop in self._stops):
            return False
        self._stops.append(
            {
                CONF_STOP_ID: candidate.stop_id,
                CONF_STOP_LID: candidate.lid,
                CONF_STOP_NAME: candidate.name,
                CONF_STOP_CITY: pending[CONF_CITY],
                CONF_LINES: list(pending[CONF_LINES]),
                CONF_LINE_TARGETS: dict(line_targets),
                CONF_WALKING_MINUTES: pending[CONF_WALKING_MINUTES],
            }
        )
        self._settings[CONF_CITY] = pending[CONF_CITY]
        return True

    def _stop_schema(self) -> vol.Schema:
        previous = self._stops[-1] if self._stops else None
        default_city = (
            str(previous.get(CONF_STOP_CITY))
            if previous
            else str(self._settings.get(CONF_CITY, DEFAULT_CITY))
        )
        default_lines = lines_to_text(previous.get(CONF_LINES)) if previous else ""
        return vol.Schema(
            {
                vol.Required(CONF_CITY, default=default_city): _text_selector(),
                vol.Required(CONF_STOP_QUERY, default=""): _text_selector(),
                vol.Optional(CONF_LINES, default=default_lines): _text_selector(),
                vol.Required(
                    CONF_WALKING_MINUTES, default=DEFAULT_WALKING_MINUTES
                ): _number_selector(MIN_WALKING_MINUTES, MAX_WALKING_MINUTES, "min"),
            }
        )

    def _edit_stop_select_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_STOP_INDEX, default="0"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            _configured_stop_label(index, stop)
                            for index, stop in enumerate(self._stops)
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )

    def _remove_stop_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_STOP_INDEX, default="0"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            _configured_stop_label(index, stop)
                            for index, stop in enumerate(self._stops)
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
