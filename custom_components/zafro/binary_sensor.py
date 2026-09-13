"""Binary sensor platform: booleans the device reports but does not accept."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from pyzafro import BinarySensorKey

from .entity import ZafroEntity, async_setup_device_entities

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from pyzafro import ZafroDevice

    from . import ZafroConfigEntry
    from .coordinator import ZafroCoordinator

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZafroBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes a Zafro binary sensor."""

    value_fn: Callable[[ZafroDevice], bool | None]


def _problem(device: ZafroDevice) -> bool | None:
    code = device.state.fault_code
    return None if code is None else code != 0


BINARY_SENSORS: tuple[ZafroBinarySensorEntityDescription, ...] = (
    ZafroBinarySensorEntityDescription(
        key=BinarySensorKey.PROBLEM,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_problem,
    ),
    # Disabled by default: it duplicates what the climate entity already implies by
    # showing the setpoint next to the ambient reading.
    ZafroBinarySensorEntityDescription(
        key=BinarySensorKey.REACHED_TARGET,
        entity_registry_enabled_default=False,
        value_fn=lambda device: device.state.reached_target,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZafroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors each device's capabilities claim."""
    async_setup_device_entities(
        entry,
        async_add_entities,
        lambda coordinator: [
            ZafroBinarySensor(coordinator, description)
            for description in BINARY_SENSORS
            if description.key in coordinator.device.capabilities.binary_sensors
        ],
    )


class ZafroBinarySensor(ZafroEntity, BinarySensorEntity):
    """A boolean reported by a Zafro device."""

    entity_description: ZafroBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ZafroCoordinator,
        description: ZafroBinarySensorEntityDescription,
    ) -> None:
        """Bind the description to a device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_translation_key = description.key
        self._attr_unique_id = f"{self.device.sn}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Current value."""
        return self.entity_description.value_fn(self.device)
