"""Constants for the Zafro integration."""

from __future__ import annotations

from datetime import timedelta
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

#: How often the account is re-enumerated to pick up devices added or removed in the
#: app. The device list is a cheap REST call; state never arrives this way.
DISCOVERY_INTERVAL: Final = timedelta(minutes=5)

#: How long a device must be continuously absent from a *successful* enumeration
#: before its entities are removed. A cloud API that answers 200 with a short list is
#: indistinguishable from a real removal in any single response, so the signal has to
#: persist. Stored as a duration rather than a number of scans so the two can be tuned
#: independently.
REMOVAL_GRACE: Final = timedelta(minutes=15)
