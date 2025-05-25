from homeassistant.helpers.entity import Entity

from .const import CONF_INDEX_INJECTION_SENSOR, CONF_START_INDEX_INJECTION

SENSOR_TYPES = [
    ("index_out_battery_energy", "Index Out Battery Energy", "kWh"),
    ("index_in_battery_energy", "Index In Battery Energy", "kWh"),
    ("capacity_battery", "Capacity Battery", "kWh"),
    ("virtual_consumption_energy", "Virtual Consumption Energy", "kWh"),
]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up UrbanSolar sensors from a config entry."""
    sensors = []
    for sensor_id, name, unit in SENSOR_TYPES:
        sensors.append(UrbanSolarSensor(name, sensor_id, unit))
    async_add_entities(sensors, True)


class UrbanSolarSensor(Entity):
    """Representation of an Urban Solar Sensor."""

    def __init__(self, name, unique_id, unit):
        self._name = name
        self._unique_id = unique_id
        self._unit = unit
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

    def update(self):
        # Ici, tu dois mettre à jour self._state avec la vraie valeur
        pass

    @property
    def extra_state_attributes(self):
        return {}

    async def async_update(self):
        """Met à jour l'état du capteur."""
        if self._unique_id == "index_in_battery_energy":
            # Récupère la valeur actuelle du sensor d'injection
            sensor_entity_id = self.hass.data[self._unique_id][CONF_INDEX_INJECTION_SENSOR]
            start_index = self.hass.data[self._unique_id][CONF_START_INDEX_INJECTION]
            state = self.hass.states.get(sensor_entity_id)
            if state and state.state not in (None, "unknown", "unavailable"):
                try:
                    self._state = float(state.state) - float(start_index)
                except ValueError:
                    self._state = None
            else:
                self._state = None
        # ...autres sensors...
