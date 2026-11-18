"""Add-a-fan flow: name it, then learn each remote button (or use a preset)."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import Event, callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import slugify

from . import async_listen, get_hub
from . import const
from .const import (
    COMMANDS,
    CONF_BRIDGE,
    CONF_COMMANDS,
    CONF_DIP,
    CONF_FREQUENCY,
    CONF_LABELS,
    CONF_PRESET,
    CUSTOM_PREFIX,
    DOMAIN,
    RAW_EVENT,
    SCAN_FREQUENCIES,
    SEND_SUFFIX,
)
from .rf import (
    CHUNGEAR_FREQUENCY,
    MIN_PULSES,
    chungear_commands,
    clean_capture,
    frames_match,
    identify_preset,
    parse_timings,
)

# Known-model frequencies first, so a recognised remote is identified in seconds
IDENTIFY_FREQUENCIES = [CHUNGEAR_FREQUENCY] + [
    f for f in SCAN_FREQUENCIES if abs(f - CHUNGEAR_FREQUENCY) > 0.2
]

BUTTON_NAMES = {
    "off": "Fan OFF",
    "on": "Fan ON",
    "low": "Fan LOW",
    "medium": "Fan MEDIUM",
    "high": "Fan HIGH",
    "light": "LIGHT on/off",
    "dim": "LIGHT dim",
    "reverse": "REVERSE direction",
}
SCAN = "scan"


class LearnError(Exception):
    """A capture did not produce a usable button."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RFCeilingFanConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._name = ""
        self._bridge = ""
        self._frequency: float | None = None
        self._commands: dict[str, dict] = {}
        self._labels: dict[str, str] = {}   # custom command key -> display name
        self._index = 0                     # which button is being learned
        self._task: asyncio.Task | None = None
        self._error = ""
        self._dip: int | None = None
        self._preset: str | None = None
        self._learning = False
        self._custom_key = ""               # custom button currently being learned
        self._custom_label = ""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _bridges(self) -> list[str]:
        services = self.hass.services.async_services().get("esphome", {})
        return sorted(s[: -len(SEND_SUFFIX)] for s in services if s.endswith(SEND_SUFFIX))

    async def _start_learning(self, frequency: float) -> None:
        if not self._learning:
            self._learning = True
            get_hub(self.hass).learning += 1
        await async_listen(self.hass, self._bridge, frequency, learning=True)

    def _stop_learning(self) -> None:
        if self._learning:
            self._learning = False
            hub = get_hub(self.hass)
            hub.learning = max(0, hub.learning - 1)
            freq = hub.home_frequency() or self._frequency
            if freq is not None and self._bridge:
                self.hass.async_create_task(
                    async_listen(self.hass, self._bridge, freq, learning=False)
                )

    @callback
    def async_remove(self) -> None:
        """Flow closed or finished: put the bridge back to normal listening."""
        self._stop_learning()

    async def _collect(self, wait_first: float, quiet: float, longest: float):
        """Collect frames of one held button: (frames, gaps)."""
        frames: list[list[int]] = []
        gaps: list[int] = []
        stamps: list[float] = []

        @callback
        def _frame(event: Event) -> None:
            frame = parse_timings(event.data.get("timings", ""))
            if len(frame) < MIN_PULSES:
                return
            frames.append(frame)
            stamps.append(time.monotonic())
            try:
                gaps.append(int(event.data.get("gap", 0)))
            except (TypeError, ValueError):
                pass

        unsub = self.hass.bus.async_listen(RAW_EVENT, _frame)
        try:
            start = time.monotonic()
            while not stamps:
                if time.monotonic() - start > wait_first:
                    return frames, gaps
                await asyncio.sleep(0.05)
            while (
                time.monotonic() - stamps[-1] < quiet
                and time.monotonic() - stamps[0] < longest
            ):
                await asyncio.sleep(0.05)
        finally:
            unsub()
        return frames, gaps

    # ------------------------------------------------------------------
    # step 1: name
    # ------------------------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        bridges = self._bridges()
        if not bridges:
            return self.async_abort(reason="no_bridge")
        if user_input is not None:
            self._name = user_input["name"].strip()
            self._bridge = user_input.get(CONF_BRIDGE, bridges[0])
            return await self.async_step_ready()
        schema: dict[Any, Any] = {vol.Required("name"): str}
        if len(bridges) > 1:
            schema[vol.Required(CONF_BRIDGE, default=bridges[0])] = vol.In(bridges)
        return self.async_show_form(step_id="user", data_schema=vol.Schema(schema))

    # ------------------------------------------------------------------
    # step 2: make sure the button is already held before the search starts
    # ------------------------------------------------------------------
    async def async_step_ready(self, user_input=None) -> ConfigFlowResult:
        """Hold the button FIRST, then start the search.

        The search begins the moment it is started and lasts well under a
        minute, so a user who starts it and only then reaches for the remote
        misses it. Putting the instruction on the menu row itself also means
        it is readable even when translation loading is broken, which a
        progress step's text is not.
        """
        return self.async_show_menu(
            step_id="ready",
            menu_options={
                "identify": (
                    "Stand 1-3 ft from the controller, press and HOLD any "
                    "button on the remote, and keep holding while you tap this"
                ),
                "frequency": "Skip the search — I'll pick the frequency myself",
                "preset_manual": "Skip the search — enter a DIP switch code",
            },
        )

    # ------------------------------------------------------------------
    # step 3: listen once and work out the frequency and the remote model
    # ------------------------------------------------------------------
    async def async_step_identify(self, user_input=None) -> ConfigFlowResult:
        if self._task is None:
            self._task = self.hass.async_create_task(self._async_identify())
        if not self._task.done():
            return self.async_show_progress(
                step_id="identify", progress_action="identifying", progress_task=self._task
            )
        task, self._task = self._task, None
        try:
            frequency, frames = task.result()
        except LearnError:
            return self.async_show_progress_done(next_step_id="identify_failed")

        self._frequency = frequency
        if preset := identify_preset(frames, frequency):
            self._preset = preset["name"]
            self._dip = preset["dip"]
            self._commands = preset["commands"]
            return self.async_show_progress_done(next_step_id="finish")
        # Unrecognised remote: the frequency is known, so learn each button
        return self.async_show_progress_done(next_step_id="button")

    async def _async_identify(self) -> tuple[float, list[list[int]]]:
        """Find the frequency the remote uses, and capture frames from it.

        Frequencies already in use by other fans are tried first, so adding a
        second fan of the same kind takes a couple of seconds.
        """
        known = [e.data[CONF_FREQUENCY] for e in self._async_current_entries()]
        order = list(dict.fromkeys(known + IDENTIFY_FREQUENCIES))
        # Two passes: the first is a quick sweep for someone already holding a
        # button, the second catches a user who started holding a moment late
        # or had to walk to the fan. Dwelling longer on one pass would make the
        # right frequency come round too slowly to catch either.
        for _ in range(const.IDENTIFY_PASSES):
            for frequency in order:
                try:
                    await self._start_learning(frequency)
                except Exception as err:  # noqa: BLE001 - bridge offline or busy
                    raise LearnError("nothing_heard") from err
                frames, _ = await self._collect(
                    const.IDENTIFY_DWELL, const.IDENTIFY_DWELL, const.IDENTIFY_DWELL
                )
                if len(frames) >= 3:
                    return frequency, frames
        raise LearnError("nothing_heard")

    async def async_step_identify_failed(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="identify_failed",
            menu_options={
                "ready": "Try again — this time hold the button BEFORE tapping",
                "frequency": "Pick the frequency myself",
                "preset_manual": "Enter a DIP switch code instead",
            },
        )

    # ------------------------------------------------------------------
    # generic path: frequency -> learn each button
    # ------------------------------------------------------------------
    async def async_step_frequency(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[CONF_FREQUENCY] == SCAN:
                return await self.async_step_scan()
            self._frequency = float(user_input[CONF_FREQUENCY])
            return await self.async_step_button()
        options = [SCAN] + [f"{f:g}" for f in SCAN_FREQUENCIES]
        return self.async_show_form(
            step_id="frequency",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FREQUENCY, default=SCAN): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="frequency",
                        )
                    )
                }
            ),
        )

    async def async_step_scan(self, user_input=None) -> ConfigFlowResult:
        if self._task is None:
            self._task = self.hass.async_create_task(self._async_scan())
        if not self._task.done():
            return self.async_show_progress(
                step_id="scan", progress_action="scanning", progress_task=self._task
            )
        task, self._task = self._task, None
        try:
            self._frequency = task.result()
        except LearnError:
            return self.async_show_progress_done(next_step_id="scan_failed")
        return self.async_show_progress_done(next_step_id="button")

    async def _async_scan(self) -> float:
        """Listen on each common frequency while the user keeps pressing a button."""
        best, best_count = None, 0
        for freq in SCAN_FREQUENCIES:
            await self._start_learning(freq)
            frames, _ = await self._collect(const.SCAN_DWELL, const.SCAN_DWELL, const.SCAN_DWELL)
            if len(frames) > best_count:
                best, best_count = freq, len(frames)
        if best is None or best_count < 5:
            raise LearnError("nothing_heard")
        return best

    async def async_step_scan_failed(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="scan_failed",
            menu_options={
                "scan": "Scan again",
                "frequency": "Pick a frequency myself",
            },
        )

    async def async_step_button(self, user_input=None) -> ConfigFlowResult:
        """Ask before each button: capture it or skip it."""
        if self._index >= len(COMMANDS):
            return await self.async_step_extras()
        name = BUTTON_NAMES[COMMANDS[self._index]]
        return self.async_show_menu(
            step_id="button",
            menu_options={
                "capture": f"Ready — I'll hold {name} now",
                "skip": f"Skip {name} — my remote doesn't have it",
            },
            description_placeholders={
                "button": BUTTON_NAMES[COMMANDS[self._index]],
                "frequency": f"{self._frequency:g}",
                "learned": ", ".join(BUTTON_NAMES[c] for c in self._commands) or "none yet",
            },
        )

    async def async_step_skip(self, user_input=None) -> ConfigFlowResult:
        self._index += 1
        return await self.async_step_button()

    async def async_step_capture(self, user_input=None) -> ConfigFlowResult:
        command = COMMANDS[self._index]
        if self._task is None:
            self._task = self.hass.async_create_task(self._async_capture())
        if not self._task.done():
            return self.async_show_progress(
                step_id="capture",
                progress_action="hold_button",
                progress_task=self._task,
                description_placeholders={"button": BUTTON_NAMES[command]},
            )
        task, self._task = self._task, None
        try:
            self._commands[command] = task.result()
        except LearnError as err:
            self._error = err.reason
            return self.async_show_progress_done(next_step_id="capture_failed")
        self._index += 1
        return self.async_show_progress_done(next_step_id="button")

    async def _async_capture(self) -> dict:
        await self._start_learning(self._frequency)
        frames, gaps = await self._collect(
            const.LEARN_TIMEOUT, const.LEARN_QUIET, const.LEARN_MAX
        )
        if not frames:
            raise LearnError("nothing_heard")
        template = clean_capture(frames, gaps)
        if template is None:
            raise LearnError("unclear")
        for done in self._commands.values():
            if frames_match(template["timings"], done["timings"]):
                raise LearnError("same_button")
        return template

    async def async_step_capture_failed(self, user_input=None) -> ConfigFlowResult:
        reasons = {
            "nothing_heard": "Nothing was received.",
            "unclear": "A signal was received but it was not clean enough.",
            "same_button": "That is the same signal as a button already learned.",
        }
        return self.async_show_menu(
            step_id="capture_failed",
            menu_options={
                "capture": f"Try {BUTTON_NAMES[COMMANDS[self._index]]} again",
                "skip": "Skip this button",
            },
            description_placeholders={
                "button": BUTTON_NAMES[COMMANDS[self._index]],
                "reason": reasons.get(self._error, self._error),
            },
        )

    # ------------------------------------------------------------------
    # extra custom buttons (anything the standard keys don't cover)
    # ------------------------------------------------------------------
    async def async_step_extras(self, user_input=None) -> ConfigFlowResult:
        """After the standard keys: offer to add named custom buttons."""
        return self.async_show_menu(
            step_id="extras",
            menu_options={
                "add_custom": "Add a custom button (Breeze, Timer, Nightlight…)",
                "finish": "Done — save this fan",
            },
            description_placeholders={
                "added": ", ".join(self._labels.values()) or "none",
            },
        )

    async def async_step_add_custom(self, user_input=None) -> ConfigFlowResult:
        """Name the custom button, then capture it."""
        if user_input is not None:
            label = user_input["label"].strip()
            slug = slugify(label) or "button"
            key = f"{CUSTOM_PREFIX}{slug}"
            suffix = 2
            while key in self._commands:
                key = f"{CUSTOM_PREFIX}{slug}_{suffix}"
                suffix += 1
            self._custom_key = key
            self._custom_label = label
            return await self.async_step_capture_custom()
        return self.async_show_form(
            step_id="add_custom",
            data_schema=vol.Schema({vol.Required("label"): str}),
        )

    async def async_step_capture_custom(self, user_input=None) -> ConfigFlowResult:
        if self._task is None:
            self._task = self.hass.async_create_task(self._async_capture())
        if not self._task.done():
            return self.async_show_progress(
                step_id="capture_custom",
                progress_action="hold_button",
                progress_task=self._task,
                description_placeholders={"button": self._custom_label},
            )
        task, self._task = self._task, None
        try:
            self._commands[self._custom_key] = task.result()
        except LearnError as err:
            self._error = err.reason
            return self.async_show_progress_done(next_step_id="custom_failed")
        self._labels[self._custom_key] = self._custom_label
        return self.async_show_progress_done(next_step_id="extras")

    async def async_step_custom_failed(self, user_input=None) -> ConfigFlowResult:
        reasons = {
            "nothing_heard": "Nothing was received.",
            "unclear": "A signal was received but it was not clean enough.",
            "same_button": "That is the same signal as a button already learned.",
        }
        return self.async_show_menu(
            step_id="custom_failed",
            menu_options={
                "capture_custom": f"Try {self._custom_label} again",
                "extras": "Cancel this button",
            },
            description_placeholders={
                "button": self._custom_label,
                "reason": reasons.get(self._error, self._error),
            },
        )

    # ------------------------------------------------------------------
    # fallback: type in a DIP-switch code for a known model
    # ------------------------------------------------------------------
    async def async_step_preset_manual(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._dip = int(user_input[CONF_DIP], 2)
            self._frequency = CHUNGEAR_FREQUENCY
            self._preset = "Chungear E01BT-S"
            self._commands = chungear_commands(self._dip)
            return await self.async_step_finish()
        return self.async_show_form(
            step_id="preset_manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DIP): SelectSelector(
                        SelectSelectorConfig(
                            options=[format(d, "04b") for d in range(16)],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    # ------------------------------------------------------------------
    # save
    # ------------------------------------------------------------------
    async def async_step_finish(self, user_input=None) -> ConfigFlowResult:
        data: dict[str, Any] = {CONF_BRIDGE: self._bridge, CONF_FREQUENCY: self._frequency}
        if self._dip is not None:
            data[CONF_DIP] = self._dip
        if self._preset is not None:
            data[CONF_PRESET] = self._preset
        if not self._commands:
            return self.async_abort(reason="nothing_learned")

        # Refuse a remote another fan already uses
        for entry in self._async_current_entries():
            if abs(entry.data[CONF_FREQUENCY] - self._frequency) > 0.1:
                continue
            for theirs in entry.data[CONF_COMMANDS].values():
                if any(
                    frames_match(mine["timings"], theirs["timings"])
                    for mine in self._commands.values()
                ):
                    return self.async_abort(
                        reason="already_configured",
                        description_placeholders={"other": entry.title},
                    )

        first = next(iter(self._commands.values()))["timings"]
        digest = hashlib.sha1(
            f"{self._frequency}:{first}".encode()
        ).hexdigest()[:12]
        await self.async_set_unique_id(digest)
        self._abort_if_unique_id_configured()
        data[CONF_COMMANDS] = self._commands
        if self._labels:
            data[CONF_LABELS] = self._labels
        return self.async_create_entry(title=self._name, data=data)
