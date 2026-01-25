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
* Async Webserver (Show status, set target temp, simple Chart.js graph).
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
3. **`handle_client` (Webserver)**: Serves `index.html` and JSON API (`/api/data`, `/api/set`).

### Data Structures

**Govee H5075 Decoding (Crucial):**
The H5075 encodes data in 3 bytes.

```python
raw = (mfg[3] << 16) | (mfg[4] << 8) | mfg[5]
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
  "hysteresis": 1.0
}

```



---

## 3. Roadmap & Development Plan

### Phase 1: Access Point Mode (Island Solution)

**Goal:** Run without external Router/Internet.

* **Changes:**
* Switch ESP32 from Station Mode (`STA_IF`) to Access Point Mode (`AP_IF`).
* Configure Tasmota Plug to connect to ESP32's SSID.
* Configure ESP32 to assign/expect a static IP for Tasmota.


* **Challenges:**
* **No Internet for Chart.js:** The CDN link in HTML will fail.
* **No NTP (Time):** Timestamps for the graph will be relative (boot time) or wrong (1970).


* **ToDo:**
* Implement `Chart.min.js` serving from local ESP flash.
* Update `wifi_connect` to handle AP creation.



### Phase 2: Refinements

* Implement `PulseTime` on Tasmota for hardware-level safety (watchdog).
* Add Watchdog Timer (WDT) on ESP32 in case of asyncio freeze.