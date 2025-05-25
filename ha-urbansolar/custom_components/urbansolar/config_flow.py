from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from typing import Dict, Any

class UrbanSolarConfigFlow(config_entries.ConfigFlow, domain="urbansolar"):
    VERSION = 1

    async def async_step_user(self, user_input: Dict[str, Any] = None):
        if user_input is None:
            return self.async_show_form(step_id="user")

        # Here you would validate the user input and possibly create a config entry
        return self.async_create_entry(title="Urban Solar", data=user_input)

    async def async_step_import(self, import_info: Dict[str, Any]):
        return self.async_create_entry(title="Urban Solar", data=import_info)