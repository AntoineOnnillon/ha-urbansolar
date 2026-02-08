from __future__ import annotations

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, CONF_REBUILD_HISTORY

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    if entry.data.get(CONF_REBUILD_HISTORY):
        async def _run_rebuild():
            from .history import async_rebuild_price_history
            result = await async_rebuild_price_history(hass, entry)
            if result:
                _LOGGER.info("Cost history rebuild finished: %s rows", result)
            data = dict(entry.data)
            data[CONF_REBUILD_HISTORY] = False
            hass.config_entries.async_update_entry(entry, data=data)

        hass.async_create_task(_run_rebuild())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
