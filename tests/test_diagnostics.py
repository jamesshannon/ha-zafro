"""Diagnostics must be safe to paste into a public issue."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeClient

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


async def test_diagnostics_carry_whatever_the_device_did_that_we_did_not_expect(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """The dump is the whole point of tracking anomalies: no debug logging needed."""
    fake_client.device.handle_frame(4, {"ionizer": True, "mode": 99, "windlevel": 9})
    await hass.async_block_till_done()

    data = await async_get_config_entry_diagnostics(hass, init_integration)
    anomalies = data["client"]["devices"][0]["anomalies"]
    assert anomalies["unknown_keys"] == {"ionizer": True}
    assert anomalies["unreadable_keys"] == {"mode": 99}
    assert anomalies["outside_capabilities"] == ["fan_speed=9"]
