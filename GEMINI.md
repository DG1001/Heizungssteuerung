# GEMINI.md

## 1. Project Context & Goal

**Project Name:** ESP32 Govee-Tasmota Thermostat
**Goal:** Create a standalone heating control system using an ESP32-C3, a Govee BLE Thermometer, and a Tasmota Smart Plug. The ESP32 acts as the bridge and logic controller.

### Hardware Stack

* **Controller:** ESP32-C3 (RISC-V, MicroPython).
* **Sensor:** Govee H5075 (Square display, BLE).
* *Protocol:* Advertising Manufacturer Data (Company ID `0xEC88`).
* *Data:* 24-bit combined integer for Temp/Humidity.


* **Actuator:** Tasmota WiFi Smart Plug (Controller `82xx`, Tasmota v15).
* *Control Method:* HTTP GET requests (`/cm?cmnd=Power%20On`).



### Current Status

* **State:** Functional Async Prototype.
* **Features:**
* BLE Scanning (Passive) & Decoding.
* Hysteresis Control Loop (Target Temp + 1.0°C offset).
* Safety Sync (Forces defined state at boot).
* Async Webserver (Show status, set target temp, simple custom SVG graph).
* Persistent Settings (`settings.json`).



---

## 2. Technical Architecture

### Software Stack

* **Language:** MicroPython.
* **Core Library:** `uasyncio` (Cooperative multitasking).
* **Dependencies:** `bluetooth`, `network`, `socket`, `ujson`, `struct`.

### Logic Flow (Async Tasks)

1. **`BLEScanner`**: Scans for 10s, sleeps for 10s. Updates global `STATE`.
2. **`controller_loop`**: Checks `STATE` every 10s. Compares `current_temp` vs. `target_temp`. Sends HTTP requests to Tasmota if switching is needed. Includes "Safety Sync" to handle unknown boot states.
3. **`handle_client` (Webserver)**: Serves `index.html`, `chart.min.js` (if in STA mode, otherwise from local flash for AP mode), and JSON API (`/api/data`, `/api/set`).

### Data Structures

**Govee H5075 Decoding (Crucial):**
The H5075 encodes data in 3 bytes.

```python
raw = (mfg[3] << 16) | (mfg[4] << 8) | (mfg[5])
# Handle sign bit (23rd bit)
if raw & 0x800000: raw = (raw ^ 0x800000) * -1
# Formula
hum = (raw % 1000) / 10.0
temp = (raw - (raw % 1000)) / 10000.0

```

**Configuration (`settings.json`):**

```json
{
  "target_temp": 22.0,
  "hysteresis": 1.0,
  "wifi_ssid": "ESP32_Thermostat",
  "wifi_pass": "esp32tasmota",
  "tasmota_ip": "192.168.4.100",
  "govee_mac": "",
  "wifi_mode": "ap"
}

```



---

## 3. Roadmap & Development Plan

### Phase 1: Access Point Mode (Island Solution)

**Goal:** Run without external Router/Internet.

* **Changes:**
* ESP32 can switch between Station Mode (`STA_IF`) and Access Point Mode (`AP_IF`) via `settings.json`.
* When in AP mode, the ESP32 acts as an Access Point (SSID/Pass configured in `settings.json`).
* Configure Tasmota Plug to connect to ESP32's SSID.
* **Crucially:** Configure Tasmota Plug with a **static IP address** (e.g., `192.168.4.100`) to avoid conflicts with ESP32's DHCP server for other clients. This IP must then be set in `settings.json`.
* Custom SVG graph implemented, replacing Chart.js, to save space and remove external dependency.


* **Challenges:**
* **No NTP (Time):** Timestamps for the graph will be relative (boot time) or wrong (1970).


* **ToDo:**
* Implement `PulseTime` on Tasmota for hardware-level safety (watchdog).
* Add Watchdog Timer (WDT) on ESP32 in case of asyncio freeze.