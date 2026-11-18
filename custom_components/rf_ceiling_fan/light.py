"""Light entity: the fan's light as an assumed-state on/off toggle.

The remote's light key is a single toggle (one code flips the light on or
off), so there's no separate on/off command and the state is assumed. The
assumption is held in the hub (shared with the light-sync switch) so the two
always agree. The bridge hearing that key - from the real remote - flips the
state to match, which keeps the assumption honest in practice; when it drifts
(unknown state after a restart, or the light changed out of band), the
light-sync switch corrects it without sending a command.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import async_send, get_hub
from .const import CONF_COMMANDS, signal_light, signal_remote
from .entity import RFCeilingFanEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if "light" in entry.data[CONF_COMMANDS]:
        async_add_entities([RFCeilingFanLight(entry)])


class RFCeilingFanLight(RFCeilingFanEntity, LightEntity, RestoreEntity):
    """The fan's light. One toggle code, so on/off is assumed."""

    _attr_translation_key = "light"
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, entry: ConfigEntry) -> None:
        super().__init__(entry, "light")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        hub = get_hub(self.hass)
        # Seed the shared assumed state from what we last knew.
        last = await self.async_get_last_state()
        hub.light_state[self._entry.entry_id] = (
            last is not None and last.state == STATE_ON
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_light(self._entry.entry_id), self.async_write_ha_state
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_remote(self._entry.entry_id), self._remote_pressed
            )
        )

    @callback
    def _remote_pressed(self, command: str) -> None:
        # The light key is a toggle, so a press flips the light.
        if command == "light":
            get_hub(self.hass).toggle_light(self._entry.entry_id)

    @property
    def is_on(self) -> bool:
        return get_hub(self.hass).light_state.get(self._entry.entry_id, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.is_on:
            async_send(self.hass, self._entry, "light")
            get_hub(self.hass).set_light(self._entry.entry_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            async_send(self.hass, self._entry, "light")
            get_hub(self.hass).set_light(self._entry.entry_id, False)
