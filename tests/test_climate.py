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
    # Every position of the one fan control, slowest first: sleep drops the fan below
    # the slowest selectable speed, the remote's fan button cycles the middle four, and
    # holding it selects EXTRA. windlevel 0 is not a mode of its own because nothing but
    # sleep can reach it.
    assert state.attributes[ATTR_FAN_MODES] == [
        "sleep",
        "low",
        "medium",
        "high",
        "auto",
        "extra",
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
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "auto"},
        blocking=True,
    )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_FAN_MODE] == "auto"


async def test_auto_is_the_top_of_the_speed_range(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """The top speed is the app's AUTO button, shipped as "turbo" by mistake.

    1.1.0 called windlevel 4 "turbo" and had no mode for the real EXTRA function at all.
    """
    fake_client.device.handle_frame(4, {"windlevel": 4, "origin": 0})
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_FAN_MODE] == "auto"


async def test_extra_outranks_the_speed_it_reports(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """A real long press on the remote: {"windlevel": 3, "extra": true}.

    Reading the speed alone would show high, which is what the fan is doing but not
    what it is set to.
    """
    fake_client.device.handle_frame(4, {"windlevel": 3, "extra": True, "origin": 0})
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_FAN_MODE] == "extra"


async def test_extra_is_its_own_command(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """It is a fan mode in Home Assistant and a boolean on the wire."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "extra"},
        blocking=True,
    )

    assert fake_client.broker.commands == [{"extra": True, "sleep": False}]
    assert hass.states.get(ENTITY).attributes[ATTR_FAN_MODE] == "extra"


async def test_a_speed_takes_the_fan_back_out_of_extra(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Asking for low while EXTRA runs means low, so EXTRA leaves with it."""
    fake_client.device.handle_frame(4, {"windlevel": 3, "extra": True, "origin": 0})
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "low"},
        blocking=True,
    )

    assert fake_client.broker.commands == [
        {"windlevel": 1, "extra": False, "sleep": False, "eco": False}
    ]
    assert hass.states.get(ENTITY).attributes[ATTR_FAN_MODE] == "low"


async def test_sleep_is_the_slowest_fan_mode(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """Sleep drops the fan to windlevel 0, which no speed names.

    It used to read as nothing selected, which looks like a control Home Assistant
    cannot display rather than a fan that is running quietly.
    """
    fake_client.device.handle_frame(
        4, {"windlevel": 0, "sleep": True, "muteon": True, "origin": 0}
    )
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_FAN_MODE] == "sleep"


async def test_selecting_sleep_is_the_sleep_command(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """The same boolean the switch writes, and the switch follows it."""
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "sleep"},
        blocking=True,
    )

    assert fake_client.broker.commands == [{"sleep": True, "extra": False}]
    assert hass.states.get(ENTITY).attributes[ATTR_FAN_MODE] == "sleep"
    assert hass.states.get("switch.bedroom_ac_sleep_mode").state == "on"


async def test_a_speed_takes_the_fan_back_out_of_sleep(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """The way out of sleep is the same as the way out of EXTRA."""
    fake_client.device.handle_frame(
        4, {"windlevel": 0, "sleep": True, "muteon": True, "origin": 0}
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: ENTITY, ATTR_FAN_MODE: "high"},
        blocking=True,
    )

    assert fake_client.broker.commands == [
        {"windlevel": 3, "extra": False, "sleep": False, "eco": False}
    ]
    assert hass.states.get(ENTITY).attributes[ATTR_FAN_MODE] == "high"


async def test_an_unexplained_speed_reads_as_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry, fake_client: FakeClient
) -> None:
    """A speed of 0 without sleep is a state nothing here can account for.

    It has never been seen. Naming it would be inventing a mode; leaving the control
    unset says as much as is actually known.
    """
    fake_client.device.handle_frame(4, {"windlevel": 0, "origin": 0})
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.attributes[ATTR_FAN_MODE] is None


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
