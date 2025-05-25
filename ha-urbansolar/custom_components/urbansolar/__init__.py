""" 
This file is the entry point for the UrbanSolar integration. 
It initializes the component and may contain startup configuration.
"""

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
