"""Keeping the device set in step with the account, without trusting one bad answer."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pyzafro import ZafroConnectionError

from custom_components.zafro import async_remove_config_entry_device
from custom_components.zafro.const import DISCOVERY_INTERVAL, DOMAIN, REMOVAL_GRACE

from .conftest import RAW_DEVICE, FakeClient

SECOND_SN = "6ISEComboWF020BSJ0000000001"


async def _scan(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Let one discovery interval elapse."""
    freezer.tick(DISCOVERY_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _scan_past_grace(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Scan repeatedly until any mark laid down now would have expired."""
    elapsed = timedelta()
    while elapsed <= REMOVAL_GRACE:
        await _scan(hass, freezer)
        elapsed += DISCOVERY_INTERVAL


def _device_count(hass: HomeAssistant, entry: MockConfigEntry) -> int:
    return len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id))


async def test_a_device_added_in_the_app_appears_without_a_reload(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    assert _device_count(hass, init_integration) == 1

    fake_client.add_to_account(SECOND_SN, "Office AC")
    await _scan(hass, freezer)

    assert _device_count(hass, init_integration) == 2
    assert hass.states.get("climate.office_ac") is not None
    # And it is furnished like any other device, not just registered.
    assert hass.states.get("switch.office_ac_eco_mode") is not None


async def test_a_failed_enumeration_removes_nothing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    """The cloud being unreachable is not evidence about what the account contains."""
    fake_client.enumerate_error = ZafroConnectionError("no route to host")
    await _scan_past_grace(hass, freezer)

    assert _device_count(hass, init_integration) == 1
    assert hass.states.get("climate.bedroom_ac") is not None


async def test_a_brief_absence_removes_nothing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    """One short listing is the failure mode the grace period exists for."""
    fake_client.listing = []
    await _scan(hass, freezer)
    assert _device_count(hass, init_integration) == 1

    fake_client.listing = [RAW_DEVICE["sn"]]
    await _scan_past_grace(hass, freezer)

    assert _device_count(hass, init_integration) == 1
    assert hass.states.get("climate.bedroom_ac") is not None


async def test_a_sustained_absence_removes_the_device(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    fake_client.add_to_account(SECOND_SN, "Office AC")
    await _scan(hass, freezer)
    assert _device_count(hass, init_integration) == 2

    fake_client.listing.remove(SECOND_SN)
    await _scan_past_grace(hass, freezer)

    assert _device_count(hass, init_integration) == 1
    assert hass.states.get("climate.office_ac") is None
    assert hass.states.get("switch.office_ac_eco_mode") is None
    # The one that stayed is untouched.
    assert hass.states.get("climate.bedroom_ac") is not None
    # And the library was told to stop tracking it.
    assert SECOND_SN not in fake_client.tracked


async def test_an_empty_account_is_not_a_special_case(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    """An empty listing can be true. It is believed on the same terms as any absence."""
    fake_client.listing = []
    await _scan_past_grace(hass, freezer)

    assert _device_count(hass, init_integration) == 0
    assert hass.states.get("climate.bedroom_ac") is None


async def test_a_removed_device_that_comes_back_is_the_same_device(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    """The registry tombstone should restore the entity_id, not allocate a new one."""
    fake_client.listing = []
    await _scan_past_grace(hass, freezer)
    assert hass.states.get("climate.bedroom_ac") is None

    fake_client.listing = [RAW_DEVICE["sn"]]
    await _scan(hass, freezer)

    assert hass.states.get("climate.bedroom_ac") is not None
    assert _device_count(hass, init_integration) == 1


async def test_a_device_that_does_not_answer_is_retried_not_added(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
    fake_client: FakeClient,
) -> None:
    """A new unit that is offline must not half-register, and must not be forgotten."""
    fake_client.add_to_account(SECOND_SN, "Office AC")
    fake_client.broker.offline.add(SECOND_SN)
    await _scan(hass, freezer)
    assert _device_count(hass, init_integration) == 1

    fake_client.broker.offline.clear()
    await _scan(hass, freezer)
    assert _device_count(hass, init_integration) == 2


@pytest.mark.parametrize(
    ("sn", "removable"),
    [(RAW_DEVICE["sn"], False), ("6ISEComboWF020BSJ0000009999", True)],
)
async def test_manual_removal_is_refused_while_the_account_still_lists_it(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    sn: str,
    removable: bool,
) -> None:
    """Deleting a live device by hand would only have it re-added on the next scan."""
    device = dr.DeviceEntry(
        config_entry_id=init_integration.entry_id, identifiers={(DOMAIN, sn)}
    )
    result = await async_remove_config_entry_device(hass, init_integration, device)
    assert result is removable
