"""Fixtures.

The library is not mocked out. A real ZafroDevice runs against a fake broker, so the
capability gating, the wire translation and the optimistic write path are all exercised
for real and only the network is replaced.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pyzafro import ZafroDevice

from custom_components.zafro.const import CONF_CLIENT_ID, DOMAIN

#: A real /device/list entry, flattened out of its room grouping.
RAW_DEVICE: dict[str, Any] = {
    "sn": "6ISEComboWF020BSJ0000000000",
    "vendor": "I4SEASON",
    "model": "90038EAC0-12K-ZAZ",
    "name": "Bedroom AC",
    "mac": "001cc2000000",
    "version": "1.0.9",
    "mcu_version": "1.0.3",
    "room": "Bedroom",
    "room_id": 42,
}

#: A real cmd:3 reply from that device.
STATE_FRAME: dict[str, Any] = {
    "poweron": True,
    "mode": 1,
    "templevel": 67,
    "temperature": 77,
    "tempunit": 1,
    "rh": 90,
    "rhlevel": 50,
    "windlevel": 1,
    "worktime": 2,
    "filterthr": 600,
    "waterlevel": 0,
    "reachtarget": 0,
    "wrong": 0,
    "origin": 0,
    "childlockon": False,
    "eco": False,
    "extra": False,
    "lighton": True,
    "muteon": False,
    "oscset1": False,
    "oscset2": False,
    "sleep": False,
    "timeron": {"du": 0, "ts": 182},
    "timeroff": {"du": 0, "ts": 182},
}

#: A real cmd:5 reply.
BASE_INFO_FRAME: dict[str, Any] = {
    "v": "I4SEASON",
    "p": "90038EAC0-12K-ZAZ",
    "ver": "1.0.9",
    "mp": "1.0.3",
    "ssid": "homewifi",
    "rssi": 44,
}


class FakeBroker:
    """Stands in for ZafroMqtt.

    Answers cmd:3 and cmd:5 immediately, the way the real broker does. Control frames
    get no synchronous answer, also like the real broker: the acknowledgement arrives
    later as an ordinary push, which is exactly what the optimistic write path is for.
    """

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []
        self._devices: dict[str, ZafroDevice] = {}

    def register(self, device: ZafroDevice) -> None:
        self._devices[device.sn] = device

    async def publish(self, vendor: str, sn: str, payload: dict[str, Any]) -> None:
        self.published.append(payload)
        device = self._devices[sn]
        if payload["cmd"] == 3:
            device.handle_frame(3, dict(STATE_FRAME))
        elif payload["cmd"] == 5:
            device.handle_frame(5, dict(BASE_INFO_FRAME))

    @property
    def commands(self) -> list[dict[str, Any]]:
        """Just the control frames' state payloads."""
        return [p["data"]["state"] for p in self.published if p["cmd"] == 6]


class FakeClient:
    """Stands in for ZafroClient. Same surface, no sockets."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.broker = FakeBroker()
        self.device = ZafroDevice(RAW_DEVICE, self.broker)  # type: ignore[arg-type]
        self.broker.register(self.device)
        self.authenticate_error: Exception | None = None
        self.listen_error: Exception | None = None

    async def async_authenticate(self) -> None:
        if self.authenticate_error is not None:
            raise self.authenticate_error

    async def async_get_devices(self) -> list[ZafroDevice]:
        return [self.device]

    async def async_wait_connected(self, timeout: float = 30.0) -> None:
        return

    async def listen(self) -> None:
        if self.listen_error is not None:
            raise self.listen_error

    def close(self) -> None:
        self.device.close()

    def diagnostics(self) -> dict[str, Any]:
        return {"connected": True, "devices": [self.device.diagnostics()]}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Load the integration from custom_components."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A configured Zafro account."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        unique_id="user@example.com",
        data={
            CONF_EMAIL: "user@example.com",
            CONF_PASSWORD: "hunter2",
            CONF_CLIENT_ID: "ha-0123456789ab",
        },
    )


@pytest.fixture
def fake_client() -> Generator[FakeClient]:
    """Patch ZafroClient everywhere the integration constructs one."""
    client = FakeClient()
    with (
        patch("custom_components.zafro.ZafroClient", return_value=client),
        patch("custom_components.zafro.config_flow.ZafroClient", return_value=client),
    ):
        yield client


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, fake_client: FakeClient
) -> MockConfigEntry:
    """Set the integration up and return its entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
