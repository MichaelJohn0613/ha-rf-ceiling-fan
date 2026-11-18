"""One button per learned remote key, standard or custom."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_send
from .const import COMMANDS, CONF_COMMANDS, CONF_LABELS, CUSTOM_PREFIX, signal_remote
from .entity import RFCeilingFanEntity

ICONS = {
    "off": "mdi:fan-off",
    "on": "mdi:fan",
    "low": "mdi:fan-speed-1",
    "medium": "mdi:fan-speed-2",
    "high": "mdi:fan-speed-3",
    "light": "mdi:ceiling-fan-light",
    "dim": "mdi:brightness-6",
    "reverse": "mdi:rotate-3d-variant",
}
CUSTOM_ICON = "mdi:remote"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    learned = entry.data[CONF_COMMANDS]
    labels = entry.data.get(CONF_LABELS, {})
    entities: list[RFRemoteButton] = []
    # Standard keys first, in their canonical order, then any custom buttons.
    # "light" is exposed as a light entity instead of a button.
    for command in COMMANDS:
        if command in learned and command != "light":
            entities.append(RFRemoteButton(entry, command))
    for command in learned:
        if command.startswith(CUSTOM_PREFIX):
            entities.append(RFRemoteButton(entry, command, labels.get(command)))
    async_add_entities(entities)


class RFRemoteButton(RFCeilingFanEntity, ButtonEntity):
    """Sends exactly what the matching remote key sends."""

    def __init__(
        self, entry: ConfigEntry, command: str, label: str | None = None
    ) -> None:
        super().__init__(entry, f"button_{command}")
        self._command = command
        if command.startswith(CUSTOM_PREFIX):
            # Custom buttons are named by the user, so no translation key.
            self._attr_name = label or command[len(CUSTOM_PREFIX):].replace("_", " ").title()
            self._attr_icon = CUSTOM_ICON
        else:
            self._attr_translation_key = command
            self._attr_icon = ICONS[command]

    async def async_press(self) -> None:
        async_send(self.hass, self._entry, self._command)
        # keep the fan entity in step
        async_dispatcher_send(self.hass, signal_remote(self._entry.entry_id), self._command)
