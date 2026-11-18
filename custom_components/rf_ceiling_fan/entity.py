"""Shared base entity: one device per fan."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_FREQUENCY, CONF_PRESET, DOMAIN


class RFCeilingFanEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_assumed_state = True

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        preset = entry.data.get(CONF_PRESET)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=preset or "Learned RF remote",
            model=f"{entry.data[CONF_FREQUENCY]:.3f} MHz",
        )
