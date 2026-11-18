"""Fan entity: on/off plus whichever speeds were learned."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from . import async_send, get_hub
from .const import CONF_COMMANDS, SPEED_COMMANDS, signal_fan, signal_remote
from .entity import RFCeilingFanEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    commands = entry.data[CONF_COMMANDS]
    speeds = [s for s in SPEED_COMMANDS if s in commands]
    if "off" in commands and speeds:
        async_add_entities([RFCeilingFan(entry, speeds)])


class RFCeilingFan(RFCeilingFanEntity, FanEntity, RestoreEntity):
    """The fan motor."""

    _attr_name = None  # the device name, e.g. "Kitchen"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )

    def __init__(self, entry: ConfigEntry, speeds: list[str]) -> None:
        super().__init__(entry, "fan")
        self._speeds = speeds
        self._attr_speed_count = len(speeds)
        self._attr_is_on = False
        self._attr_percentage = 0
        self._last_speed = speeds[-1]  # used when turned on without a speed
        # A remote with a dedicated power-on key uses it for plain turn-on;
        # otherwise turning on just re-sends the last speed.
        self._has_on = "on" in entry.data[CONF_COMMANDS]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            pct = last.attributes.get("percentage")
            if isinstance(pct, (int, float)) and pct > 0:
                self._last_speed = percentage_to_ordered_list_item(self._speeds, pct)
            if last.state == STATE_ON:
                self._apply(self._last_speed)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_remote(self._entry.entry_id), self._remote_pressed
            )
        )

    @callback
    def _remote_pressed(self, command: str) -> None:
        """The real remote (or a button entity) was used: follow it."""
        if command == "off" or command in self._speeds:
            self._apply(command)
            self.async_write_ha_state()
        elif command == "on":
            # A bare on key carries no speed, so assume the last one used.
            self._apply(self._last_speed)
            self.async_write_ha_state()

    def _apply(self, command: str) -> None:
        if command == "off":
            self._attr_is_on = False
            self._attr_percentage = 0
        else:
            self._last_speed = command
            self._attr_is_on = True
            self._attr_percentage = ordered_list_item_to_percentage(self._speeds, command)
        # Publish the current speed so the per-speed switches can mirror it.
        hub = get_hub(self.hass)
        hub.fan_speed[self._entry.entry_id] = None if command == "off" else command
        async_dispatcher_send(self.hass, signal_fan(self._entry.entry_id))

    async def _do(self, command: str) -> None:
        async_send(self.hass, self._entry, command)
        self._apply(command)
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    async def async_turn_on(
        self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any
    ) -> None:
        if percentage:
            await self.async_set_percentage(percentage)
        elif self._has_on:
            # Send the remote's real power-on key, then assume the last speed.
            async_send(self.hass, self._entry, "on")
            self._apply(self._last_speed)
            self.async_write_ha_state()
        else:
            await self._do(self._last_speed)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._do("off")

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self._do("off")
        else:
            await self._do(percentage_to_ordered_list_item(self._speeds, percentage))
