# TR198A Ceiling-Fan Home Assistant Integration

A custom Home Assistant integration and Python toolkit for controlling TR198A ceiling fans via Broadlink RM-series RF remotes. This project provides both a Home Assistant component and a standalone Python CLI/library for advanced automation and reverse-engineered RF packet control.

---

## Features

- **Home Assistant Integration**: Adds a `fan` entity for TR198A ceiling fans, with support for speed, direction, breeze modes, light toggle, and pairing.
- **Button Entities**: Exposes pairing, light toggle, and dimming as Home Assistant button entities and services.
- **Config Flow**: Simple UI-based setup for selecting your Broadlink remote and (optionally) a smart power switch.
- **Pure Python RF Codec**: All RF packet generation is implemented in Python—no external dependencies for packet building.
- **Command-Line Tool**: `fancli.py` lets you generate handset IDs, pair fans, and send commands directly from the terminal or scripts.

---

## Installation

1. **Copy the Integration**
   - Place the `custom_components/tr198a_fan/` folder into your Home Assistant `custom_components/` directory.

2. **Restart Home Assistant**

3. **Add Integration**
   - Go to *Settings → Devices & Services → Add Integration* and search for "TR198A Ceiling-Fan".

4. **Follow the Config Flow**
   - Select your Broadlink remote (e.g., RM4 Pro).
   - Optionally select a smart power switch if your fan is powered through one.
   - Assign a friendly name.

---

## Usage

### Home Assistant

- **Fan Entity**: Control speed (0–9), direction, and breeze presets.
- **Light Toggle**: Use the button entity or service to toggle the fan's light.
- **Pairing**: Use the "Pair Remote" button or service to pair a new handset ID with your fan.
- **Dimming**: Use "Dim Up" and "Dim Down" buttons/services for light dimming steps.

#### Services

See `services.yaml` for full details. Example services:

- `tr198a_fan.pair`: Pair the remote to the fan.
- `tr198a_fan.light_toggle`: Toggle the fan's light.
- `tr198a_fan.dim_up` / `tr198a_fan.dim_down`: Adjust light brightness.

### Python CLI/Library

The `fancli.py` script provides a command-line and importable interface:

```sh
# Generate a new handset ID
python fancli.py gen-id

# Build and print the pairing packet
python fancli.py pair 0x15a9

# Send a speed-5, forward-rotation command (requires --host)
python fancli.py cmd 0x15a9 --speed 5 --direction forward --host 192.168.1.42
```

Or use as a library:

```python
from fancli import build_payload, build_rf_packet, send_packet
packet = build_rf_packet(build_payload(0x15A9, speed=3, direction="forward"))
send_packet(packet, host="192.168.1.42")
```

---

## Requirements

- Home Assistant (latest recommended)
- Broadlink RM4 Pro (or compatible RF remote)
- Python 3.9+
- See `requirements.txt` for development dependencies (not all are required for integration use)

---

## Development & Reverse Engineering

- All RF protocol logic is implemented in `codec.py` and `fancli.py`.
- No proprietary libraries required for packet building.
- See `exp/` notebooks for protocol analysis and timing experiments.

---

## File Overview

- `custom_components/tr198a_fan/` – Home Assistant integration
  - `fan.py` – Main fan entity logic
  - `button.py` – Button entities and service registration
  - `codec.py` – RF packet builder (pure Python)
  - `config_flow.py` – UI setup flow
  - `const.py` – Constants and service names
  - `services.yaml` – Service descriptions
  - `translations/` – UI translations
- `fancli.py` – Standalone CLI and Python library for RF control
- `exp/` – Jupyter notebooks for protocol analysis

---

## License

MIT License. See `LICENSE` file for details.

---

## Credits

- Reverse engineering and integration by [@janabimustafa](https://github.com/janabimustafa)
- Not affiliated with the TR198A manufacturer or Broadlink.
