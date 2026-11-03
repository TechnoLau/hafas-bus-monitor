"""Constants for the HAFAS Bus Monitor integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "hafas_bus_monitor"
NAME: Final = "HAFAS Bus Monitor"
VERSION: Final = "3.3.2"

# Configuration keys ---------------------------------------------------------
CONF_CITY: Final = "city"
CONF_STOP_QUERY: Final = "stop_query"
CONF_STOPS: Final = "stops"
CONF_LINES: Final = "lines"
CONF_WALKING_MINUTES: Final = "walking_minutes"
CONF_DESTINATION_FILTER: Final = "destination_filter"
CONF_LINE_TARGETS: Final = "line_targets"
CONF_TARGETS: Final = "targets"
CONF_HOLIDAY_ENTITY: Final = "holiday_entity"
CONF_DEVICE_TRACKER: Final = "device_tracker"
CONF_SCAN_MINUTES: Final = "scan_minutes"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_ROUTING_ENABLED: Final = "routing_enabled"
CONF_ADD_ANOTHER: Final = "add_another"
CONF_STOP_INDEX: Final = "stop"

# Keys used inside a stop dictionary ----------------------------------------
CONF_STOP_ID: Final = "id"
CONF_STOP_LID: Final = "lid"
CONF_STOP_NAME: Final = "name"
CONF_STOP_CITY: Final = "city"
CONF_STOP_LAT: Final = "latitude"
CONF_STOP_LON: Final = "longitude"
CONF_SUBENTRY_ID: Final = "subentry_id"

SUBENTRY_TYPE_STOP: Final = "stop"

# Defaults -------------------------------------------------------------------
DEFAULT_CITY: Final = "Kiel"
DEFAULT_LINES: Final = "61, 62"
DEFAULT_WALKING_MINUTES: Final = 5
DEFAULT_SCAN_MINUTES: Final = 60
DEFAULT_UPDATE_INTERVAL: Final = 30
DEFAULT_ROUTING_ENABLED: Final = True

MIN_WALKING_MINUTES: Final = 0
MAX_WALKING_MINUTES: Final = 60
MIN_SCAN_MINUTES: Final = 10
MAX_SCAN_MINUTES: Final = 180
MIN_UPDATE_INTERVAL: Final = 30
MAX_UPDATE_INTERVAL: Final = 300

MAX_DEPARTURES: Final = 12
MAX_ALL_DEPARTURES: Final = 8
MAX_UNREACHABLE_DEPARTURES: Final = 4
MAX_FETCH_DEPARTURES: Final = 100
DISPLAY_MINUTES_THRESHOLD: Final = 20
DESTINATION_DISCOVERY_MINUTES: Final = 720
DESTINATION_DISCOVERY_MAX_TRIPS: Final = 300
MAX_LOCATION_RESULTS: Final = 10

# HAFAS / NAH.SH -------------------------------------------------------------
# NAH.SH is the Schleswig-Holstein (Germany) HAFAS deployment.  It covers
# Kiel, Lübeck, Flensburg, ... and is used by the KVG Kiel buses.
HAFAS_ENDPOINT: Final = "https://nahsh.hafas.cloud/gate"
HAFAS_FALLBACK_ENDPOINT: Final = "https://nah.sh.hafas.de/bin/mgate.exe"
HAFAS_LANGUAGE: Final = "de"
HAFAS_VERSION: Final = "1.30"
HAFAS_TIMEZONE: Final = "Europe/Berlin"
HAFAS_CLIENT: Final = {
    "type": "IPH",
    "id": "NAHSH",
    "v": "3000700",
    "name": "NAHSHPROD",
}
HAFAS_AUTH: Final = {
    "type": "AID",
    "aid": "r0Ot9FLFNAFxijLW",
}
# Bit 32 = bus, bit 512 = on-call bus.  The line filtering itself is done
# locally, because HAFAS line IDs differ between deployments.
HAFAS_BUS_PRODUCT_MASK: Final = 544
HAFAS_USER_AGENT: Final = (
    "hafas-bus-monitor-homeassistant/3.3.2 "
    "(+https://github.com/TechnoLau/hafas-bus-monitor)"
)

# Active polling window (local HAFAS timezone) --------------------------------
ACTIVE_START_HOUR: Final = 6
ACTIVE_END_HOUR: Final = 22
ACTIVE_HOURS_TEXT: Final = "06:00–22:00"

# Services -------------------------------------------------------------------
SERVICE_REFRESH: Final = "refresh"

# Attribute names ------------------------------------------------------------
ATTR_DEPARTURES: Final = "departures"
ATTR_ALL_DEPARTURES: Final = "all_departures"
ATTR_NEXT_DEPARTURE: Final = "next_departure"
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_STOP: Final = "stop"
ATTR_STOP_ID: Final = "stop_id"
ATTR_CITY: Final = "city"
ATTR_LINES: Final = "lines"
ATTR_WALKING_MINUTES: Final = "walking_minutes"
ATTR_SCAN_MINUTES: Final = "scan_minutes"
ATTR_ERROR: Final = "error"
ATTR_BEST: Final = "best"
ATTR_OPTIONS: Final = "options"
ATTR_SELECTION_METHOD: Final = "selection_method"
ATTR_DEPARTURE_COUNT: Final = "departure_count"
ATTR_UNREACHABLE_DEPARTURES: Final = "unreachable_departures"
ATTR_PAUSED_REASON: Final = "paused_reason"
ATTR_ACTIVE_HOURS: Final = "active_hours"
ATTR_LINE_TARGETS: Final = "line_targets"
ATTR_MINUTES_UNTIL_DEPARTURE: Final = "minutes_until_departure"
ATTR_LINE_COLORS: Final = "line_colors"
ATTR_DISTANCE_M: Final = "distance_m"

SELECTION_METHOD: Final = (
    "Earliest real-time departure that can still be reached on foot; "
    "departures that would require walking faster than configured are skipped."
)
