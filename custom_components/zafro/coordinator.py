"""One push coordinator per device."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pyzafro import DeviceState, ZafroAuthError, ZafroError

from .const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from pyzafro import ZafroDevice

_LOGGER = logging.getLogger(__name__)


class ZafroCoordinator(DataUpdateCoordinator[DeviceState]):
    """Holds one device's state and republishes it when the cloud pushes.

    `update_interval` is None: this is a pure push coordinator. `_async_update_data`
    runs once during setup to establish a baseline, and again only when something
    explicitly asks for a resync.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, device: ZafroDevice
    ) -> None:
        """Bind the coordinator to one device."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.name}",
            update_interval=None,
        )
        self.device = device
        # Subscribing here rather than in _async_setup, which only runs for the
        # coordinators built during setup. A device discovered later gets no first
        # refresh, and would otherwise never be wired to its pushes.
        self._unsubscribe: Callable[[], None] | None = device.subscribe(
            self._handle_push
        )

    async def async_shutdown(self) -> None:
        """Stop listening, then tear the coordinator down.

        Called when the entry unloads and when a device leaves the account, so it has
        to tolerate being called twice.
        """
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        await super().async_shutdown()

    async def _async_update_data(self) -> DeviceState:
        """Establish a state baseline over MQTT.

        Unlike every cloud integration this was modelled on, there is no REST endpoint
        that returns device state — `/device/list` carries none. So the baseline is two
        MQTT round trips: cmd:5 for the identity fields the device registry wants, then
        cmd:3 for the state that subsequent cmd:4 deltas merge into.
        """
        try:
            await self.device.async_refresh_base_info()
            await self.device.async_refresh()
        except ZafroAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except ZafroError as err:
            raise UpdateFailed(err) from err
        return self.device.state

    @callback
    def _handle_push(self, device: ZafroDevice) -> None:
        """Republish state the library has already merged.

        Called for pushes, for presence changes, and for the library's own optimistic
        application of a write — one path, so the entity never has to decide which.
        """
        self.async_set_updated_data(device.state)
