from homeassistant.helpers.entity import Entity

from .const import (
    DOMAIN,
    CONF_START_INDEX_BASE,
    CONF_START_INDEX_INJECTION,
    CONF_INDEX_BASE_SENSOR,
    CONF_INDEX_INJECTION_SENSOR,
    CONF_INDEX_OUT_BATTERY_ENERGY,
    CONF_INDEX_IN_BATTERY_ENERGY,
    CONF_INDEX_VIRTUAL_BASE,
    CONF_CAPACITY_BATTERY,
)

SENSOR_TYPES = [
    (CONF_INDEX_OUT_BATTERY_ENERGY,
     "Index Out Battery Energy", "kWh", "energy", {"state_class": "total_increasing"}),
    (CONF_INDEX_IN_BATTERY_ENERGY, "Index In Battery Energy",
     "kWh", "energy", {"state_class": "total_increasing"}),
    (CONF_CAPACITY_BATTERY, "Capacity Battery", "kWh",
     "energy_storage", {"state_class": "total"}),
    (CONF_INDEX_VIRTUAL_BASE, "Virtual Consumption Energy",
     "kWh", "energy", {"state_class": "total_increasing"}),
]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up UrbanSolar sensors from a config entry."""
    # Stocke les données de config pour accès global
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][config_entry.entry_id] = config_entry.data

    sensors = []
    for sensor_id, name, unit, device_class, attributes in SENSOR_TYPES:
        sensors.append(UrbanSolarSensor(
            hass, config_entry, name, sensor_id, unit, device_class, attributes))
    async_add_entities(sensors, True)


class UrbanSolarSensor(Entity):
    """Representation of an Urban Solar Sensor."""

    def __init__(self, hass, config_entry, name, unique_id, unit, device_class, attributes):
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._unique_id = unique_id
        self._unit = unit
        self._device_class = device_class
        self._attributes = attributes
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
    def extra_state_attributes(self):
        return self._attributes

    def update(self):
        # Ici, tu dois mettre à jour self._state avec la vraie valeur
        pass

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

        elif self._unique_id == CONF_INDEX_VIRTUAL_BASE:
            # Récupère la valeur du sensor de base
            base_entity_id = config[CONF_INDEX_BASE_SENSOR]
            # ou adapte selon ton entity_id réel
            out_battery_entity_id = "sensor.index_out_battery_energy"
            base_state = self.hass.states.get(base_entity_id)
            out_battery_state = self.hass.states.get(out_battery_entity_id)
            if (
                base_state and base_state.state not in (
                    None, "unknown", "unavailable")
                and out_battery_state and out_battery_state.state not in (None, "unknown", "unavailable")
            ):
                try:
                    self._state = float(base_state.state) - \
                        float(out_battery_state.state)
                except ValueError:
                    self._state = None
            else:
                self._state = None

        elif self._unique_id == CONF_CAPACITY_BATTERY:
            in_battery_entity_id = "sensor.index_in_battery_energy"
            out_battery_entity_id = "sensor.index_out_battery_energy"
            in_battery_state = self.hass.states.get(in_battery_entity_id)
            out_battery_state = self.hass.states.get(out_battery_entity_id)
            if (
                in_battery_state and in_battery_state.state not in (
                    None, "unknown", "unavailable")
                and out_battery_state and out_battery_state.state not in (None, "unknown", "unavailable")
            ):
                try:
                    value = float(in_battery_state.state) - \
                        float(out_battery_state.state)
                    self._state = max(0, value)
                except ValueError:
                    self._state = 0
            else:
                self._state = None

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
