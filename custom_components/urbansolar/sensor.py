import asyncio
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.event import async_track_state_change, async_track_time_change
from homeassistant.core import callback
import logging

from .const import (
    DOMAIN,
    CONF_INDEX_BASE_SENSOR,
    CONF_INDEX_INJECTION_SENSOR,
    CONF_START_BATTERY_ENERGY,
    CONF_REBUILD_HISTORY,
    CONF_INDEX_BATTERY_IN,
    CONF_INDEX_BATTERY_OUT,
    CONF_CAPACITY_BATTERY,
    CONF_INDEX_BASE_EMULATED,
    CONF_INDEX_INJECTION_EMULATED,
    CONF_TARIFF_OPTION,
    SENSOR_TARIFF_ACH_HC_TTC,
    SENSOR_TARIFF_ACH_HP_TTC,
    SENSOR_TARIFF_ACH_TTC,
    SENSOR_TARIFF_ENERGY_HC_TTC,
    SENSOR_TARIFF_ENERGY_HP_TTC,
    SENSOR_TARIFF_ENERGY_TTC,
    TARIFF_OPTION_HPHC,
    UNIT_EUR_PER_KWH,
)
from .tariffs import TariffData
from .history import async_rebuild_history

_LOGGER = logging.getLogger(__name__)


def _as_float(state):
    if state is None:
        return None
    if state.state in ("unknown", "unavailable"):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None

SENSOR_TYPES = [
    (CONF_INDEX_BATTERY_IN, "Battery In", "kWh",
        "energy", {"state_class": "total_increasing"}),
    (CONF_INDEX_BATTERY_OUT, "Battery Out", "kWh",
        "energy", {"state_class": "total_increasing"}),
    (CONF_CAPACITY_BATTERY, "Capacity Battery", "kW",
     "energy_storage", {"state_class": "total"}),
    (CONF_INDEX_BASE_EMULATED, "Base Emulated", "kWh",
        "energy", {"state_class": "total_increasing"}),
    (CONF_INDEX_INJECTION_EMULATED, "Injection Emulated", "kWh",
        "energy", {"state_class": "total_increasing"}),
]

SUGGESTED_OBJECT_IDS = {
    CONF_INDEX_BATTERY_IN: "battery_in_energy",
    CONF_INDEX_BATTERY_OUT: "battery_out_energy",
    CONF_CAPACITY_BATTERY: "battery_capacity",
    CONF_INDEX_BASE_EMULATED: "base_emulated_energy",
    CONF_INDEX_INJECTION_EMULATED: "injection_emulated_energy",
}

TARIFF_SENSOR_TYPES_BASE = [
    (SENSOR_TARIFF_ENERGY_TTC, "Tarif Energie TTC", UNIT_EUR_PER_KWH, None, {"state_class": "measurement"}),
    (SENSOR_TARIFF_ACH_TTC, "Tarif Acheminement TTC", UNIT_EUR_PER_KWH, None, {"state_class": "measurement"}),
]

TARIFF_SENSOR_TYPES_HPHC = [
    (SENSOR_TARIFF_ENERGY_HP_TTC, "Tarif Energie HP TTC", UNIT_EUR_PER_KWH, None, {"state_class": "measurement"}),
    (SENSOR_TARIFF_ENERGY_HC_TTC, "Tarif Energie HC TTC", UNIT_EUR_PER_KWH, None, {"state_class": "measurement"}),
    (SENSOR_TARIFF_ACH_HP_TTC, "Tarif Acheminement HP TTC", UNIT_EUR_PER_KWH, None, {"state_class": "measurement"}),
    (SENSOR_TARIFF_ACH_HC_TTC, "Tarif Acheminement HC TTC", UNIT_EUR_PER_KWH, None, {"state_class": "measurement"}),
]

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up UrbanSolar sensors from a config entry."""
    # Stocke les données de config pour accès global
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = config_entry.data

    sensors = []
    for sensor_id, name, unit, device_class, attributes in SENSOR_TYPES:
        sensor = UrbanSolarSensor(hass, config_entry, name, sensor_id, unit, device_class, attributes)
        sensors.append(sensor)
        hass.data[DOMAIN][sensor_id] = sensor  # Stocke l'entité dans les données de l'intégration

    tariff_option = config_entry.data.get(CONF_TARIFF_OPTION)
    if tariff_option:
        hass.data[DOMAIN].setdefault("tariff_data", {})
        tariff_data = TariffData(hass, config_entry)
        hass.data[DOMAIN]["tariff_data"][config_entry.entry_id] = tariff_data
        tariff_sensors = (
            TARIFF_SENSOR_TYPES_HPHC
            if tariff_option == TARIFF_OPTION_HPHC
            else TARIFF_SENSOR_TYPES_BASE
        )
        created_tariff_sensors = []
        for sensor_id, name, unit, device_class, attributes in tariff_sensors:
            sensor = UrbanSolarTariffSensor(
                hass,
                config_entry,
                name,
                sensor_id,
                unit,
                device_class,
                attributes,
                tariff_data,
            )
            sensors.append(sensor)
            created_tariff_sensors.append(sensor)

        async def _run_monthly_tariff_update():
            await tariff_data.async_update(force=True)
            for entity in created_tariff_sensors:
                await entity.async_update_ha_state(force_refresh=True)

        @callback
        def _monthly_tariff_update(now):
            if now.day != 1:
                return
            hass.async_create_task(_run_monthly_tariff_update())

        remove_listener = async_track_time_change(
            hass,
            _monthly_tariff_update,
            hour=0,
            minute=0,
            second=0,
        )
        config_entry.async_on_unload(remove_listener)
    async_add_entities(sensors, True)

    calc_locks = hass.data[DOMAIN].setdefault("calc_locks", {})
    calc_lock = calc_locks.setdefault(config_entry.entry_id, asyncio.Lock())

    async def _recompute_from_sources():
        async with calc_lock:
            config = hass.data[DOMAIN][config_entry.entry_id]
            base_entity_id = config.get(CONF_INDEX_BASE_SENSOR)
            injection_entity_id = config.get(CONF_INDEX_INJECTION_SENSOR)

            base = _as_float(hass.states.get(base_entity_id)) if base_entity_id else None
            injection = _as_float(hass.states.get(injection_entity_id)) if injection_entity_id else None

            sensor_battery_in = hass.data[DOMAIN].get(CONF_INDEX_BATTERY_IN)
            sensor_battery_out = hass.data[DOMAIN].get(CONF_INDEX_BATTERY_OUT)
            sensor_capacity = hass.data[DOMAIN].get(CONF_CAPACITY_BATTERY)
            sensor_base_emulated = hass.data[DOMAIN].get(CONF_INDEX_BASE_EMULATED)
            sensor_injection_emulated = hass.data[DOMAIN].get(CONF_INDEX_INJECTION_EMULATED)

            if not all((sensor_battery_in, sensor_battery_out, sensor_capacity, sensor_base_emulated)):
                return

            battery_in_total = sensor_battery_in._state or 0.0
            battery_out_total = sensor_battery_out._state or 0.0

            last_injection = getattr(sensor_battery_in, "_last_injection", None)
            last_base = getattr(sensor_battery_out, "_last_base", None)

            delta_inj = 0.0
            if injection is not None:
                if last_injection is None:
                    last_injection = injection
                else:
                    delta_inj = injection - last_injection
                    if delta_inj > 0:
                        battery_in_total += delta_inj
                    last_injection = injection
                if sensor_injection_emulated is not None:
                    sensor_injection_emulated._state = injection

            delta_base = 0.0
            if base is not None:
                if last_base is None:
                    last_base = base
                else:
                    delta_base = base - last_base
                    if delta_base > 0:
                        capacity_before = max(battery_in_total - battery_out_total, 0.0)
                        delta_out = min(delta_base, capacity_before)
                        battery_out_total += delta_out
                    last_base = base

            capacity = max(battery_in_total - battery_out_total, 0.0)
            base_emulated_total = sensor_base_emulated._state or 0.0
            if base is not None:
                base_emulated_total = max(base - battery_out_total, 0.0)

            sensor_battery_in._state = battery_in_total
            sensor_battery_out._state = battery_out_total
            sensor_capacity._state = capacity
            sensor_base_emulated._state = base_emulated_total
            if sensor_injection_emulated is not None and injection is not None:
                sensor_injection_emulated._state = injection

            sensor_battery_in._last_injection = last_injection
            sensor_battery_out._last_base = last_base
            sensor_base_emulated._last_base = last_base
            sensor_base_emulated._last_injection = last_injection

            sensor_battery_in.async_write_ha_state()
            sensor_battery_out.async_write_ha_state()
            sensor_capacity.async_write_ha_state()
            sensor_base_emulated.async_write_ha_state()
            if sensor_injection_emulated is not None and injection is not None:
                sensor_injection_emulated.async_write_ha_state()

    hass.data[DOMAIN].setdefault("recompute", {})[config_entry.entry_id] = _recompute_from_sources

    @callback
    def _source_update(entity_id, old_state, new_state):
        hass.async_create_task(_recompute_from_sources())

    if config_entry.data.get(CONF_INDEX_BASE_SENSOR):
        remove_base = async_track_state_change(
            hass,
            config_entry.data[CONF_INDEX_BASE_SENSOR],
            _source_update,
        )
        config_entry.async_on_unload(remove_base)
    if config_entry.data.get(CONF_INDEX_INJECTION_SENSOR):
        remove_inj = async_track_state_change(
            hass,
            config_entry.data[CONF_INDEX_INJECTION_SENSOR],
            _source_update,
        )
        config_entry.async_on_unload(remove_inj)

    hass.async_create_task(_recompute_from_sources())

    if config_entry.data.get(CONF_REBUILD_HISTORY):
        async def _run_rebuild():
            result = await async_rebuild_history(hass, config_entry)
            if result:
                # Align live sensor states with rebuilt totals
                sensor_battery_in = hass.data[DOMAIN].get(CONF_INDEX_BATTERY_IN)
                sensor_battery_out = hass.data[DOMAIN].get(CONF_INDEX_BATTERY_OUT)
                sensor_capacity = hass.data[DOMAIN].get(CONF_CAPACITY_BATTERY)
                sensor_base_emulated = hass.data[DOMAIN].get(CONF_INDEX_BASE_EMULATED)
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
                sensor_injection_emulated = hass.data[DOMAIN].get(CONF_INDEX_INJECTION_EMULATED)
                if sensor_injection_emulated and result.last_injection_state is not None:
                    sensor_injection_emulated._state = result.last_injection_state
                    sensor_injection_emulated.async_write_ha_state()

            # Disable rebuild flag to avoid running at every restart
            data = dict(config_entry.data)
            data[CONF_REBUILD_HISTORY] = False
            hass.config_entries.async_update_entry(config_entry, data=data)

        hass.async_create_task(_run_rebuild())

class UrbanSolarSensor(RestoreEntity, Entity):  # Hérite de RestoreEntity
    """Representation of an Urban Solar Sensor."""

    async def async_added_to_hass(self):
        """Restaure l'état précédent à l'ajout."""
        last_state = await self.async_get_last_state()
        if self._unique_id == CONF_CAPACITY_BATTERY:
            if last_state is not None and last_state.state not in ("unknown", "unavailable"):
                try:
                    self._state = float(last_state.state)
                except ValueError:
                    self._state = self.config_entry.data.get(CONF_START_BATTERY_ENERGY, 0.0)
            else:
                self._state = self.config_entry.data.get(CONF_START_BATTERY_ENERGY, 0.0)
        elif self._unique_id == CONF_INDEX_BATTERY_IN:
            if last_state is not None and last_state.state not in ("unknown", "unavailable"):
                try:
                    self._state = float(last_state.state)
                except ValueError:
                    self._state = self.config_entry.data.get(CONF_START_BATTERY_ENERGY, 0.0)
            else:
                self._state = self.config_entry.data.get(CONF_START_BATTERY_ENERGY, 0.0)
        elif self._unique_id == CONF_INDEX_BATTERY_OUT:
            if last_state is not None and last_state.state not in ("unknown", "unavailable"):
                try:
                    self._state = float(last_state.state)
                except ValueError:
                    self._state = 0.0
            else:
                self._state = 0.0
        elif self._unique_id == CONF_INDEX_BASE_EMULATED:
            if last_state is not None and last_state.state not in ("unknown", "unavailable"):
                try:
                    self._state = float(last_state.state)
                except ValueError:
                    self._state = 0.0
            else:
                self._state = 0.0
        elif self._unique_id == CONF_INDEX_INJECTION_EMULATED:
            if last_state is not None and last_state.state not in ("unknown", "unavailable"):
                try:
                    self._state = float(last_state.state)
                except ValueError:
                    self._state = 0.0
            else:
                self._state = 0.0

    async def _trigger_update(self, entity_id, old_state, new_state):
        """Déclenche une mise à jour de l'état."""
        await self.async_update_ha_state(force_refresh=True)

    def __init__(self, hass, config_entry, name, unique_id, unit, device_class, attributes):
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._unique_id = unique_id
        self._unit = unit
        self._device_class = device_class
        self._attributes = attributes
        # Initialisation de la batterie à la création
        if self._unique_id == CONF_CAPACITY_BATTERY:
            self._state = None
        elif self._unique_id == CONF_INDEX_BATTERY_IN:
            self._state = 0.0
        elif self._unique_id == CONF_INDEX_BATTERY_OUT:
            self._state = 0.0
        elif self._unique_id == CONF_INDEX_BASE_EMULATED:
            self._state = 0.0
        elif self._unique_id == CONF_INDEX_INJECTION_EMULATED:
            self._state = 0.0
        else:
            self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID for this sensor."""
        return self._unique_id

    @property
    def state(self):
        """Return the state of the sensor arrondi à 3 décimales."""
        if self._state is None:
            return None
        return round(self._state, 3)

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def device_class(self):
        return self._device_class

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def suggested_object_id(self):
        return SUGGESTED_OBJECT_IDS.get(self._unique_id)

    @property
    def should_poll(self):
        return False

    def update(self):
        # Ici, tu dois mettre à jour self._state avec la vraie valeur
        pass

    async def async_update(self):
        """Met à jour l'état du capteur (piloté par les sources base/injection)."""
        recompute = self.hass.data.get(DOMAIN, {}).get("recompute", {}).get(self.config_entry.entry_id)
        if recompute:
            await recompute()

    @property
    def device_info(self):
        """Retourne les infos de l'appareil pour rattacher les entités à un device."""
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": "Urban Solar",
            "manufacturer": "Urban Solar",
            "model": "Battery Integration",
            "entry_type": "service",
        }


class UrbanSolarTariffSensor(Entity):
    """Representation of an Urban Solar Tariff Sensor."""

    def __init__(self, hass, config_entry, name, unique_id, unit, device_class, attributes, tariff_data):
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._unique_id = unique_id
        self._unit = unit
        self._device_class = device_class
        self._attributes = attributes or {}
        self._tariff_data = tariff_data
        self._state = None

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def state(self):
        if self._state is None:
            return None
        return round(self._state, 4)

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def device_class(self):
        return self._device_class

    @property
    def extra_state_attributes(self):
        return self._attributes

    async def async_update(self):
        await self._tariff_data.async_update()
        self._state = self._tariff_data.values.get(self._unique_id)
        self._attributes = {
            **(self._attributes or {}),
            "tariff_option": self._tariff_data.tariff_option,
            "subscribed_power_kva": self._tariff_data.subscribed_power,
            "source_url": self._tariff_data.source_url,
            "effective_date": self._tariff_data.effective_date,
            "last_update": self._tariff_data.last_update,
            "last_error": self._tariff_data.last_error,
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.config_entry.entry_id)},
            "name": "Urban Solar",
            "manufacturer": "Urban Solar",
            "model": "Battery Integration",
            "entry_type": "service",
        }
