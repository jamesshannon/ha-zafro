"""Setup, teardown and the failure paths."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pyzafro import ZafroAuthError, ZafroConnectionError

from custom_components.zafro.const import DOMAIN

from .conftest import RAW_DEVICE, FakeClient


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_device_registered_with_identity_from_base_info(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    device = registry.async_get_device_by_identifier(
        (DOMAIN, RAW_DEVICE["sn"]), init_integration.entry_id
    )
    assert device is not None
    assert device.manufacturer == "Zafro"
    assert device.model == "90038EAC0-12K-ZAZ"
    assert device.sw_version == "1.0.9"
    assert device.serial_number == RAW_DEVICE["sn"]
    assert (dr.CONNECTION_NETWORK_MAC, "00:1c:c2:00:00:00") in device.connections


async def test_bad_credentials_go_to_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.authenticate_error = ZafroAuthError("nope")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_transport_failure_is_retried(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    fake_client.authenticate_error = ZafroConnectionError("broker down")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_credentials_rejected_while_running_triggers_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_client: FakeClient
) -> None:
    """A password changed elsewhere surfaces from the listener, not from setup."""
    fake_client.listen_error = ZafroAuthError("password changed")
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("climate", 1),
        # Five switches, all enabled.
        ("switch", 5),
        # Seven sensors, every one disabled by default, so none is in the state machine.
        ("sensor", 0),
        # Problem is enabled; reached target is not.
        ("binary_sensor", 1),
    ],
)
async def test_entities_created(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    platform: str,
    expected: int,
) -> None:
    states = [state for state in hass.states.async_all() if state.domain == platform]
    assert len(states) == expected
