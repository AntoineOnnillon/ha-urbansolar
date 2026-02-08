""" 
This file is the entry point for the UrbanSolar integration. 
It initializes the component and may contain startup configuration.
"""

from .const import (
    CONF_TARIFF_OPTION,
    CONF_SUBSCRIBED_POWER,
    TARIFF_OPTION_BASE,
)

from homeassistant import config_entries, core
from homeassistant.helpers import discovery

DOMAIN = "urbansolar"


async def async_setup(hass: core.HomeAssistant, config: dict) -> bool:
    """Set up the UrbanSolar component."""
    return True


async def async_setup_entry(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Set up a config entry for UrbanSolar."""
    # Charger la plateforme sensor
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    return True


async def async_unload_entry(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Unload a config entry."""
    await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    return True


async def async_migrate_entry(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Migrate old entry."""
    if entry.version == 1:
        data = dict(entry.data)
        data.setdefault(CONF_TARIFF_OPTION, TARIFF_OPTION_BASE)
        data.setdefault(CONF_SUBSCRIBED_POWER, 6)
        entry.version = 2
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
