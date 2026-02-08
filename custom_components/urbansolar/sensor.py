from homeassistant.helpers.entity import Entity
from homeassistant.helpers.restore_state import RestoreEntity  # Ajout
from homeassistant.helpers.event import async_track_state_change, async_track_time_change
from homeassistant.core import callback
import logging

from .const import (
    DOMAIN,
    CONF_INDEX_BASE_SENSOR,
    CONF_INDEX_INJECTION_SENSOR,
    CONF_START_BATTERY_ENERGY,
    CONF_INDEX_BATTERY_IN,
    CONF_INDEX_BATTERY_OUT,
    CONF_CAPACITY_BATTERY,
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

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES = [
    (CONF_INDEX_BATTERY_IN, "Battery In", "kWh",
        "energy", {"state_class": "total_increasing"}),
    (CONF_INDEX_BATTERY_OUT, "Battery Out", "kWh",
        "energy", {"state_class": "total_increasing"}),
    (CONF_CAPACITY_BATTERY, "Capacity Battery", "kW",
     "energy_storage", {"state_class": "total"}),
]

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
                    self._state = 0.0
            else:
                self._state = 0.0
        elif self._unique_id == CONF_INDEX_BATTERY_OUT:
            if last_state is not None and last_state.state not in ("unknown", "unavailable"):
                try:
                    self._state = float(last_state.state)
                except ValueError:
                    self._state = 0.0
            else:
                self._state = 0.0

        config = self.hass.data[DOMAIN][self.config_entry.entry_id]
        if self._unique_id == CONF_CAPACITY_BATTERY:
            battery_in_entity_id = config.get(CONF_INDEX_BATTERY_IN)
            battery_out_entity_id = config.get(CONF_INDEX_BATTERY_OUT)
            if battery_in_entity_id:
                async_track_state_change(
                    self.hass, battery_in_entity_id, self._trigger_update
                )
            if battery_out_entity_id:
                async_track_state_change(
                    self.hass, battery_out_entity_id, self._trigger_update
                )

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

    def update(self):
        # Ici, tu dois mettre à jour self._state avec la vraie valeur
        pass

    async def async_update(self):
        """Met à jour l'état du capteur."""
        config = self.hass.data[DOMAIN][self.config_entry.entry_id]

        # _LOGGER.debug("Updating %s with config: %s", self._unique_id, config)
        if self._unique_id == CONF_CAPACITY_BATTERY:
            # Récupération de la capacité de la batterie
            start_battery_capacity = config.get(CONF_START_BATTERY_ENERGY, 0.0)
            battery_in_state = self.hass.data[DOMAIN].get(CONF_INDEX_BATTERY_IN).state
            battery_out_state = self.hass.data[DOMAIN].get(CONF_INDEX_BATTERY_OUT).state

            if start_battery_capacity is None:
                _LOGGER.error("Battery capacity is not configured.")
                return

            _LOGGER.debug("Battery Out: %s, Battery In: %s, Start Capacity: %s", battery_out_state, battery_in_state, start_battery_capacity)

            # Calcul du delta et mise à jour de la batterie
            if battery_out_state is not None and battery_in_state is not None:
                self._state = battery_in_state - battery_out_state + start_battery_capacity
        elif self._unique_id == CONF_INDEX_BATTERY_OUT:
            base_entity_id = config.get(CONF_INDEX_BASE_SENSOR)
            base_state = self.hass.states.get(base_entity_id)
            battery_capacity = self.hass.data[DOMAIN].get(CONF_CAPACITY_BATTERY).state
            if not base_entity_id:
                _LOGGER.error("Base sensor entity ID is not configured.")
                return

            # Initialisation des variables persistantes
            if self._state is None:
                self._state = 0.0

            # Récupération des valeurs actuelles
            try:
                base = float(base_state.state) if base_state and base_state.state not in ("unknown", "unavailable") else None
            except ValueError:
                base = None

            # Calcul du delta et mise à jour de la batterie
            if base is not None:
                if hasattr(self, "_last_base") and not self._last_base is None:
                    delta_base = base - self._last_base
                    if battery_capacity is not None and delta_base > 0:
                        if delta_base <= battery_capacity:
                            self._state += delta_base
                        else:
                            self._state += battery_capacity
                self._last_base = base
        elif self._unique_id == CONF_INDEX_BATTERY_IN:
            injection_entity_id = config.get(CONF_INDEX_INJECTION_SENSOR)
            injection_state = self.hass.states.get(injection_entity_id)

            # Initialisation des variables persistantes
            if self._state is None:
                self._state = 0.0

            # Récupération des valeurs actuelles
            try:
                injection = float(injection_state.state) if injection_state and injection_state.state not in ("unknown", "unavailable") else None
            except ValueError:
                injection = None

            # Calcul du delta et mise à jour de la batterie
            if injection is not None:
                if hasattr(self, "_last_injection") and not self._last_injection is None:
                    delta_injection = injection - self._last_injection
                    # On ne prend que les variations positives
                    if delta_injection > 0:
                        self._state += delta_injection
                self._last_injection = injection

        _LOGGER.debug("Update %s: state=%s", self._unique_id, self._state)

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
