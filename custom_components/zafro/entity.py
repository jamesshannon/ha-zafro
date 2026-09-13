"""Shared entity base and error translation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pyzafro import ZafroError, ZafroUnsupportedError

from .const import DOMAIN, MANUFACTURER
from .coordinator import ZafroCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Iterable

    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from pyzafro import DeviceState, ZafroDevice

    from . import ZafroConfigEntry


async def async_call(coro: Coroutine[Any, Any, None]) -> None:
    """Await a library call, translating its errors into Home Assistant's.

    ZafroUnsupportedError means the user asked for something this device cannot do —
    a setpoint outside its range, or the humidity target while it is cooling. That is
    a bad request, not a failure, so it must not mark the entity unavailable.
    """
    try:
        await coro
    except ZafroUnsupportedError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unsupported",
            translation_placeholders={"error": str(err)},
        ) from err
    except ZafroError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="communication_error",
            translation_placeholders={"error": str(err)},
        ) from err


@callback
def async_setup_device_entities(
    entry: ZafroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    factory: Callable[[ZafroCoordinator], Iterable[ZafroEntity]],
) -> None:
    """Add a platform's entities for every device, now and whenever one appears.

    `factory` is called once per device and returns whatever that device's
    capabilities justify — often nothing, which is how a product that is not an air
    conditioner ends up with no thermostat. Discovery calls back through the same
    factory later, so a device added in the app is furnished exactly like one that was
    there at setup.
    """

    @callback
    def _async_add(coordinators: list[ZafroCoordinator]) -> None:
        async_add_entities(
            entity for coordinator in coordinators for entity in factory(coordinator)
        )

    entry.runtime_data.new_device_callbacks.append(_async_add)
    _async_add(list(entry.runtime_data.coordinators.values()))


class ZafroEntity(CoordinatorEntity[ZafroCoordinator]):
    """Base for every Zafro entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZafroCoordinator) -> None:
        """Attach to a device and describe it to the registry."""
        super().__init__(coordinator)
        device = coordinator.device
        info = device.base_info

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.sn)},
            manufacturer=MANUFACTURER,
            model=device.model or None,
            name=device.name,
            serial_number=device.sn,
            sw_version=(info.firmware if info else None) or device.firmware or None,
            hw_version=(info.mcu_version if info else None)
            or device.mcu_version
            or None,
            connections=(
                {(CONNECTION_NETWORK_MAC, format_mac(device.mac))}
                if device.mac
                else set()
            ),
        )

    @property
    def device(self) -> ZafroDevice:
        """The library object this entity controls."""
        return self.coordinator.device

    @property
    def zafro_state(self) -> DeviceState:
        """Current device state. Named so it does not shadow Entity.state."""
        return self.coordinator.device.state

    @property
    def available(self) -> bool:
        """Available only while the device itself is reachable.

        `super().available` covers the coordinator; `device.available` is driven by
        the device's LWT topic and by the transport dropping.
        """
        return super().available and self.device.available
