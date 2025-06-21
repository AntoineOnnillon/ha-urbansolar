from homeassistant.helpers.entity import Entity

from .const import (
    DOMAIN,
    CONF_INDEX_BASE_SENSOR,
    CONF_INDEX_INJECTION_SENSOR,
    CONF_CAPACITY_BATTERY,
    CONF_START_BATTERY_ENERGY,
)

SENSOR_TYPES = [
    (CONF_CAPACITY_BATTERY, "Capacity Battery", "kW",
     "energy_storage", {"state_class": "total"}),
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
        # Initialisation de la batterie à la création
        if self._unique_id == CONF_CAPACITY_BATTERY:
            self._state = config_entry.data.get(CONF_START_BATTERY_ENERGY, 0.0)
        else:
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

        if self._unique_id == CONF_CAPACITY_BATTERY:
            injection_entity_id = config[CONF_INDEX_INJECTION_SENSOR]
            base_entity_id = config[CONF_INDEX_BASE_SENSOR]
            injection_state = self.hass.states.get(injection_entity_id)
            base_state = self.hass.states.get(base_entity_id)

            # Initialisation des variables persistantes
            if not hasattr(self, "_last_injection") or self._last_injection is None:
                self._last_injection = None
            if not hasattr(self, "_last_base") or self._last_base is None:
                self._last_base = None
            if self._state is None:
                self._state = 0.0

            # Récupération des valeurs actuelles
            try:
                injection = float(injection_state.state) if injection_state and injection_state.state not in ("unknown", "unavailable") else None
                base = float(base_state.state) if base_state and base_state.state not in ("unknown", "unavailable") else None
            except ValueError:
                injection = None
                base = None

            # Calcul du delta et mise à jour de la batterie
            if injection is not None and base is not None:
                if self._last_injection is not None and self._last_base is not None:
                    delta_injection = injection - self._last_injection
                    delta_base = base - self._last_base
                    # On ne prend que les variations positives
                    if delta_injection > 0:
                        self._state += delta_injection
                    if delta_base > 0:
                        self._state -= delta_base
                    # Empêche la batterie de descendre sous 0
                    self._state = max(0, self._state)
                self._last_injection = injection
                self._last_base = base

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
