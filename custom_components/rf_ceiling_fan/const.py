"""Constants for the RF Ceiling Fan integration."""

DOMAIN = "rf_ceiling_fan"

CONF_BRIDGE = "bridge"            # e.g. "ceiling_fan_controller" (ESPHome device)
CONF_FREQUENCY = "frequency"      # MHz
CONF_COMMANDS = "commands"        # {command: {"timings": [...], "gap": us}}
CONF_DIP = "dip"                  # only for recognised DIP-switch remotes
CONF_PRESET = "preset"            # name of the recognised remote model, if any
CONF_LABELS = "labels"            # {custom command key: display name}

# Prefix marking a user-named custom button (vs. the standard keys below)
CUSTOM_PREFIX = "custom_"

# Bridge actions are exposed by ESPHome as esphome.<device>_<action>
SEND_SUFFIX = "_send_raw"
LISTEN_SUFFIX = "_listen"

# Event fired by the bridge for every received remote frame
RAW_EVENT = "esphome.rf_raw"

# Standard remote keys, in the order they are learned. "on" is a distinct
# power-on key that some remotes have separately from the speed buttons; it is
# skippable like any other during learning.
COMMANDS = ["off", "on", "low", "medium", "high", "light", "dim", "reverse"]
SPEED_COMMANDS = ["low", "medium", "high"]

# How long one command "holds the button" (the fans need about 1 s).
# Toggle keys get a short tap instead: a long burst can be counted as two
# presses, and a toggle pressed twice undoes itself (the light flicks off and
# straight back on). Tested on a Chungear fan: 0.25 s toggles every time with
# no bounce, while 0.8 s still bounced.
HOLD_MS = {"dim": 1600, "light": 250, "reverse": 250}
DEFAULT_HOLD_MS = 1100
DEFAULT_GAP_US = 10000

# Common fan-remote frequencies (MHz), most likely first
SCAN_FREQUENCIES = [304.25, 303.875, 315.0, 433.92, 310.0, 318.0, 390.0, 418.0]

LEARN_TIMEOUT = 20      # seconds to wait for the first frame of a button
LEARN_QUIET = 1.2       # seconds without frames that ends a capture
LEARN_MAX = 4.0         # longest capture after the first frame
SCAN_DWELL = 4.0        # seconds listened on each frequency while scanning
IDENTIFY_DWELL = 2.0    # seconds listened per frequency while identifying
IDENTIFY_PASSES = 2     # sweeps of the frequency list before giving up
SYNC_DEDUPE = 1.5       # seconds: one held press = one state change
SEND_SETTLE = 0.25      # seconds of quiet after a transmission
MAX_QUEUE = 4           # most commands allowed to wait for one fan


def signal_remote(entry_id: str) -> str:
    """Dispatcher signal: the real remote for this fan sent a command."""
    return f"{DOMAIN}_remote_{entry_id}"


def signal_light(entry_id: str) -> str:
    """Dispatcher signal: this fan's assumed light state changed.

    The light is a single toggle with no feedback, so its on/off is a shared
    assumption held in the hub. Both the light entity and the light-sync
    switch render from it and refresh on this signal.
    """
    return f"{DOMAIN}_light_{entry_id}"


def signal_fan(entry_id: str) -> str:
    """Dispatcher signal: this fan's current speed changed.

    The fan publishes its current speed to the hub so the per-speed switches
    (radio-button style, exposed to voice assistants) can render which speed
    is active and refresh on this signal.
    """
    return f"{DOMAIN}_fan_{entry_id}"
