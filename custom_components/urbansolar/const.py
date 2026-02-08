# This file contains constants used in the integration, such as configuration keys and identifiers.

DOMAIN = "urbansolar"
CONF_START_BATTERY_ENERGY = "start_battery_energy"
CONF_INDEX_BASE_SENSOR = "index_base_sensor"
CONF_INDEX_INJECTION_SENSOR = "index_injection_sensor"
CONF_INDEX_BATTERY_IN = "battery_in_energy"
CONF_INDEX_BATTERY_OUT = "battery_out_energy"
CONF_CAPACITY_BATTERY = "battery_capacity"
CONF_INDEX_BASE_EMULATED = "index_base_emulated"
CONF_INDEX_INJECTION_EMULATED = "index_injection_emulated"
CONF_REBUILD_HISTORY = "rebuild_history"

# Tariffs / pricing configuration
CONF_TARIFF_OPTION = "tariff_option"
CONF_SUBSCRIBED_POWER = "subscribed_power_kva"

TARIFF_OPTION_BASE = "base"
TARIFF_OPTION_HPHC = "hphc"

TARIFF_POWER_OPTIONS = [3, 6, 9, 12, 15, 18, 24, 30, 36]

UNIT_EUR_PER_KWH = "EUR/kWh"

SENSOR_TARIFF_ENERGY_TTC = "tariff_energy_ttc"
SENSOR_TARIFF_ACH_TTC = "tariff_acheminement_ttc"
SENSOR_TARIFF_ENERGY_HP_TTC = "tariff_energy_hp_ttc"
SENSOR_TARIFF_ENERGY_HC_TTC = "tariff_energy_hc_ttc"
SENSOR_TARIFF_ACH_HP_TTC = "tariff_acheminement_hp_ttc"
SENSOR_TARIFF_ACH_HC_TTC = "tariff_acheminement_hc_ttc"
