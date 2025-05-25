from homeassistant.helpers.entity import Entity

from .const import (
    DOMAIN,
    CONF_INDEX_INJECTION_SENSOR,
    CONF_START_INDEX_INJECTION,
    CONF_INDEX_OUT_BATTERY_ENERGY,
    CONF_INDEX_IN_BATTERY_ENERGY,
    CONF_INDEX_VIRTUAL_BASE,
    CONF_CAPACITY_BATTERY,
)

SENSOR_TYPES = [
    (CONF_INDEX_OUT_BATTERY_ENERGY,
     "Index Out Battery Energy", "kWh", "energy", "total_increasing"),
    (CONF_INDEX_IN_BATTERY_ENERGY, "Index In Battery Energy",
     "kWh", "energy", "total_increasing"),
    (CONF_CAPACITY_BATTERY, "Capacity Battery", "kWh", "energy", "total"),
    (CONF_INDEX_VIRTUAL_BASE, "Virtual Consumption Energy",
     "kWh", "energy", "total_increasing"),
]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up UrbanSolar sensors from a config entry."""
    # Stocke les données de config pour accès global
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = config_entry.data

    sensors = []
    for sensor_id, name, unit, device_class, state_class in SENSOR_TYPES:
        sensors.append(UrbanSolarSensor(
            hass, config_entry, name, sensor_id, unit, device_class, state_class))
    async_add_entities(sensors, True)


class UrbanSolarSensor(Entity):
    """Representation of an Urban Solar Sensor."""

    def __init__(self, hass, config_entry, name, unique_id, unit, device_class, state_class):
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._unique_id = unique_id
        self._unit = unit
        self._device_class = device_class
        self._state_class = state_class
        self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self):
        """Return the unique ID of the sensor."""
        return self._unique_id

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def device_class(self):
        return self._device_class

    @property
    def state_class(self):
        return self._state_class

    @property
    def precision(self):
        """Return the precision of the sensor."""
        if self._device_class == "energy":
            return 3  # kWh
        return None  # Pas de précision spécifique pour d'autres types

    def update(self):
        # Ici, tu dois mettre à jour self._state avec la vraie valeur
        pass

    @property
    def extra_state_attributes(self):
        return {}

    async def async_update(self):
        """Met à jour l'état du capteur."""
        config = self.hass.data[DOMAIN][self.config_entry.entry_id]
        if self._unique_id == CONF_INDEX_IN_BATTERY_ENERGY:
            sensor_entity_id = config[CONF_INDEX_INJECTION_SENSOR]
            start_index = config[CONF_START_INDEX_INJECTION]
            state = self.hass.states.get(sensor_entity_id)
            if state and state.state not in (None, "unknown", "unavailable"):
                try:
                    self._state = float(state.state) - float(start_index)
                except ValueError:
                    self._state = None
            else:
                self._state = None
        # ...autres sensors...

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
