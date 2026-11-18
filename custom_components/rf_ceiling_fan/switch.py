"""Light-sync switch: corrects HA's assumed light state without sending RF.

The fan's light is a single toggle with no feedback, so HA can only guess its
on/off and may end up inverted (it guesses "on" while the bulb is off). A
toggle can never un-invert itself - every press flips the bulb and the guess
together. This switch is the correction: set it to match what the bulb is
actually doing and the guess realigns, with no command sent to the fan. It
mirrors the light's state and is exposed to voice assistants, so the fix is
one tap (or "turn on/off ... Light Sync") in Home Assistant or Alexa.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_send, get_hub
from .const import CONF_COMMANDS, SPEED_COMMANDS, signal_fan, signal_light, signal_remote
from .entity import RFCeilingFanEntity

SPEED_ICONS = {
    "low": "mdi:fan-speed-1",
    "medium": "mdi:fan-speed-2",
    "high": "mdi:fan-speed-3",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    commands = entry.data[CONF_COMMANDS]
    entities: list[RFCeilingFanEntity] = []
    if "light" in commands:
        entities.append(RFCeilingFanLightSync(entry))
    # A plain on/off switch per learned speed, so voice assistants can set the
    # speed as a simple on/off action (no brightness, which fakes a fan as a
    # dimmable light and makes Alexa announce an error). They behave like radio
    # buttons: turning one on selects that speed; turning one off stops the fan.
    if "off" in commands:
        for speed in SPEED_COMMANDS:
            if speed in commands:
                entities.append(RFCeilingFanSpeedSwitch(entry, speed))
    async_add_entities(entities)


class RFCeilingFanLightSync(RFCeilingFanEntity, SwitchEntity):
    """Sets HA's assumed light state to match reality. Never transmits RF."""

    _attr_translation_key = "light_sync"
    _attr_icon = "mdi:sync"

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "light_sync")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_light(self._entry.entry_id), self.async_write_ha_state
            )
        )

    @property
    def is_on(self) -> bool:
        return get_hub(self.hass).light_state.get(self._entry.entry_id, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Correct the belief to "on" - no command goes to the fan.
        get_hub(self.hass).set_light(self._entry.entry_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        get_hub(self.hass).set_light(self._entry.entry_id, False)


class RFCeilingFanSpeedSwitch(RFCeilingFanEntity, SwitchEntity):
    """One learned speed as a plain on/off switch (radio-button style)."""

    def __init__(self, entry: ConfigEntry, speed: str) -> None:
        super().__init__(entry, f"speed_{speed}")
        self._speed = speed
        self._attr_translation_key = f"speed_{speed}"
        self._attr_icon = SPEED_ICONS.get(speed)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_fan(self._entry.entry_id), self.async_write_ha_state
            )
        )

    @property
    def is_on(self) -> bool:
        return get_hub(self.hass).fan_speed.get(self._entry.entry_id) == self._speed

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Select this speed: send it and let the fan apply it (which updates
        # the fan entity and the shared speed, so the switches stay in step).
        async_send(self.hass, self._entry, self._speed)
        async_dispatcher_send(
            self.hass, signal_remote(self._entry.entry_id), self._speed
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Turning a speed off stops the fan.
        async_send(self.hass, self._entry, "off")
        async_dispatcher_send(self.hass, signal_remote(self._entry.entry_id), "off")
