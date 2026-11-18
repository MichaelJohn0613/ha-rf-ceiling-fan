# RF Ceiling Fan

Control non-smart ceiling fans that came with a radio (RF) remote, through an
ESPHome + CC1101 bridge.

Full documentation, wiring and troubleshooting:
https://github.com/MichaelJohn0613/ha-rf-ceiling-fan

## Install
1. Flash the bridge firmware (`esphome/ceiling-fan-controller.yaml`) to the ESP32.
2. Install this integration from the Marketplace (Home Assistant 2026.11+) or
   HACS as a custom repository, or copy this `rf_ceiling_fan` folder into
   `/config/custom_components/`.
3. Restart Home Assistant if asked.

## Add a fan
Settings > Devices & Services > Add Integration > **RF Ceiling Fan**

1. Name the fan.
2. Press and hold any button on its remote, then start the search.

The integration finds the frequency itself and checks whether it recognises the
remote model. A recognised remote (currently Chungear E01BT-S) is set up
immediately with all its buttons. An unrecognised one is learned button by
button: hold each key when prompted, and skip any the remote doesn't have. You
can then add custom buttons (Breeze, Timer, Nightlight...).

If no signal is heard you can pick the frequency by hand, or enter a DIP switch
code directly.

Each fan becomes its own device with a fan entity (on/off + the speeds you
learned), a button per learned key (except the light), and, where the keys were
learned, a light entity, a Light Sync switch and one on/off switch per speed.
Using the real remote updates Home Assistant automatically.

## Notes
- Infrared (point-at-the-fan) remotes cannot be learned; this is radio only.
- Two fans must not share a remote code, or one press moves both. The flow
  refuses a remote that is already set up.
- The bridge can only listen on one frequency at a time, so remote-following
  works for fans on the most common frequency among those configured.
- Hold the remote 1-3 feet from the bridge while learning.
