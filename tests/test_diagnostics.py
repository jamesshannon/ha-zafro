"""Diagnostics must be safe to paste into a public issue."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.zafro.diagnostics import async_get_config_entry_diagnostics

#: Everything a dump must never contain, from the fixtures in conftest.
SECRETS = [
    "6ISEComboWF020BSJ0000000000",
    "001cc2000000",
    "Bedroom",
    "homewifi",
    "hunter2",
    "user@example.com",
]


async def test_diagnostics_leak_nothing_identifying(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    dump = json.dumps(await async_get_config_entry_diagnostics(hass, init_integration))
    for secret in SECRETS:
        assert secret not in dump


async def test_diagnostics_still_say_what_the_model_is(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Redaction is worthless if it removes the thing the issue is about."""
    data = await async_get_config_entry_diagnostics(hass, init_integration)
    device = data["client"]["devices"][0]
    assert device["capabilities"]["normalised_model"] == "90038EAC0-12K-ZAZ"
    assert device["capabilities"]["known_model"] is True
    assert device["state"]["target_temperature"] == 67
