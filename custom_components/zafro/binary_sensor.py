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


def _reached_target(device: ZafroDevice) -> bool | None:
    """Return the thermostat's verdict, or nothing at all while the unit is off.

    The device does not answer the comparison while it is off: it reports 0. Measured
    across four power transitions in two conformance runs with the setpoint and the
    ambient reading identical either side — satisfied running, not satisfied off, pushed
    as a delta within 0.55s of each power command.

    Reported raw, that is indistinguishable from "running and still working towards the
    target", so an automation on the negative would fire every time the air conditioner
    is idle. Unknown is the honest answer, and `pyzafro`'s selftest asserts the device
    really does withhold it so this cannot quietly become a lie.
    """
    state = device.state
    return None if state.power is False else state.reached_target


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
        value_fn=_reached_target,
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
