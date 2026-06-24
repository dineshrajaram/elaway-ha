"""Shared device info for Elaway entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_CHARGE_POINT_ID, CONF_NAME, DOMAIN, MANUFACTURER


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Build the single charger device all entities attach to."""
    charge_point_id = entry.data[CONF_CHARGE_POINT_ID]
    return DeviceInfo(
        identifiers={(DOMAIN, charge_point_id)},
        name=entry.data.get(CONF_NAME, "Elaway charger"),
        manufacturer=MANUFACTURER,
        model="EV charger",
    )
