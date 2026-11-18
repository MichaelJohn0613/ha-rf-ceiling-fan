"""Pure RF helpers: clean learned frames, match received ones, build transmissions."""

from __future__ import annotations

import math
from collections import Counter
from statistics import median

from .const import DEFAULT_GAP_US, DEFAULT_HOLD_MS, HOLD_MS

MIN_PULSES = 16


def parse_timings(text: str) -> list[int]:
    """'412,-824,412' -> [412, -824, 412]; bad input -> []."""
    try:
        return [int(v) for v in str(text).split(",") if v.strip()]
    except ValueError:
        return []


def normalize(frame: list[int]) -> list[int]:
    """Trim to start and end with carrier-on (positive) pulses."""
    start, end = 0, len(frame)
    while start < end and frame[start] <= 0:
        start += 1
    while end > start and frame[end - 1] <= 0:
        end -= 1
    return list(frame[start:end])


def frames_match(received: list[int], template: list[int]) -> bool:
    """Same shape within receiver tolerance (marks shrink, spaces grow ~100us)."""
    if len(received) != len(template) or len(template) < MIN_PULSES:
        return False
    for got, want in zip(received, template):
        if (got > 0) != (want > 0):
            return False
        if abs(abs(got) - abs(want)) > max(200, 0.35 * abs(want)):
            return False
    return True


def clean_capture(frames: list[list[int]], gaps: list[int]) -> dict | None:
    """Turn ~30 noisy frames of one held button into one clean template.

    Uses the most common frame length, takes the per-pulse median, and
    requires most frames to agree. Returns {"timings": [...], "gap": us}.
    """
    frames = [normalize(f) for f in frames]
    frames = [f for f in frames if len(f) >= MIN_PULSES]
    if len(frames) < 3:
        return None
    counts = Counter(len(f) for f in frames)
    length = max(counts, key=lambda n: (counts[n], n))
    group = [f for f in frames if len(f) == length]
    if len(group) < 3:
        return None
    med = [int(median(f[i] for f in group)) for i in range(length)]
    good = [f for f in group if frames_match(f, med)]
    if len(good) < max(3, len(group) // 2):
        return None
    med = [int(median(f[i] for f in good)) for i in range(length)]
    valid_gaps = [g for g in gaps if 2000 < g < 100000]
    gap = int(median(valid_gaps)) if valid_gaps else DEFAULT_GAP_US
    return {"timings": med, "gap": gap}


def transmission(template: dict, command: str) -> tuple[list[int], int]:
    """Frame + gap, and how many repeats make a ~1 s button hold."""
    frame = list(template["timings"]) + [-abs(int(template["gap"]))]
    frame_us = sum(abs(v) for v in frame)
    hold_ms = HOLD_MS.get(command, DEFAULT_HOLD_MS)
    repeats = max(2, min(200, math.ceil(hold_ms * 1000 / frame_us)))
    return frame, repeats


# ---- Preset: Chungear E01BT-S (DIP switch remotes, 304.25 MHz) ----
CHUNGEAR_FREQUENCY = 304.25
_CHUNGEAR_BUTTONS = {
    "off": 0xFB, "low": 0x7F, "medium": 0xEF, "high": 0xF7, "light": 0xBF, "dim": 0xDF,
}


def identify_preset(frames: list[list[int]], frequency: float) -> dict | None:
    """Recognise a known remote model from captured frames.

    Returns {"name", "dip", "commands"} when the frames match a known
    model, otherwise None (the remote is then learned button by button).
    """
    if abs(frequency - CHUNGEAR_FREQUENCY) > 0.2:
        return None
    votes: dict[int, int] = {}
    for frame in frames:
        clean = normalize(frame)
        for dip in range(16):
            if any(
                frames_match(clean, t["timings"])
                for t in chungear_commands(dip).values()
            ):
                votes[dip] = votes.get(dip, 0) + 1
                break
    if not votes:
        return None
    dip = max(votes, key=votes.get)
    if votes[dip] < 3:
        return None
    return {
        "name": "Chungear E01BT-S",
        "dip": dip,
        "commands": chungear_commands(dip),
    }


def chungear_commands(dip: int) -> dict[str, dict]:
    """Templates measured from the real remote: 412us unit, 14.8ms gap."""
    out = {}
    for name, bits in _CHUNGEAR_BUTTONS.items():
        code = (bits << 4) | (dip & 0xF)
        t = [412]
        for b in range(11, -1, -1):
            t += [-824, 412] if (code >> b) & 1 else [-412, 824]
        out[name] = {"timings": t, "gap": 14832}
    return out
