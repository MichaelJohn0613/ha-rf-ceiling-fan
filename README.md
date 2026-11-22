# RF Ceiling Fan

[![Marketplace / HACS compatible][hacs-badge]][hacs]
[![Validate][validate-badge]][validate]

Control ceiling fans that came with a **radio (RF) remote** — the non-smart kind —
from Home Assistant, using an ESP32 + CC1101 bridge that captures the original
remote's codes and replays them.

No cloud, no vendor hub, no replacing the fan. The integration listens to the
real remote over RF, learns each button, and gives you a fan entity plus a button
per key. Pressing the physical remote keeps Home Assistant in sync.

> **Radio only.** Infrared "point-at-the-fan" remotes cannot be learned — those
> send light, not RF. If your remote only works when aimed straight at the fan,
> this isn't the right project.

---

## How it works

A small ESP32 board with a CC1101 sub-GHz radio sits near your fans and acts as a
dumb **bridge**: it can listen on a given frequency and report any RF frames it
hears, and it can transmit a raw frame on command. All the intelligence —
identifying the remote, learning buttons, remembering which fan is which — lives
in this integration, inside Home Assistant.

When you add a fan, the integration has the bridge listen while you hold a button
on the real remote, captures the waveform, and works out the frequency and (where
it can) the remote model. From then on, Home Assistant entities transmit those
same captured frames, and when you use the physical remote the bridge hears it and
updates the matching entity.

Because it's a one-way transmitter, the fan's state is **assumed** — Home
Assistant shows what it last sent or last heard, not a live reading from the fan.

---

## What you need

- An **ESP32** dev board.
- A **CC1101** sub-GHz transceiver module (the common SMA-antenna breakout).
- The fan's original **RF remote**, to learn from.
- [ESPHome](https://esphome.io/) (the add-on or CLI) — used once, to flash the
  bridge firmware.

### Wiring (ESP32 ↔ CC1101)

| CC1101 | ESP32  | Purpose          |
|--------|--------|------------------|
| VCC    | 3V3    | Power (3.3 V!)   |
| GND    | GND    | Ground           |
| SCK    | GPIO18 | SPI clock        |
| MISO   | GPIO19 | SPI data in      |
| MOSI   | GPIO23 | SPI data out     |
| CSN    | GPIO5  | SPI chip select  |
| GDO0   | GPIO4  | TX (transmit)    |
| GDO2   | GPIO16 | RX (receive)     |

CC1101 is a **3.3 V** part — do not feed it 5 V. After flashing, check the
ESPHome log for the CC1101 **Chip ID**: `0x0014` or `0x0004` means the radio is
talking. `0x0000`, or an ID starting `0xFF`, means a loose or wrong SPI wire.

**Placement and power.** Too *strong* a signal is a problem as well as too
weak: a fan in the same room as the bridge can be overloaded and ignore
commands, even though its own remote works. Put the bridge somewhere central,
ideally not in a room with a fan, and tune `tx_power` at the top of the bridge
config (default `5`, maximum `11`): lower it if the nearest fan is unreliable,
raise it if the farthest one is.

**Per-fan power.** If no single power suits every fan — usually because one
fan is close to the bridge — give that fan its own: **Settings → Devices &
services → RF Ceiling Fan → the fan → Configure → Transmit power** (dBm, -30 to
11; leave empty for the bridge default). Try `0` or `-10` for a fan in the same
room as the bridge. Needs bridge firmware with the `send_raw_power` action
(the config in this repo); with older firmware the setting is ignored and a
warning is logged.

---

## 1. Flash the bridge

The bridge firmware is in
[`esphome/ceiling-fan-controller.yaml`](esphome/ceiling-fan-controller.yaml).
It reads four values from your ESPHome `secrets.yaml`: `wifi_ssid`,
`wifi_password`, `api_encryption_key` (generate one at
[esphome.io/components/api](https://esphome.io/components/api/)) and
`fallback_ap_password`. Add those, then flash it to the ESP32 with ESPHome. Once it boots and appears under **Settings → Devices & Services →
ESPHome**, the bridge is ready — it exposes the `listen` and `send_raw` actions
this integration drives. You do **not** configure fans on the device; all of that
happens in Home Assistant.

## 2. Install this integration

This is a **custom repository**: it isn't in the built-in catalog, so you add it
by its GitHub link. That's a one-time step and needs a repository that is public
and ships a `hacs.json` — both already true here.

> **Repository URL:** `https://github.com/MichaelJohn0613/ha-rf-ceiling-fan`

### A) Home Assistant 2026.11 or newer — the Marketplace

In 2026.11, Home Assistant absorbed HACS and replaced it with the built-in
**Marketplace**, found under **Settings → Marketplace**. There's nothing extra to
install — it ships with Home Assistant.

1. Go to **Settings → Marketplace**.
2. Select **Add from link** in the upper-right corner.
3. Paste the repository URL above and confirm the kind is **Integration**, then
   **Add**.
4. If you haven't linked GitHub before, the Marketplace will ask you to now. It
   uses **GitHub device sign-in** — you'll get a short code to approve at
   `github.com/login/device`, so you never type your GitHub password into Home
   Assistant. Approve it and return.
5. The repository now shows up in the Marketplace. Open **RF Ceiling Fan** and
   select **Install**. The first time, Home Assistant reminds you that community
   content isn't reviewed or supported by the project — confirm to continue.
6. If the Marketplace asks for a restart, use the repair under **Settings →
   System → Repairs** to restart Home Assistant. If the setup dialog later comes
   up with **blank text or empty menu rows**, do a full restart (see
   Troubleshooting) — that's a translation-cache quirk, not a broken install.

The Marketplace also creates an **update entity** for the repository, so future
versions show up alongside your Home Assistant updates.

### B) Home Assistant 2026.10 or earlier — HACS

If you haven't upgraded to 2026.11 and still run HACS:

1. **HACS → overflow menu (⋮) → Custom repositories.**
2. Enter the repository URL above, set **Category: Integration**, and select
   **Add**.
3. Search HACS for **RF Ceiling Fan** and **Download** it.
4. **Restart Home Assistant.**

### C) Manual install (no store)

Copy the `custom_components/rf_ceiling_fan/` folder into your
`/config/custom_components/` directory and restart Home Assistant.

## 3. Add a fan

**Settings → Devices & Services → Add Integration → RF Ceiling Fan.**

1. **Name the fan** (e.g. *Kitchen*).
2. On the next screen, **press and hold any button on the remote** 1–3 ft from the
   bridge, *then* start the search — and keep holding it until the search
   finishes. Holding first matters: the radio only hears you while the search is
   actually running.

The integration finds the frequency itself and checks whether it recognizes the
remote model:

- **Recognized** (currently the Chungear E01BT-S): set up instantly, with every
  button.
- **Unrecognized:** learned one button at a time — hold each key when prompted,
  and skip any your remote doesn't have. The standard keys are Off, **On**, Low,
  Medium, High, Light, Dim, and Reverse; learn only the ones your remote has.

If nothing is heard, you can **pick the frequency by hand** or **type a DIP-switch
code** directly.

**Custom buttons.** After the standard keys, the flow offers to add extra buttons
of your own — a breeze mode, a timer, a nightlight, anything else on the remote.
Name each one and hold it like any other key; it becomes its own button entity.

**The On key.** If your remote has a dedicated power-on button separate from the
speeds, learn it as **On**, and Home Assistant's plain turn-on will send that key
instead of re-sending a speed. Remotes without one work exactly as before — turn-on
just re-sends the last speed.

Each fan becomes its own **device** with:

- a **fan entity** (on/off plus the speeds you learned) — created when Off and at
  least one speed were learned;
- **one button entity per learned key** except the light, custom buttons
  included;
- if the light key was learned, a **light entity** and a **Light Sync switch**;
- if Off was learned, a **speed switch** per learned speed
  (`switch.<fan>_low` / `_medium` / `_high`).

Using the real remote updates Home Assistant automatically.

**Voice assistants.** The light entity and the speed switches are plain on/off
entities, so they work cleanly with Alexa, Google, or local Hue emulation. The
speed switches act like radio buttons: turning one on selects that speed, and
turning it off stops the fan. Expose those rather than the fan entity, which
voice assistants treat as a dimmable light and often report an error for, even
when the speed change works.

**Light Sync.** The light key is a single toggle with no feedback, so Home
Assistant can end up believing the light is on while the bulb is off. Set the
Light Sync switch to match what the bulb is really doing — it corrects Home
Assistant's assumption **without sending anything** to the fan.

---

## Notes & limits

- **One remote, one fan.** Two fans must not share a remote code, or a single
  press moves both. The flow refuses a remote that's already set up — change one
  fan's DIP switches (and its receiver) first, then add it.
- **One frequency at a time.** The bridge can only listen on a single frequency,
  so remote-following works for fans on the most common frequency among those
  you've configured.
- **Distance.** Hold the remote 1–3 ft from the bridge while learning — closer is
  not better, and across the room is too far.
- **Assumed state.** This is a one-way transmitter; Home Assistant reflects the
  last command sent or heard, not a reading from the fan. If the light gets out
  of step, fix it with the Light Sync switch.

## Troubleshooting

- **Blank text / empty menu rows in the setup dialog.** Do a **full restart** of
  Home Assistant (Settings → System → power icon → *Restart Home Assistant*, not
  "Quick reload"). Home Assistant caches an integration's translations for the
  life of the process and won't re-read them from disk until a real restart —
  this is the single most common hiccup after installing or updating.
- **Nothing heard during the search.** Confirm the CC1101 reports **Chip ID
  `0x0004`** in the ESPHome log, that you're on the right frequency, and that you
  started holding the button **before** the search began. Check the GDO2→GPIO16
  wire if reception never works at all.
- **Commands fire but the fan ignores them.** Make sure only one fan is on each
  remote code, and that the bridge is within range — a short whip on a
  mismatched-band board loses range, so a matched antenna helps.

## Publishing / getting into the Marketplace catalog

This repo installs as a **custom repository** today (sections A/B above). To be
listed in the searchable Marketplace **catalog** so others find it without the
link, it additionally needs:

- a pull request to add the repository to the catalog (see the
  [Marketplace contributor docs](https://contributors.home-assistant.io/marketplace/how-it-works/)).

The integration's icon ships in `custom_components/rf_ceiling_fan/brand/`
(Home Assistant 2026.3 and newer show it; older versions show a placeholder),
so no submission to home-assistant/brands is needed.

## License

[Apache 2.0](LICENSE)

<!-- badges -->
[hacs]: https://github.com/hacs/integration
[hacs-badge]: https://img.shields.io/badge/Marketplace%20%2F%20HACS-custom-41BDF5.svg
[validate]: ../../actions/workflows/validate.yaml
[validate-badge]: ../../actions/workflows/validate.yaml/badge.svg
