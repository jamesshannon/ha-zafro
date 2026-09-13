"""Config flow: creation, reauth and reconfigure."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pyzafro import ZafroAuthError, ZafroConnectionError

from custom_components.zafro.const import CONF_CLIENT_ID, DOMAIN

from .conftest import FakeClient

CREDENTIALS = {CONF_EMAIL: "User@Example.com", CONF_PASSWORD: "hunter2"}


async def test_user_flow(hass: HomeAssistant, fake_client: FakeClient) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "User@Example.com"
    assert result["data"][CONF_EMAIL] == "User@Example.com"
    # Generated here and never again: two clients sharing an id evict each other.
    assert result["data"][CONF_CLIENT_ID].startswith("ha-")
    assert result["result"].unique_id == "user@example.com"


async def test_invalid_auth_then_recovery(
    hass: HomeAssistant, fake_client: FakeClient
) -> None:
    fake_client.authenticate_error = ZafroAuthError("bad password")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    fake_client.authenticate_error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_cannot_connect(hass: HomeAssistant, fake_client: FakeClient) -> None:
    fake_client.authenticate_error = ZafroConnectionError("timeout")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_account_can_only_be_added_once(
    hass: HomeAssistant, fake_client: FakeClient, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CREDENTIALS
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_keeps_email_and_client_id(
    hass: HomeAssistant, fake_client: FakeClient, mock_config_entry: MockConfigEntry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new-password"
    assert mock_config_entry.data[CONF_EMAIL] == "user@example.com"
    assert mock_config_entry.data[CONF_CLIENT_ID] == "ha-0123456789ab"


async def test_reconfigure_rejects_a_different_account(
    hass: HomeAssistant, fake_client: FakeClient, mock_config_entry: MockConfigEntry
) -> None:
    """Swapping in someone else's account would orphan every entity."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "other@example.com", CONF_PASSWORD: "pw"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "account_mismatch"
