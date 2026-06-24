"""The Elaway integration."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ElawayApi
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CHARGE_POINT_ID,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EVSE_ID,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_EXPIRY,
    DEFAULT_BASE_URL,
    DEFAULT_CLIENT_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import ElawayCoordinator


def _build_api(hass: HomeAssistant, entry: ConfigEntry) -> ElawayApi:
    data = entry.data
    session = async_get_clientsession(hass)

    async def token_update_cb(tokens: dict[str, Any]) -> None:
        # Persist rotated token + access token + expiry to the config entry.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **tokens}
        )

    return ElawayApi(
        session,
        base_url=DEFAULT_BASE_URL,
        client_id=data.get(CONF_CLIENT_ID, DEFAULT_CLIENT_ID),
        client_secret=data[CONF_CLIENT_SECRET],
        evse_id=int(data[CONF_EVSE_ID]),
        charge_point_id=data[CONF_CHARGE_POINT_ID],
        refresh_token=data[CONF_REFRESH_TOKEN],
        access_token=data.get(CONF_ACCESS_TOKEN),
        token_expiry=float(data.get(CONF_TOKEN_EXPIRY, 0) or 0),
        token_update_cb=token_update_cb,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Elaway from a config entry."""
    api = _build_api(hass, entry)
    scan_interval = int(
        entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
    )
    coordinator = ElawayCoordinator(hass, api, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (e.g. new poll interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
