"""Switch platform: the booleans that are not part of the climate model.

Sleep and eco have separate buttons in the app and can be on at the same time, so they
cannot be climate presets — presets are mutually exclusive and would have to
misrepresent one of the two states.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from pyzafro import SwitchKey

from .entity import ZafroEntity, async_call

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from pyzafro import ZafroDevice

    from . import ZafroConfigEntry
    from .coordinator import ZafroCoordinator

PARALLEL_UPDATES = 0


class SetSwitch(Protocol):
    """Calls the library setter for one switch."""

    def __call__(self, device: ZafroDevice, *, on: bool) -> Coroutine[Any, Any, None]:
        """Return the coroutine that applies `on` to `device`."""


@dataclass(frozen=True, kw_only=True)
class ZafroSwitchEntityDescription(SwitchEntityDescription):
    """Describes a Zafro switch."""

    value_fn: Callable[[ZafroDevice], bool | None]
    set_fn: SetSwitch


SWITCHES: tuple[ZafroSwitchEntityDescription, ...] = (
    # The device rewrites other fields when these change — sleep moves the fan speed
    # and mutes the beeper, eco moves the setpoint. Those arrive as their own pushes
    # and are never assumed here.
    ZafroSwitchEntityDescription(
        key=SwitchKey.SLEEP,
        value_fn=lambda device: device.state.sleep,
        set_fn=lambda device, *, on: device.async_set_sleep(on=on),
    ),
    ZafroSwitchEntityDescription(
        key=SwitchKey.ECO,
        value_fn=lambda device: device.state.eco,
        set_fn=lambda device, *, on: device.async_set_eco(on=on),
    ),
    ZafroSwitchEntityDescription(
        key=SwitchKey.CHILD_LOCK,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda device: device.state.child_lock,
        set_fn=lambda device, *, on: device.async_set_child_lock(on=on),
    ),
    ZafroSwitchEntityDescription(
        key=SwitchKey.DISPLAY,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda device: device.state.display,
        set_fn=lambda device, *, on: device.async_set_display(on=on),
    ),
    ZafroSwitchEntityDescription(
        key=SwitchKey.MUTE,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda device: device.state.mute,
        set_fn=lambda device, *, on: device.async_set_mute(on=on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZafroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the switches each device's capabilities claim."""
    async_add_entities(
        ZafroSwitch(coordinator, description)
        for coordinator in entry.runtime_data.coordinators.values()
        for description in SWITCHES
        if description.key in coordinator.device.capabilities.switches
    )


class ZafroSwitch(ZafroEntity, SwitchEntity):
    """A toggle on a Zafro device."""

    entity_description: ZafroSwitchEntityDescription

    def __init__(
        self,
        coordinator: ZafroCoordinator,
        description: ZafroSwitchEntityDescription,
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the feature on."""
        await async_call(self.entity_description.set_fn(self.device, on=True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the feature off."""
        await async_call(self.entity_description.set_fn(self.device, on=False))
