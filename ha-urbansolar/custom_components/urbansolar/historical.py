import itertools
import statistics
import aiohttp
from datetime import datetime, timedelta

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import DiscoveryInfoType
from homeassistant.util import dt as dtutil
from homeassistant.helpers.entity import Entity

from homeassistant_historical_sensor import (
    HistoricalSensor,
    HistoricalState,
    PollUpdateMixin,
)

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
    CONF_HA_TOKEN,
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


class UrbanSolarVirtualBaseHistoricalSensor(PollUpdateMixin, HistoricalSensor, SensorEntity, Entity):
    def __init__(self, hass, config_entry, name, unique_id, unit, device_class, attributes):
        super().__init__()
        self.hass = hass
        self.config_entry = config_entry
        self._name = name
        self._unique_id = unique_id
        self._unit = unit
        self._device_class = device_class
        self._attributes = attributes

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

    async def async_update_historical(self):
        # Récupère l'historique du sensor de base sur 7 jours
        now = datetime.now()
        start = now - timedelta(days=7)
        base_entity_id = self.config_entry.data[CONF_INDEX_BASE_SENSOR]
        # <-- Utilisation du token de la config
        token = self.config_entry.data[CONF_HA_TOKEN]
        url = f"http://localhost:8123/api/history/period/{start.isoformat()}?filter_entity_id={base_entity_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        hist_states = []
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for state in data[0]:
                        if state["state"] not in ("unknown", "unavailable"):
                            hist_states.append(
                                HistoricalState(
                                    state=float(state["state"]),
                                    dt=dtutil.parse_datetime(
                                        state["last_changed"])
                                )
                            )
        self._attr_historical_states = hist_states

    def get_statistic_metadata(self) -> StatisticMetaData:
        #
        # Add sum and mean to base statistics metadata
        # Important: HistoricalSensor.get_statistic_metadata returns an
        # internal source by default.
        #
        meta = super().get_statistic_metadata()
        meta["has_sum"] = True
        meta["has_mean"] = True

        return meta

    async def async_calculate_statistic_data(
        self, hist_states: list[HistoricalState], *, latest: dict | None = None
    ) -> list[StatisticData]:
        #
        # Group historical states by hour
        # Calculate sum, mean, etc...
        #

        accumulated = latest["sum"] if latest else 0

        def hour_block_for_hist_state(hist_state: HistoricalState) -> datetime:
            # XX:00:00 states belongs to previous hour block
            if hist_state.dt.minute == 0 and hist_state.dt.second == 0:
                dt = hist_state.dt - timedelta(hours=1)
                return dt.replace(minute=0, second=0, microsecond=0)

            else:
                return hist_state.dt.replace(minute=0, second=0, microsecond=0)

        ret = []
        for dt, collection_it in itertools.groupby(
            hist_states, key=hour_block_for_hist_state
        ):
            collection = list(collection_it)
            mean = statistics.mean([x.state for x in collection])
            partial_sum = sum([x.state for x in collection])
            accumulated = accumulated + partial_sum

            ret.append(
                StatisticData(
                    start=dt,
                    state=partial_sum,
                    mean=mean,
                    sum=accumulated,
                )
            )

        return ret

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

    @property
    def statistic_id(self) -> str:
        return self.entity_id

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
            start_index = config[CONF_START_INDEX_BASE]
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
                    self._state = float(base_state.state) - float(start_index) - \
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

        elif self._unique_id == CONF_INDEX_OUT_BATTERY_ENERGY:
            base_entity_id = config[CONF_INDEX_BASE_SENSOR]
            capacity_entity_id = "sensor.capacity_battery"
            base_state = self.hass.states.get(base_entity_id)
            capacity_state = self.hass.states.get(capacity_entity_id)

            # Initialisation des variables persistantes
            if not hasattr(self, "_last_base_value") or self._last_base_value is None:
                self._last_base_value = None
            if not hasattr(self, "_state") or self._state is None:
                self._state = 0.0

            if (
                base_state and base_state.state not in (
                    None, "unknown", "unavailable")
                and capacity_state and capacity_state.state not in (None, "unknown", "unavailable")
            ):
                try:
                    capacity = float(capacity_state.state)
                    base_value = float(base_state.state)
                    if self._last_base_value is None:
                        self._last_base_value = base_value
                    if capacity > 0:
                        delta = base_value - self._last_base_value
                        if delta > 0:
                            self._state += delta
                    # Si capacity <= 0, self._state ne change pas
                    self._last_base_value = base_value
                except ValueError:
                    pass

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
