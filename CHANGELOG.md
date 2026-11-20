# Changelog

All notable changes are recorded here. This project follows
[Semantic Versioning](https://semver.org): MAJOR.MINOR.PATCH — a MAJOR bump
breaks existing setups, MINOR adds features compatibly, PATCH fixes bugs.

## Bridge firmware - 2026-11-20

### Fixed
- **Light flicking off and back on** (or on and back off). The bridge let the
  transmitter repeat each frame itself, which can leave short breaks between
  repeats; the fan counted a break as a second press of the light toggle. The
  bridge now sends the whole burst as one continuous transmission. Reflash the
  bridge with the updated `esphome/ceiling-fan-controller.yaml`.

## [2.7.3] - 2026-11-20

### Fixed
- **Light missing commands after 2.7.2.** The 0.5 s tap was too short for
  fans at the edge of the bridge's range. Toggle keys are now sent for 0.8 s,
  between the 0.5 s that was missed and the 1.1 s that could double-toggle.

## [2.7.2] - 2026-11-20

### Fixed
- **Light sometimes flicking off and back on (or on and back off)** when
  controlled from Home Assistant. The light and reverse keys are toggles and
  were sent as a 1.1 s button hold; if the fan missed a few frames mid-burst it
  counted two presses and the toggle undid itself. They are now sent as a
  short 0.5 s tap.

## [2.7.1] - 2026-11-18

Initial release.

### Features
- **Learn any RF fan remote** through an ESPHome ESP32 + CC1101 bridge. Setup
  finds the remote's frequency itself; hold a button first, then start the
  search.
- **Recognised remotes set up instantly.** A Chungear E01BT-S remote is
  identified and configured with every button, or you can enter its DIP-switch
  code directly.
- **Button-by-button learning** for any other remote: Off, On, Low, Medium,
  High, Light, Dim and Reverse, skipping any keys the remote doesn't have, plus
  any number of **custom buttons** you name yourself (Breeze, Timer,
  Nightlight…).
- **Fan entity** with on/off and the learned speeds. If the remote has a
  separate **On** key, turning the fan on sends it instead of re-sending a
  speed.
- **Light entity** for the light key, exposable to Alexa, Google and other
  voice assistants.
- **Light Sync switch** to correct Home Assistant's assumed light state when
  it gets out of step with the bulb, without sending anything to the fan.
- **Per-speed switches** (`switch.<fan>_low` / `_medium` / `_high`) that act
  like radio buttons, so voice assistants can set a speed with a plain on/off.
- **A button entity per learned key**, custom buttons included.
- **Remote follow.** Using the physical remote updates Home Assistant.
- **One remote per fan** is enforced: the flow refuses a remote that's already
  set up.
- Fans load reliably on restart, even before the ESPHome bridge connects.
- Ships its own icon (light and dark), shown on Home Assistant 2026.3 and
  newer.

### Notes
- Earlier version numbers were internal development builds and are not
  published.
