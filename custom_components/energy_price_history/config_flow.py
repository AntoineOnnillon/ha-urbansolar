import json
import re
import voluptuous as vol
from typing import Any, Dict, List
from homeassistant import config_entries
from homeassistant.helpers.selector import selector

from .const import (
    DOMAIN,
    CONF_ENERGY_SENSOR,
    CONF_COST_SENSOR,
    CONF_PRICE_PERIODS,
    CONF_REBUILD_HISTORY,
)


def _normalize_periods(raw: str) -> List[Dict[str, Any]]:
    """Parse a list of price periods from a loose JSON-like string."""
    if not raw:
        return []

    # Normalize unquoted keys: from:, to:, price:
    normalized = re.sub(r"\bfrom\s*:", '"from":', raw)
    normalized = re.sub(r"\bto\s*:", '"to":', normalized)
    normalized = re.sub(r"\bprice\s*:", '"price":', normalized)

    periods = json.loads(normalized)
    if not isinstance(periods, list):
        raise ValueError("price_periods must be a list")

    parsed = []
    for item in periods:
        if not isinstance(item, dict):
            raise ValueError("each period must be an object")
        if "from" not in item or "to" not in item or "price" not in item:
            raise ValueError("each period needs from/to/price")
        parsed.append(
            {
                "from": str(item["from"]),
                "to": str(item["to"]),
                "price": float(item["price"]),
            }
        )
    return parsed


class EnergyPriceHistoryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                periods = _normalize_periods(user_input[CONF_PRICE_PERIODS])
                user_input[CONF_PRICE_PERIODS] = periods
            except (ValueError, json.JSONDecodeError):
                errors[CONF_PRICE_PERIODS] = "invalid_periods"

            if not errors:
                return self.async_create_entry(title="Energy Price History", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENERGY_SENSOR): selector(
                        {
                            "entity": {
                                "domain": "sensor",
                                "device_class": "energy",
                            }
                        }
                    ),
                    vol.Required(CONF_COST_SENSOR): selector(
                        {
                            "entity": {
                                "domain": "sensor",
                            }
                        }
                    ),
                    vol.Required(CONF_PRICE_PERIODS): selector(
                        {
                            "text": {
                                "multiline": True,
                                "type": "text",
                            }
                        }
                    ),
                    vol.Required(CONF_REBUILD_HISTORY, default=False): selector({"boolean": {}}),
                }
            ),
            errors=errors,
            description_placeholders={
                "periods_example": '[{"from":"2025-01-01","to":"2025-06-30","price":0.18}]'
            },
        )
