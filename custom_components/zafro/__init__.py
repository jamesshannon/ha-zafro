"""The Zafro integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pyzafro import ZafroAuthError, ZafroClient, ZafroError

from .const import CONF_CLIENT_ID, CONNECT_TIMEOUT
from .coordinator import ZafroCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.SWITCH,
]


@dataclass
class ZafroRuntimeData:
    """Everything the platforms need, hung off the config entry."""

    client: ZafroClient
    coordinators: dict[str, ZafroCoordinator]


type ZafroConfigEntry = ConfigEntry[ZafroRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: ZafroConfigEntry) -> bool:
    """Set up Zafro from a config entry."""
    client = ZafroClient(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        client_id=entry.data[CONF_CLIENT_ID],
    )

    try:
        await client.async_authenticate()
        devices = await client.async_get_devices()
    except ZafroAuthError as err:
        raise ConfigEntryAuthFailed(err) from err
    except ZafroError as err:
        raise ConfigEntryNotReady(err) from err

    # The listener owns the socket and its own reconnect loop; it runs until the entry
    # is unloaded. Started before the first refresh because that refresh is itself an
    # MQTT round trip.
    entry.async_create_background_task(
        hass, _async_listen(hass, entry, client), f"{entry.entry_id} zafro listener"
    )
    try:
        await client.async_wait_connected(CONNECT_TIMEOUT)
    except ZafroError as err:
        raise ConfigEntryNotReady(err) from err

    coordinators = {
        device.sn: ZafroCoordinator(hass, entry, device) for device in devices
    }
    for coordinator in coordinators.values():
        await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(client.close)
    entry.runtime_data = ZafroRuntimeData(client=client, coordinators=coordinators)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZafroConfigEntry) -> bool:
    """Unload a config entry. The background listener is cancelled by Home Assistant."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_listen(
    hass: HomeAssistant, entry: ZafroConfigEntry, client: ZafroClient
) -> None:
    """Run the transport, turning a credential failure into a reauth prompt.

    The library retries transport errors itself and only lets ZafroAuthError escape,
    because bad credentials are the one failure retrying cannot fix. The weekly token
    expiry is refreshed internally and never reaches here.
    """
    try:
        await client.listen()
    except ZafroAuthError as err:
        _LOGGER.warning("Zafro credentials were rejected: %s", err)
        entry.async_start_reauth(hass)
