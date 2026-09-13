"""Config flow for Zafro.

One config entry per cloud account. Every device on the account is added; a device the
user does not want is disabled in the UI, which is the convention for cloud accounts and
means a unit bought later appears on its own instead of needing a reconfigure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from pyzafro import ZafroAuthError, ZafroClient, ZafroError

from .const import CONF_CLIENT_ID, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)
STEP_PASSWORD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        )
    }
)


class ZafroConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Zafro."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials for a new account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            errors = await self._async_validate(email, user_input[CONF_PASSWORD])
            if not errors:
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=email,
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        # Generated once, here, and never regenerated: the broker
                        # evicts the older session when two clients share an id.
                        CONF_CLIENT_ID: f"ha-{uuid4().hex[:12]}",
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth when the stored password stops working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password, keeping the email and the client id."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_validate(
                entry.data[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_PASSWORD_SCHEMA,
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user correct the credentials without removing the entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            errors = await self._async_validate(email, user_input[CONF_PASSWORD])
            if not errors:
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_mismatch(reason="account_mismatch")
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, {CONF_EMAIL: entry.data[CONF_EMAIL]}
            ),
            errors=errors,
        )

    async def _async_validate(self, email: str, password: str) -> dict[str, str]:
        """Log in once to check the credentials. Returns form errors, if any."""
        client = ZafroClient(
            async_get_clientsession(self.hass),
            email,
            password,
            # Throwaway: a validation login never opens an MQTT connection, so this
            # id is never used on the wire.
            client_id=f"ha-validate-{uuid4().hex[:8]}",
        )
        try:
            await client.async_authenticate()
        except ZafroAuthError:
            return {"base": "invalid_auth"}
        except ZafroError:
            _LOGGER.debug("Zafro login failed", exc_info=True)
            return {"base": "cannot_connect"}
        return {}
