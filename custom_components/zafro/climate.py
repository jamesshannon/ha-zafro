"""Climate platform: the air conditioner itself."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    SWING_HORIZONTAL_OFF,
    SWING_HORIZONTAL_ON,
    SWING_OFF,
    SWING_ON,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from pyzafro import Feature, Mode, TemperatureUnit

from .entity import ZafroEntity, async_call

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import ZafroConfigEntry
    from .coordinator import ZafroCoordinator

#: Writes are non-blocking publishes, so there is nothing to serialise.
PARALLEL_UPDATES = 0

MODE_TO_HVAC: dict[Mode, HVACMode] = {
    Mode.COOL: HVACMode.COOL,
    Mode.DRY: HVACMode.DRY,
    Mode.FAN: HVACMode.FAN_ONLY,
    Mode.HEAT: HVACMode.HEAT,
}
HVAC_TO_MODE = {hvac: mode for mode, hvac in MODE_TO_HVAC.items()}

#: `windlevel` 0 is not off — it is the silent speed that sleep mode selects, with the
#: unit still running. It has to appear here, because Home Assistant logs an error when
#: a device reports a fan mode that is not in `fan_modes`.
SPEED_TO_FAN_MODE: dict[int, str] = {
    0: "silent",
    1: "low",
    2: "medium",
    3: "high",
    4: "turbo",
}
FAN_MODE_TO_SPEED = {name: speed for speed, name in SPEED_TO_FAN_MODE.items()}

UNIT_TO_HA: dict[TemperatureUnit, UnitOfTemperature] = {
    TemperatureUnit.CELSIUS: UnitOfTemperature.CELSIUS,
    TemperatureUnit.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZafroConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a climate entity for each device that is actually a climate device.

    A product this library has never handled — the capability table's fallback assumes
    an air conditioner — narrows itself to nothing once it reports its first state
    frame. Building a thermostat for it would be worse than building nothing; pyzafro
    logs a warning naming the model when that happens.
    """
    async_add_entities(
        ZafroClimate(coordinator)
        for coordinator in entry.runtime_data.coordinators.values()
        if coordinator.device.capabilities.is_climate
    )


class ZafroClimate(ZafroEntity, ClimateEntity):
    """The main entity for a Zafro unit."""

    _attr_name = None
    _attr_translation_key = "zafro"
    _attr_target_temperature_step = 1

    def __init__(self, coordinator: ZafroCoordinator) -> None:
        """Derive the supported feature set from the device's capabilities."""
        super().__init__(coordinator)
        caps = self.device.capabilities
        self._attr_unique_id = self.device.sn

        self._attr_hvac_modes = [HVACMode.OFF] + [
            MODE_TO_HVAC[mode] for mode in sorted(caps.modes) if mode in MODE_TO_HVAC
        ]

        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if caps.target_temperature_range is not None:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if caps.target_humidity_range is not None:
            features |= ClimateEntityFeature.TARGET_HUMIDITY
        if caps.has(Feature.FAN_SPEED) and caps.fan_speeds:
            features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = [
                SPEED_TO_FAN_MODE[speed]
                for speed in caps.fan_speeds
                if speed in SPEED_TO_FAN_MODE
            ]
        if caps.has(Feature.SWING_VERTICAL):
            features |= ClimateEntityFeature.SWING_MODE
            self._attr_swing_modes = [SWING_ON, SWING_OFF]
        if caps.has(Feature.SWING_HORIZONTAL):
            features |= ClimateEntityFeature.SWING_HORIZONTAL_MODE
            self._attr_swing_horizontal_modes = [
                SWING_HORIZONTAL_ON,
                SWING_HORIZONTAL_OFF,
            ]
        self._attr_supported_features = features

        if (temp_range := caps.target_temperature_range) is not None:
            self._attr_min_temp, self._attr_max_temp = temp_range
        if (humidity_range := caps.target_humidity_range) is not None:
            self._attr_min_humidity, self._attr_max_humidity = humidity_range

    # --- reads -----------------------------------------------------------------------

    @property
    def temperature_unit(self) -> UnitOfTemperature:
        """The unit the device reports in, not the unit the user sees.

        Home Assistant converts for display and converts back on the way in, so a
        Fahrenheit unit works untested in a Celsius household and vice versa. The
        capability table's min/max are expressed in this same device unit.
        """
        unit = self.zafro_state.temperature_unit
        if unit is None:
            return UnitOfTemperature.FAHRENHEIT
        return UNIT_TO_HA[unit]

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Off when powered down, otherwise the reported mode."""
        state = self.zafro_state
        if state.power is False:
            return HVACMode.OFF
        if state.power is None or state.mode is None:
            return None
        return MODE_TO_HVAC.get(state.mode)

    @property
    def current_temperature(self) -> float | None:
        """Ambient temperature, in the device's unit."""
        return self.zafro_state.ambient_temperature

    @property
    def target_temperature(self) -> float | None:
        """The setpoint, which only cool and heat modes carry."""
        return self.zafro_state.target_temperature

    @property
    def current_humidity(self) -> float | None:
        """Ambient relative humidity."""
        return self.zafro_state.ambient_humidity

    @property
    def target_humidity(self) -> float | None:
        """The humidity setpoint, which only dry mode carries."""
        return self.zafro_state.target_humidity

    @property
    def fan_mode(self) -> str | None:
        """Fan speed as a named mode."""
        speed = self.zafro_state.fan_speed
        return None if speed is None else SPEED_TO_FAN_MODE.get(speed)

    @property
    def swing_mode(self) -> str | None:
        """Vertical louvre swing."""
        swinging = self.zafro_state.swing_vertical
        return None if swinging is None else (SWING_ON if swinging else SWING_OFF)

    @property
    def swing_horizontal_mode(self) -> str | None:
        """Horizontal louvre swing."""
        swinging = self.zafro_state.swing_horizontal
        if swinging is None:
            return None
        return SWING_HORIZONTAL_ON if swinging else SWING_HORIZONTAL_OFF

    # --- writes ----------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        """Turn the unit on."""
        await async_call(self.device.async_set_power(on=True))

    async def async_turn_off(self) -> None:
        """Turn the unit off."""
        await async_call(self.device.async_set_power(on=False))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Select a mode, powering the unit on first if it is off."""
        if hvac_mode == HVACMode.OFF:
            await async_call(self.device.async_set_power(on=False))
            return
        if self.zafro_state.power is not True:
            await async_call(self.device.async_set_power(on=True))
        await async_call(self.device.async_set_mode(HVAC_TO_MODE[hvac_mode]))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the temperature setpoint.

        The library rejects this outside cool and heat modes, because the device
        would silently ignore the field rather than report an error.
        """
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await async_call(
            self.device.async_set_target_temperature(round(float(temperature)))
        )

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the humidity setpoint. Dry mode only."""
        await async_call(self.device.async_set_target_humidity(humidity))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan speed."""
        await async_call(self.device.async_set_fan_speed(FAN_MODE_TO_SPEED[fan_mode]))

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set vertical swing."""
        await async_call(self.device.async_set_swing(vertical=swing_mode == SWING_ON))

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Set horizontal swing."""
        await async_call(
            self.device.async_set_swing(
                horizontal=swing_horizontal_mode == SWING_HORIZONTAL_ON
            )
        )
