"""The climate entity: state mapping and the write path."""

from __future__ import annotations

import pytest
from homeassistant.components.climate import (
    ATTR_CURRENT_HUMIDITY,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODES,
    ATTR_SWING_HORIZONTAL_MODE,
    ATTR_SWING_MODE,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_SWING_HORIZONTAL_MODE,
    SERVICE_SET_SWING_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import FakeClient

ENTITY = "climate.bedroom_ac"


async def test_state_from_the_captured_frame(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == HVACMode.COOL
    # Reported in Fahrenheit, which is what the device says tempunit is. Home
    # Assistant's default display unit is Celsius, so these come back converted —
    # proof the unit is being taken from the device rather than assumed.
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == pytest.approx(25.0, abs=0.1)
    assert state.attributes[ATTR_TEMPERATURE] == pytest.approx(19.4, abs=0.1)
    assert state.attributes[ATTR_CURRENT_HUMIDITY] == 90
    assert state.attributes[ATTR_FAN_MODE] == "low"
    assert state.attributes[ATTR_SWING_MODE] == "off"
    assert state.attributes[ATTR_SWING_HORIZONTAL_MODE] == "off"


async def test_capabilities_drive_the_offered_options(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_HVAC_MODES] == [
        HVACMode.OFF,
        HVACMode.COOL,
        HVACMode.DRY,
        HVACMode.FAN_ONLY,
    ]
    # windlevel 0 is the silent speed sleep selects, not off. It has to be listed or
    # Home Assistant logs an error the moment sleep mode reports it.
    assert state.attributes[ATTR_FAN_MODES] == [
        "silent",
        "low",
        "medium",
        "high",
        "turbo",
    ]


async def test_set_temperature_sends_device_units(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """20 °C in the UI must leave as 68 on the wire, because the device speaks °F."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 20},
        blocking=True,
    )
    assert fake_client.broker.commands == [{"templevel": 68}]


async def test_write_is_optimistic(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The entity updates without waiting for the device to acknowledge."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "turbo"},
        blocking=True,
    )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_FAN_MODE] == "turbo"


async def test_turning_off_only_sends_power(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Partial payloads are accepted, so nothing is padded in."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: ENTITY},
        blocking=True,
    )
    assert fake_client.broker.commands == [{"poweron": False}]
    assert hass.states.get(ENTITY).state == HVACMode.OFF


async def test_selecting_a_mode_powers_on_first(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: ENTITY},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY, "hvac_mode": HVACMode.DRY},
        blocking=True,
    )
    assert fake_client.broker.commands == [
        {"poweron": False},
        {"poweron": True},
        {"mode": 2},
    ]


async def test_swing_axes_are_separate(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """The horizontal axis is oscset2. Shipped transposed once, so pin it down."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_HORIZONTAL_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_HORIZONTAL_MODE: "on"},
        blocking=True,
    )
    assert fake_client.broker.commands == [{"oscset2": True}]


async def test_humidity_setpoint_is_refused_while_cooling(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """The device would silently ignore rhlevel in cool mode; say so instead."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate",
            "set_humidity",
            {ATTR_ENTITY_ID: ENTITY, "humidity": 55},
            blocking=True,
        )
    assert fake_client.broker.commands == []


async def test_turning_on_and_off_through_hvac_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """turn_on, and OFF via set_hvac_mode, are separate paths to the same command."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY, "hvac_mode": HVACMode.OFF},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True
    )
    assert fake_client.broker.commands == [{"poweron": False}, {"poweron": True}]


async def test_vertical_swing_is_its_own_command(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_SWING_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_SWING_MODE: "on"},
        blocking=True,
    )
    assert fake_client.broker.commands == [{"oscset1": True}]


async def test_humidity_setpoint_is_sent_in_dry_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: ENTITY, "hvac_mode": HVACMode.DRY},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        "set_humidity",
        {ATTR_ENTITY_ID: ENTITY, "humidity": 55},
        blocking=True,
    )
    assert fake_client.broker.commands[-1] == {"rhlevel": 55}


async def test_set_temperature_without_a_temperature_does_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """A call carrying only a target range has nothing this device can act on."""
    entity = hass.data["entity_components"][CLIMATE_DOMAIN].get_entity(ENTITY)
    await entity.async_set_temperature()
    assert fake_client.broker.commands == []


async def test_an_unreported_mode_and_unit_degrade_quietly(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    """A frame with no power, mode or unit must not raise or invent a default."""
    fake_client.broker.state_frame = {"temperature": 77, "rh": 50}
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    # Falls back to the device family's unit rather than guessing the user's.
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == pytest.approx(25.0, abs=0.1)
