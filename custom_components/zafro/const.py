"""Constants for the Zafro integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "zafro"

#: Brand shown in the device registry. The wire `vendor` is "I4SEASON", the ODM that
#: builds these units; the name on the box, and in the app, is Zafro.
MANUFACTURER: Final = "Zafro"

#: MQTT client identifier, generated once in the config flow and never changed.
#: The broker evicts whichever session connected first when two share an id, so a
#: value derived from the account would make Home Assistant and the phone app fight.
CONF_CLIENT_ID: Final = "client_id"

#: How long to wait for the broker before giving up on setup. The connection is
#: established once per config entry and everything else depends on it.
CONNECT_TIMEOUT: Final = 30.0
