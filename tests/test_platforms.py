"""Sensors, binary sensors and switches."""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeClient


async def test_every_sensor_is_disabled_by_default(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Ambient readings duplicate climate attributes; the rest are diagnostics."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, init_integration.entry_id)
    sensors = [entry for entry in entries if entry.domain == "sensor"]
    assert len(sensors) == 7
    assert all(
        entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION for entry in sensors
    )


async def test_enabled_sensor_reports_the_captured_reading(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    mock_config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "zafro",
        f"{fake_client.device.sn}-ambient_humidity",
        suggested_object_id="bedroom_ac_ambient_humidity",
        disabled_by=None,
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.bedroom_ac_ambient_humidity")
    assert state is not None
    assert state.state == "90"


async def test_problem_sensor_reflects_the_fault_code(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    assert hass.states.get("binary_sensor.bedroom_ac_problem").state == STATE_OFF

    fake_client.device.handle_frame(4, {"wrong": 7})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.bedroom_ac_problem").state == STATE_ON


@pytest.mark.parametrize(
    ("entity_id", "wire_key"),
    [
        ("switch.bedroom_ac_sleep_mode", "sleep"),
        ("switch.bedroom_ac_eco_mode", "eco"),
        ("switch.bedroom_ac_child_lock", "childlockon"),
        ("switch.bedroom_ac_beeper", "muteon"),
    ],
)
async def test_switches_send_only_their_own_field(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    fake_client: FakeClient,
    entity_id: str,
    wire_key: str,
) -> None:
    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert fake_client.broker.commands == [{wire_key: True}]
    assert hass.states.get(entity_id).state == STATE_ON


async def test_sleep_side_effects_are_not_invented(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """The device mutes itself and drops the fan when sleep turns on.

    Home Assistant must not predict that. It shows the commanded field immediately and
    the consequences only once the device reports them.
    """
    await hass.services.async_call(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.bedroom_ac_sleep_mode"},
        blocking=True,
    )
    assert hass.states.get("switch.bedroom_ac_sleep_mode").state == STATE_ON
    assert hass.states.get("switch.bedroom_ac_beeper").state == STATE_OFF
    assert hass.states.get("climate.bedroom_ac").attributes["fan_mode"] == "low"

    fake_client.device.handle_frame(4, {"muteon": True, "windlevel": 0, "origin": 0})
    await hass.async_block_till_done()
    assert hass.states.get("switch.bedroom_ac_beeper").state == STATE_ON
    assert hass.states.get("climate.bedroom_ac").attributes["fan_mode"] == "silent"


async def test_device_going_offline_makes_entities_unavailable(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.device.handle_presence(online=False)
    await hass.async_block_till_done()
    assert hass.states.get("climate.bedroom_ac").state == "unavailable"
    assert hass.states.get("switch.bedroom_ac_eco_mode").state == "unavailable"
