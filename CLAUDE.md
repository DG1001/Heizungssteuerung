# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ESP32-C3 heating control system written in MicroPython. The ESP32 bridges a Govee H5075 BLE thermometer and a Tasmota WiFi smart plug to implement a thermostat. There is no build system, package manager, or test framework — the single source file (`src/main.py`) is deployed directly to the microcontroller.

## Deployment

Files are uploaded to the ESP32 via tools like `mpremote`, `ampy`, or Thonny IDE:

```bash
# Upload files to device
mpremote cp src/main.py :main.py
mpremote cp src/settings.json :settings.json

# Monitor serial output (REPL)
mpremote repl
```

The MicroPython firmware for ESP32-C3 is flashed separately via the web installer at https://bipes.net.br/flash/2025/ using firmware from https://micropython.org/download/ESP32_GENERIC_C3/

## Architecture

Everything runs in a single file (`src/main.py`) using `uasyncio` cooperative multitasking with four concurrent tasks:

1. **`BLEScanner`** — passive BLE scan for 10s, sleep 10s. Decodes Govee H5075 manufacturer data (Company ID `0xEC88`, 24-bit combined temp/humidity value). Updates global `STATE`.
2. **`controller_loop`** — runs every 10s. Applies hysteresis thermostat logic, sends HTTP GET commands to Tasmota plug. Shuts off heating if sensor data is stale (>180s).
3. **`mqtt_loop`** — STA mode only, skipped if `mqtt_broker` is empty. Connects to MQTT broker with user/password auth, publishes state JSON to `{mqtt_topic}/status` every `mqtt_publish_interval` minutes, subscribes to `{mqtt_topic}/set/target_temp` to receive target temperature updates. Reconnects automatically on failure. Uses `umqtt.simple` (must be available in MicroPython firmware).
4. **Web server** — async HTTP on port 80. Serves embedded HTML UI, `/api/data` (JSON with last 50 history points), `/api/set?target=X.X` (set target temp).

Global state is split into `SETTINGS` (persisted to `settings.json`) and `STATE` (runtime, in-memory). Temperature history is capped at 200 points (one per 60s).

## Configuration (`src/settings.json`)

```json
{
  "target_temp": 19.0,
  "hysteresis": 1.0,
  "wifi_ssid": "",
  "wifi_pass": "",
  "tasmota_ip": "",
  "govee_mac": "",
  "wifi_mode": "sta"
}
```

- `wifi_mode`: `"sta"` (connects to existing network) or `"ap"` (ESP32 creates its own AP at 192.168.4.1)
- `govee_mac`: leave empty for auto-detect; or specify as `"XX:XX:XX:XX:XX:XX"`
- In AP mode, Tasmota must be configured with a static IP (e.g., `192.168.4.100`) to avoid DHCP conflicts
- MQTT keys (`mqtt_broker`, `mqtt_port`, `mqtt_user`, `mqtt_pass`, `mqtt_topic`, `mqtt_publish_interval`) are STA-mode only; leave `mqtt_broker` empty to disable MQTT entirely

## Key Algorithms

**Govee H5075 decoding:**
```python
raw = (mfg[3] << 16) | (mfg[4] << 8) | mfg[5]
if raw & 0x800000: raw = (raw ^ 0x800000) * -1
hum = (raw % 1000) / 10.0
temp = (raw - (raw % 1000)) / 10000.0
```

**Hysteresis control:**
- Turn ON: `temp < target_temp`
- Turn OFF: `temp >= target_temp + hysteresis`

## Constraints

- **No external dependencies** — standard MicroPython library only. Do not add imports that require installing packages.
- **Memory limited** — SVG graph was chosen specifically to replace Chart.js. Avoid adding large inline resources.
- **No NTP in AP mode** — timestamps in the graph are relative to boot time (epoch 0) in AP mode.
- The web UI and API are embedded as strings inside `main.py` — there are no separate HTML/JS files.

## Tasmota Static IP (AP mode)

Run these commands in the Tasmota console:
```
IPAddress1 192.168.4.100
IPAddress2 192.168.4.1
IPAddress3 255.255.255.0
IPAddress4 192.168.4.1
WifiConfig 5
Restart 1
```
