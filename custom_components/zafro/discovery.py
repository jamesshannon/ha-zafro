"""Keeping the device set in step with the account.

Devices are added and removed in the vendor's app, not here, so the only way to learn
about either is to re-enumerate. Adding is uncontroversial. Removing is not: a single
short listing is indistinguishable from a real removal, and acting on one would strip
a user's entities off their dashboard because a cloud API had a bad minute.

So removal is deliberately slow and deliberately narrow:

* An enumeration that *raises* is ignored outright — no marks, no removals.
* An enumeration that succeeds marks every known device it did not mention, and
  clears the mark on every device it did.
* A device stays marked for REMOVAL_GRACE before anything happens to it.

An empty-but-successful listing is not special-cased. "I removed every device" and
"the API returned nothing" look identical in one response and are told apart by the
same thing that tells any other absence apart: whether it persists.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from pyzafro import ZafroError

from .const import DISCOVERY_INTERVAL, DOMAIN, REMOVAL_GRACE
from .coordinator import ZafroCoordinator

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from pyzafro import ZafroDevice

    from . import ZafroConfigEntry

_LOGGER = logging.getLogger(__name__)


class ZafroDiscovery:
    """Re-enumerates the account and reconciles the result against what is set up."""

    def __init__(self, hass: HomeAssistant, entry: ZafroConfigEntry) -> None:
        """Bind to one config entry."""
        self.hass = hass
        self.entry = entry
        #: sn -> when it was first missed. In memory only: a reload re-enumerates from
        #: scratch, and the worst a lost mark costs is one more grace period.
        self._missing_since: dict[str, datetime] = {}

    @callback
    def async_start(self) -> None:
        """Begin periodic enumeration, stopping when the entry unloads."""
        self.entry.async_on_unload(
            async_track_time_interval(
                self.hass, self._async_scan, DISCOVERY_INTERVAL, cancel_on_shutdown=True
            )
        )

    async def _async_scan(self, now: datetime) -> None:
        """Enumerate once and reconcile, or do nothing at all."""
        client = self.entry.runtime_data.client
        try:
            devices = await client.async_get_devices()
        except ZafroError as err:
            # Explicitly not a reason to mark anything missing. Authentication failures
            # reach the reauth flow through the listener, which owns that decision.
            _LOGGER.debug("Enumeration failed; leaving the device set alone: %s", err)
            return

        await self._async_add(devices)
        await self._async_expire({device.sn for device in devices}, now)

    async def _async_add(self, devices: list[ZafroDevice]) -> None:
        """Set up coordinators for devices that are new to this entry."""
        coordinators = self.entry.runtime_data.coordinators
        added: list[ZafroCoordinator] = []

        for device in devices:
            if device.sn in coordinators:
                continue
            coordinator = ZafroCoordinator(self.hass, self.entry, device)
            # Not async_config_entry_first_refresh: that is only legal while the entry
            # is setting up, and it turns a failure into ConfigEntryNotReady, which
            # would tear down every working device over one unreachable new one.
            await coordinator.async_refresh()
            if not coordinator.last_update_success:
                _LOGGER.debug(
                    "New device %s did not answer; retrying next scan", device.name
                )
                await coordinator.async_shutdown()
                continue
            coordinators[device.sn] = coordinator
            added.append(coordinator)
            _LOGGER.info("Discovered new Zafro device: %s", device.name)

        if not added:
            return
        for add_entities in self.entry.runtime_data.new_device_callbacks:
            add_entities(added)

    async def _async_expire(self, present: set[str], now: datetime) -> None:
        """Mark absences, and act on the ones that have lasted."""
        coordinators = self.entry.runtime_data.coordinators

        for sn in list(coordinators):
            if sn in present:
                self._missing_since.pop(sn, None)
                continue

            first_missed = self._missing_since.setdefault(sn, now)
            if now - first_missed < REMOVAL_GRACE:
                _LOGGER.debug("%s absent since %s; waiting", sn, first_missed)
                continue

            await self._async_remove(sn)

        # Marks for devices this entry no longer tracks are just clutter.
        for sn in list(self._missing_since):
            if sn not in coordinators:
                del self._missing_since[sn]

    async def _async_remove(self, sn: str) -> None:
        """Drop a device that has been gone long enough to believe.

        Removing the device registry entry is the whole teardown: Home Assistant
        removes its entities from the registry in response, and each entity object
        removes itself in response to that.
        """
        coordinator = self.entry.runtime_data.coordinators.pop(sn)
        _LOGGER.info("Removing %s; gone from the account", coordinator.device.name)

        await coordinator.async_shutdown()
        await self.entry.runtime_data.client.async_forget(sn)

        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, sn), self.entry.entry_id
        )
        if device is not None:
            registry.async_remove_device(device.id)
