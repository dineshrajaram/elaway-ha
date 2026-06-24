"""Constants for the Elaway integration."""

DOMAIN = "elaway"
PLATFORMS = ["switch", "sensor", "button"]

# --- API ---
DEFAULT_BASE_URL = "https://no.eu-elaway.charge.ampeco.tech/api/v1/app"
DEFAULT_CLIENT_ID = "1"
# The OAuth client_secret is the AMPECO app secret and is NOT shipped with this
# integration. Extract it from the Elaway app (e.g. via mitmproxy) and supply it
# in the config flow.

MANUFACTURER = "Elaway (AMPECO)"

# --- Polling ---
DEFAULT_SCAN_INTERVAL = 60  # seconds

# --- Token handling ---
# Refresh this many seconds before the access token's actual expiry.
TOKEN_REFRESH_BUFFER = 86400  # 1 day of slack on a ~30 day token

# --- Config entry keys ---
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCESS_TOKEN = "access_token"
CONF_TOKEN_EXPIRY = "token_expiry"
CONF_CHARGE_POINT_ID = "charge_point_id"
CONF_EVSE_ID = "evse_id"
CONF_NAME = "name"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_SCAN_INTERVAL = "scan_interval"

# --- Charger status values (sensor states) ---
STATUS_DISCONNECTED = "disconnected"  # no vehicle connected
STATUS_READY = "ready"  # vehicle connected, idle — switch may start
STATUS_CHARGING = "charging"  # session active
STATUS_UNAVAILABLE = "unavailable"  # offline / fault / unknown
