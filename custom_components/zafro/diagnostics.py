"""Diagnostics support for Zafro."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import ZafroConfigEntry

TO_REDACT = {CONF_EMAIL, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZafroConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    The device payload comes from the library, which already drops the serial, MAC,
    SSID and every user-chosen name, so this dump can be pasted into a public issue
    to get an unrecognised model added to the capability table.
    """
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "client": entry.runtime_data.client.diagnostics(),
    }
