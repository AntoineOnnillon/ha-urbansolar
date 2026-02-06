import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import selector
from homeassistant.const import UnitOfEnergy, UnitOfPower
from typing import Any, Dict

from .const import (
    DOMAIN,
    CONF_INDEX_BASE_SENSOR,
    CONF_INDEX_INJECTION_SENSOR,
    CONF_START_BATTERY_ENERGY,
    CONF_TARIFF_OPTION,
    CONF_SUBSCRIBED_POWER,
    TARIFF_OPTION_BASE,
    TARIFF_OPTION_HPHC,
    TARIFF_POWER_OPTIONS,
)


class UrbanSolarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Urban Solar", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_START_BATTERY_ENERGY, default=0): vol.All(vol.Coerce(float), vol.Range(min=0)),
                vol.Required(CONF_TARIFF_OPTION, default=TARIFF_OPTION_BASE): selector({
                    "select": {
                        "options": [
                            {"label": "Base (HB)", "value": TARIFF_OPTION_BASE},
                            {"label": "Heures pleines / Heures creuses (HP/HC)", "value": TARIFF_OPTION_HPHC},
                        ],
                        "mode": "dropdown",
                    }
                }),
                vol.Required(CONF_SUBSCRIBED_POWER, default=6): selector({
                    "select": {
                        "options": [
                            {"label": f"{value} kVA", "value": value}
                            for value in TARIFF_POWER_OPTIONS
                        ],
                        "mode": "dropdown",
                    }
                }),
                vol.Required(CONF_INDEX_BASE_SENSOR): selector({
                    "entity": {
                        "domain": "sensor",
                        "device_class": "energy"
                    }
                }),
                vol.Required(CONF_INDEX_INJECTION_SENSOR): selector({
                    "entity": {
                        "domain": "sensor",
                        "device_class": "energy"
                    }
                }),
            })

        )

    async def async_step_import(self, import_info: Dict[str, Any]):
        return self.async_create_entry(title="Urban Solar", data=import_info)
