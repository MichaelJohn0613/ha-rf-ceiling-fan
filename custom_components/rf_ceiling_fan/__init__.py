"""RF Ceiling Fan: control non-smart RF fans through an ESPHome CC1101 bridge."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, deque

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_SERVICE_REGISTERED, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_BRIDGE,
    CONF_COMMANDS,
    CONF_FREQUENCY,
    CONF_TX_POWER,
    DOMAIN,
    LISTEN_SUFFIX,
    MAX_QUEUE,
    RAW_EVENT,
    SEND_POWER_SUFFIX,
    SEND_SETTLE,
    SEND_SUFFIX,
    SPEED_COMMANDS,
    SYNC_DEDUPE,
    signal_fan,
    signal_light,
    signal_remote,
)
from .rf import frames_match, normalize, parse_timings, transmission

PLATFORMS = [Platform.FAN, Platform.LIGHT, Platform.SWITCH, Platform.BUTTON]
_LOGGER = logging.getLogger(__name__)

# Commands that set a state: a newer one makes an older one pointless.
# "on" is here too - if a speed or off is queued behind it, that wins.
STATE_COMMANDS = {"off", "on", *SPEED_COMMANDS}


class Sender:
    """Sends one fan's commands in turn, dropping ones that no longer matter.

    Every transmission occupies the radio for about a second, so commands are
    queued. A new speed (or off) replaces any speed still waiting, which stops
    a dragged slider from playing out every step it passed through. Toggles
    like the light are each meaningful, so they are kept - but only a few, so
    impatient tapping cannot turn into a flashing light.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._queue: deque[str] = deque()
        self._worker: asyncio.Task | None = None
        self._warned_power = False

    @callback
    def submit(self, command: str) -> None:
        if command in STATE_COMMANDS:
            self._queue = deque(c for c in self._queue if c not in STATE_COMMANDS)
        elif len(self._queue) >= MAX_QUEUE:
            _LOGGER.debug("%s: dropping %s, queue full", self._entry.title, command)
            return
        self._queue.append(command)
        if self._worker is None or self._worker.done():
            self._worker = self._hass.async_create_task(self._run())

    async def _run(self) -> None:
        while self._queue:
            command = self._queue.popleft()
            template = self._entry.data[CONF_COMMANDS].get(command)
            if template is None:
                continue
            frame, repeats = transmission(template, command)
            service, data = self._service(frame, repeats)
            try:
                await self._hass.services.async_call(
                    "esphome", service, data, blocking=True
                )
            except Exception:  # noqa: BLE001 - the bridge may be offline
                _LOGGER.exception("%s: sending %s failed", self._entry.title, command)
                self._queue.clear()
                return
            # Hold the radio for as long as the transmission lasts
            await self._wait(sum(abs(v) for v in frame) * repeats / 1e6 + SEND_SETTLE)

    def _service(self, frame: list[int], repeats: int) -> tuple[str, dict]:
        """Pick the bridge action, adding this fan's transmit power if set.

        A fan close to the bridge can be overloaded by full power and ignore
        it, so each fan may have its own power. Older bridge firmware has no
        power action; then the bridge's own power is used.
        """
        bridge = self._entry.data[CONF_BRIDGE]
        data: dict = {
            "frequency": float(self._entry.data[CONF_FREQUENCY]),
            "timings": frame,
            "repeats": repeats,
        }
        power = self._entry.options.get(CONF_TX_POWER)
        if power is None:
            return bridge + SEND_SUFFIX, data
        if self._hass.services.has_service("esphome", bridge + SEND_POWER_SUFFIX):
            data["power"] = float(power)
            return bridge + SEND_POWER_SUFFIX, data
        if not self._warned_power:
            self._warned_power = True
            _LOGGER.warning(
                "%s: a transmit power is set, but the bridge firmware has no "
                "send_raw_power action yet; update the bridge to use it",
                self._entry.title,
            )
        return bridge + SEND_SUFFIX, data

    async def _wait(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def cancel(self) -> None:
        self._queue.clear()
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()


class Hub:
    """Shared listener: matches real-remote frames to configured fans."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.entries: dict[str, ConfigEntry] = {}
        self.senders: dict[str, Sender] = {}
        self.learning = 0          # >0 while a config flow is learning
        self._recent: dict[tuple[str, str], float] = {}
        # Assumed on/off of each fan's light. The light is a single toggle with
        # no feedback, so this is the shared belief the light entity and the
        # light-sync switch both render from.
        self.light_state: dict[str, bool] = {}
        # Current speed command of each fan ("low"/"medium"/"high") or None when
        # off. Published by the fan entity so the per-speed switches can show
        # which speed is active.
        self.fan_speed: dict[str, str | None] = {}
        self._unsub = hass.bus.async_listen(RAW_EVENT, self._on_frame)

    @callback
    def set_light(self, entry_id: str, value: bool) -> None:
        """Record the assumed light state and notify entities. Sends no RF."""
        self.light_state[entry_id] = value
        async_dispatcher_send(self.hass, signal_light(entry_id))

    @callback
    def toggle_light(self, entry_id: str) -> None:
        """Flip the assumed light state (used by remote-follow). Sends no RF."""
        self.set_light(entry_id, not self.light_state.get(entry_id, False))

    @callback
    def _on_frame(self, event: Event) -> None:
        if self.learning:
            return
        frame = normalize(parse_timings(event.data.get("timings", "")))
        try:
            freq = float(event.data.get("frequency", 0))
        except (TypeError, ValueError):
            return
        now = time.monotonic()
        for entry_id, entry in self.entries.items():
            if abs(entry.data[CONF_FREQUENCY] - freq) > 0.1:
                continue
            for command, template in entry.data[CONF_COMMANDS].items():
                if frames_match(frame, template["timings"]):
                    key = (entry_id, command)
                    if now - self._recent.get(key, 0) > SYNC_DEDUPE:
                        async_dispatcher_send(self.hass, signal_remote(entry_id), command)
                    self._recent[key] = now
                    return

    def home_frequency(self) -> float | None:
        freqs = [e.data[CONF_FREQUENCY] for e in self.entries.values()]
        return Counter(freqs).most_common(1)[0][0] if freqs else None

    async def async_listen_home(self, bridge: str) -> None:
        """Point the bridge's receiver at the most-used fan frequency."""
        freq = self.home_frequency()
        if freq is not None:
            await async_listen(self.hass, bridge, freq, learning=False)

    def close(self) -> None:
        self._unsub()


def get_hub(hass: HomeAssistant) -> Hub:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = Hub(hass)
    return hass.data[DOMAIN]


async def async_listen(hass: HomeAssistant, bridge: str, freq: float, learning: bool) -> None:
    if hass.services.has_service("esphome", bridge + LISTEN_SUFFIX):
        await hass.services.async_call(
            "esphome", bridge + LISTEN_SUFFIX,
            {"frequency": float(freq), "learning": learning}, blocking=True,
        )


@callback
def async_send(hass: HomeAssistant, entry: ConfigEntry, command: str) -> None:
    """Queue one command for this fan. Returns at once; sending is serialised."""
    get_hub(hass).senders[entry.entry_id].submit(command)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub = get_hub(hass)
    hub.entries[entry.entry_id] = entry
    hub.senders[entry.entry_id] = Sender(hass, entry)
    # The fan, light and button entities are assumed-state and need nothing
    # from the bridge to exist, so set them up unconditionally - a restart must
    # never leave them unavailable waiting on the bridge. Forward exactly once
    # and never raise afterwards: a raise here would strand the forwarded
    # platforms and make the next setup attempt collide with "config entry ...
    # has already been set up".
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _point_receiver(hass, entry, hub)
    return True


@callback
def _point_receiver(hass: HomeAssistant, entry: ConfigEntry, hub: Hub) -> None:
    """Aim the shared receiver at the busiest fan frequency, when we can.

    The bridge's ESPHome services (esphome.<bridge>_send_raw / _listen) only
    register once the device reconnects over the API, which lags HA startup.
    So point the receiver now if the bridge is already up, and otherwise as
    soon as its listen service appears. Best effort - never fails the entry.
    """
    bridge = entry.data[CONF_BRIDGE]
    service = bridge + LISTEN_SUFFIX

    async def _point() -> None:
        # The listen service can register a moment before the ESPHome API
        # connection finishes authenticating ("connection not ready yet"), so
        # retry a few times with backoff before giving up. Best effort - a
        # failure here only means remote-follow waits for the next command.
        for attempt in range(6):
            try:
                await hub.async_listen_home(bridge)
                return
            except Exception:  # noqa: BLE001 - the bridge may not be ready
                if attempt == 5:
                    _LOGGER.warning(
                        "%s: could not point the bridge receiver after retries",
                        entry.title,
                    )
                    return
                await asyncio.sleep(2 * (attempt + 1))

    if hass.services.has_service("esphome", service):
        hass.async_create_task(_point())
        return

    cancel: list = []

    @callback
    def _stop() -> None:
        # Drain so the bus unsubscribe runs at most once, whether we stop
        # because the service appeared or because the entry unloaded first.
        while cancel:
            cancel.pop()()

    @callback
    def _on_registered(event: Event) -> None:
        if (
            event.data.get("domain") == "esphome"
            and event.data.get("service") == service
        ):
            _stop()
            hass.async_create_task(_point())

    cancel.append(hass.bus.async_listen(EVENT_SERVICE_REGISTERED, _on_registered))
    entry.async_on_unload(_stop)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hub = get_hub(hass)
    hub.entries.pop(entry.entry_id, None)
    hub.light_state.pop(entry.entry_id, None)
    hub.fan_speed.pop(entry.entry_id, None)
    if (sender := hub.senders.pop(entry.entry_id, None)) is not None:
        sender.cancel()
    if not hub.entries:
        hub.close()
        hass.data.pop(DOMAIN, None)
    return ok
