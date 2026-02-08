from __future__ import annotations

import asyncio

from homeassistant import config_entries, core

from .const import (
    DOMAIN,
    CONF_REBUILD_HISTORY,
    CONF_INDEX_BATTERY_IN,
    CONF_INDEX_BATTERY_OUT,
    CONF_CAPACITY_BATTERY,
    CONF_INDEX_BASE_EMULATED,
    CONF_INDEX_INJECTION_EMULATED,
    CONF_TARIFF_OPTION,
    CONF_SUBSCRIBED_POWER,
    TARIFF_OPTION_BASE,
)

SERVICE_REBUILD_HISTORY = "rebuild_history"


async def async_setup(hass: core.HomeAssistant, config: dict) -> bool:
    """Set up the UrbanSolar component."""
    return True


async def async_setup_entry(hass: core.HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Set up a config entry for UrbanSolar."""
    # Charger la plateforme sensor
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    _register_services(hass)
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
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


def _register_services(hass: core.HomeAssistant) -> None:
    if hass.data.get(DOMAIN, {}).get("services_registered"):
        return

    hass.data.setdefault(DOMAIN, {})["services_registered"] = True

    async def _handle_rebuild(call):
        from .history import async_rebuild_history

        lock = hass.data[DOMAIN].setdefault("rebuild_lock", asyncio.Lock())
        async with lock:
            entries = hass.config_entries.async_entries(DOMAIN)
            entry_id = call.data.get("entry_id")
            if entry_id:
                entries = [e for e in entries if e.entry_id == entry_id]

            for entry in entries:
                result = await async_rebuild_history(hass, entry)
                if result and entry.data.get(CONF_REBUILD_HISTORY):
                    data = dict(entry.data)
                    data[CONF_REBUILD_HISTORY] = False
                    hass.config_entries.async_update_entry(entry, data=data)
                if result:
                    sensor_battery_in = hass.data[DOMAIN].get(CONF_INDEX_BATTERY_IN)
                    sensor_battery_out = hass.data[DOMAIN].get(CONF_INDEX_BATTERY_OUT)
                    sensor_capacity = hass.data[DOMAIN].get(CONF_CAPACITY_BATTERY)
                    sensor_base_emulated = hass.data[DOMAIN].get(CONF_INDEX_BASE_EMULATED)
                    sensor_injection_emulated = hass.data[DOMAIN].get(CONF_INDEX_INJECTION_EMULATED)
                    if sensor_battery_in:
                        sensor_battery_in._state = result.battery_in
                        sensor_battery_in._last_injection = result.last_injection_state
                        sensor_battery_in.async_write_ha_state()
                    if sensor_battery_out:
                        sensor_battery_out._state = result.battery_out
                        sensor_battery_out._last_base = result.last_base_state
                        sensor_battery_out.async_write_ha_state()
                    if sensor_capacity:
                        sensor_capacity._state = result.capacity
                        sensor_capacity.async_write_ha_state()
                    if sensor_base_emulated:
                        sensor_base_emulated._state = result.base_emulated
                        sensor_base_emulated._last_base = result.last_base_state
                        sensor_base_emulated._last_injection = result.last_injection_state
                        sensor_base_emulated.async_write_ha_state()
                    if sensor_injection_emulated and result.last_injection_state is not None:
                        sensor_injection_emulated._state = result.last_injection_state
                        sensor_injection_emulated.async_write_ha_state()

    hass.services.async_register(DOMAIN, SERVICE_REBUILD_HISTORY, _handle_rebuild)
