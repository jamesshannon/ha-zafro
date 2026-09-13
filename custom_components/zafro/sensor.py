"""Sensor platform.

Everything here is disabled by default. Ambient temperature and humidity are already
attributes of the climate entity, so a separate entity is a duplicate that only some
people want for long-term statistics; the rest are diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from pyzafro import SensorKey

from .climate import UNIT_TO_HA
from .entity import ZafroEntity

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from homeassistant.helpers.typing import StateType
    from pyzafro import ZafroDevice

    from . import ZafroConfigEntry
    from .coordinator import ZafroCoordinator

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZafroSensorEntityDescription(SensorEntityDescription):
    """Describes a Zafro sensor."""

    value_fn: Callable[[ZafroDevice], StateType]
    #: Set when the unit is a property of the device rather than of the measurement.
    unit_fn: Callable[[ZafroDevice], str | None] | None = None


SENSORS: tuple[ZafroSensorEntityDescription, ...] = (
    ZafroSensorEntityDescription(
        key=SensorKey.AMBIENT_TEMPERATURE,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device.state.ambient_temperature,
        unit_fn=lambda device: (
            None
            if device.state.temperature_unit is None
            else UNIT_TO_HA[device.state.temperature_unit]
        ),
    ),
    ZafroSensorEntityDescription(
        key=SensorKey.AMBIENT_HUMIDITY,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda device: device.state.ambient_humidity,
    ),
    # No device class: the one value ever observed was 44, which is not a dBm figure,
    # so the scale is unknown. Surfacing the raw number is honest; claiming
    # SIGNAL_STRENGTH would render it as "44 dBm", which would be wrong.
    ZafroSensorEntityDescription(
        key=SensorKey.RSSI,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.base_info.rssi if device.base_info else None,
    ),
    ZafroSensorEntityDescription(
        key=SensorKey.WORK_TIME,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.state.work_time,
    ),
    ZafroSensorEntityDescription(
        key=SensorKey.FILTER_HOURS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.state.filter_hours,
    ),
    # Scale unknown; only 0 has been observed. Raw number, no unit.
    ZafroSensorEntityDescription(
        key=SensorKey.WATER_LEVEL,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.state.water_level,
    ),
    # The non-zero fault vocabulary is undocumented and only 0 has been seen. Shipping
    # the raw code means the first person to hit a real fault can report the number.
    ZafroSensorEntityDescription(
        key=SensorKey.FAULT_CODE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device.state.fault_code,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZafroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors each device's capabilities claim."""
    async_add_entities(
        ZafroSensor(coordinator, description)
        for coordinator in entry.runtime_data.coordinators.values()
        for description in SENSORS
        if description.key in coordinator.device.capabilities.sensors
    )


class ZafroSensor(ZafroEntity, SensorEntity):
    """A single reading from a Zafro device."""

    entity_description: ZafroSensorEntityDescription
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: ZafroCoordinator,
        description: ZafroSensorEntityDescription,
    ) -> None:
        """Bind the description to a device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{self.device.sn}-{description.key}"

    @property
    def native_value(self) -> StateType:
        """Current reading."""
        return self.entity_description.value_fn(self.device)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Unit, asking the device when the unit is a device property."""
        if (unit_fn := self.entity_description.unit_fn) is not None:
            return unit_fn(self.device)
        return super().native_unit_of_measurement
