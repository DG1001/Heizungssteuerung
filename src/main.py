# main.py (ESP32-C3)
# Features: BLE Thermostat, Webserver, Graphing, Persistent Config
import uasyncio as asyncio
import bluetooth
import network
import socket
import time
import struct
from micropython import const

try:
    import ujson as json
except ImportError:
    import json

# -------------------------------------------------------------------------
# KONFIGURATION & GLOBALE VARIABLEN
# -------------------------------------------------------------------------

# Feste Hardware-Settings
# WIFI_SSID = ""
# WIFI_PASS = ""
# TASMOTA_IP = "" # IP der Steckdose
TASMOTA_PORT = 80
# GOVEE_MAC = ""

# Standard-Werte (werden überschrieben, falls config.json existiert)
SETTINGS = {
    "target_temp": 22.0,   # Heizung AN unter diesem Wert
    "hysteresis": 1.0,      # Heizung AUS über (target + hysteresis)
    "wifi_ssid": "",
    "wifi_pass": "",
    "tasmota_ip": "",
    "govee_mac": "",
    "wifi_mode": "sta"
}

# Laufzeit-Daten (State)
STATE = {
    "current_temp": None,
    "current_hum": None,
    "batt": 0,
    "heating": None,       # None=Unbekannt, True=AN, False=AUS
    "last_update": 0,
    "history": []          # Liste für den Graphen: [(ts, temp), ...]
}

MAX_HISTORY_POINTS = 200 # Begrenzung der Historie, um RAM zu sparen

# -------------------------------------------------------------------------
# PERSISTENZ (Einstellungen speichern)
# -------------------------------------------------------------------------
def load_settings():
    try:
        with open("settings.json", "r") as f:
            data = json.load(f)
            SETTINGS.update(data)
            print("[SYS] Einstellungen geladen:", SETTINGS)
    except Exception as e:
        print("[SYS] Keine gespeicherten Einstellungen oder Fehler beim Laden, nutze Defaults.", e)

def save_settings():
    try:
        with open("settings.json", "w") as f:
            json.dump(SETTINGS, f)
            print("[SYS] Einstellungen gespeichert.")
    except Exception as e:
        print("[ERR] Speichern fehlgeschlagen:", e)

# -------------------------------------------------------------------------
# NETZWERK & TASMOTA HELFER
# -------------------------------------------------------------------------
async def wifi_connect():
    if SETTINGS.get("wifi_mode") == "ap":
        wlan = network.WLAN(network.AP_IF)
        wlan.config(essid=SETTINGS["wifi_ssid"], password=SETTINGS["wifi_pass"])
        wlan.active(True)
        # Static IP for the ESP32 AP
        wlan.ifconfig(('192.168.4.1', '255.255.255.0', '192.168.4.1', '8.8.8.8'))
        print("[WIFI] AP created, SSID:", SETTINGS["wifi_ssid"])
        print("[WIFI] IP Address:", wlan.ifconfig()[0])
    else:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        wlan.connect(SETTINGS["wifi_ssid"], SETTINGS["wifi_pass"])
        print("[WIFI] Verbinde...", end="")
        while not wlan.isconnected():
            print(".", end="")
            await asyncio.sleep(0.5)
        print("\n[WIFI] Verbunden:", wlan.ifconfig()[0])
    return wlan

async def tasmota_cmnd(cmnd):
    """Sendet HTTP Request asynchron (nicht blockierend)"""
    reader, writer = None, None
    try:
        # Asynchrone Verbindung öffnen
        reader, writer = await asyncio.open_connection(SETTINGS["tasmota_ip"], TASMOTA_PORT)
        
        cmnd_enc = cmnd.replace(" ", "%20")
        req = f"GET /cm?cmnd={cmnd_enc} HTTP/1.1\r\nHost: {SETTINGS['tasmota_ip']}\r\nConnection: close\r\n\r\n"
        
        writer.write(req.encode())
        await writer.drain()
        
        # Kurze Antwort lesen (wir brauchen nicht alles)
        line = await reader.readline()
        print(f"[TASMOTA] Cmd: {cmnd} -> {line}")
        
    except Exception as e:
        print(f"[ERR] Tasmota Fehler: {e}")
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except: pass

# -------------------------------------------------------------------------
# BLE LOGIC
# -------------------------------------------------------------------------
_ADV_TYPE_MFG = const(0xFF)

def decode_govee(payload):
    # H5075 Decoder
    mfg = None
    i = 0
    while i + 1 < len(payload):
        ln = payload[i]
        if ln == 0: break
        ad_type = payload[i+1]
        if ad_type == _ADV_TYPE_MFG:
            mfg = payload[i+2 : i+1+ln]
            break
        i += 1 + ln

    if not mfg or len(mfg) < 7: return None
    if mfg[0] != 0x88 or mfg[1] != 0xEC: return None

    raw = (mfg[3] << 16) | (mfg[4] << 8) | mfg[5]
    if raw & 0x800000: raw = (raw ^ 0x800000) * -1
    
    hum = (raw % 1000) / 10.0
    temp = ((raw - (raw % 1000)) / 10000.0)
    if raw < 0: temp = -temp # Sign fix logic depending on exact bit handling
    
    # Korrekter Negative-Check für H5075 (vorheriger Code war robuster)
    # Nutzen wir die Logik vom vorherigen funktionierenden Code:
    val_raw = (mfg[3] << 16) | (mfg[4] << 8) | mfg[5]
    is_neg = False
    if val_raw & 0x800000:
        is_neg = True
        val_raw = val_raw ^ 0x800000
    
    hum_part = val_raw % 1000
    temp_part = (val_raw - hum_part) / 10000.0
    temp_c = -temp_part if is_neg else temp_part
    
    return temp_c, hum_part/10.0, mfg[6]

class BLEScanner:
    def __init__(self):
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        self.scanning = False
        self.filter_mac = SETTINGS["govee_mac"].lower().replace("-", ":")

    def _irq(self, event, data):
        if event == 5: # SCAN_RESULT
            addr = data[1]
            adv = data[4]
            mac = ":".join("{:02x}".format(x) for x in addr).lower()
            
            # Mac Check (both orders)
            if self.filter_mac:
                mac_r = ":".join(reversed(mac.split(":")))
                if mac != self.filter_mac and mac_r != self.filter_mac:
                    return

            res = decode_govee(adv)
            if res:
                temp, hum, batt = res
                STATE["current_temp"] = temp
                STATE["current_hum"] = hum
                STATE["batt"] = batt
                STATE["last_update"] = time.time()
                print(f"[BLE] T={temp} H={hum} B={batt}")

    async def scan_loop(self):
        while True:
            # Scanne für 10 Sekunden
            self.scanning = True
            # gap_scan ist nicht-blockierend in Bezug auf IRQs, aber wir müssen warten
            self.ble.gap_scan(10000, 30000, 30000)
            await asyncio.sleep(10) 
            self.scanning = False
            # Pause
            await asyncio.sleep(10)

# -------------------------------------------------------------------------
# CONTROLLER TASK (Regelung)
# -------------------------------------------------------------------------
async def controller_loop():
    print("[CTRL] Regelung gestartet.")
    while True:
        # Alle 10 Sekunden prüfen
        await asyncio.sleep(10)
        
        if STATE["current_temp"] is None:
            continue

        # Historie füllen
        now = time.time()
        # Nur alle 60 sekunden einen Punkt speichern oder wenn leer
        if not STATE["history"] or (now - STATE["history"][-1][0]) > 60:
            STATE["history"].append((now, STATE["current_temp"]))
            if len(STATE["history"]) > MAX_HISTORY_POINTS:
                STATE["history"].pop(0)

        # Sicherheits-Check: Daten zu alt?
        if (now - STATE["last_update"]) > 180:
            print("[CTRL] Daten zu alt -> Not-AUS")
            if STATE["heating"] is not False: # Wenn nicht schon aus
                await tasmota_cmnd("Power Off")
                STATE["heating"] = False
            continue

        temp = STATE["current_temp"]
        target = SETTINGS["target_temp"]
        off_thresh = target + SETTINGS["hysteresis"]

        want_on = STATE["heating"] # Default: Status behalten

        if STATE["heating"] is True:
            # Wenn AN, warte bis wir über OFF_THRESH sind
            if temp >= off_thresh:
                want_on = False
        else: # AUS oder NONE
            # Wenn AUS, schalte AN wenn unter TARGET
            if temp < target:
                want_on = True
            # Sync beim Start: Wenn None und Temp > Target -> sicherstellen dass AUS
            elif STATE["heating"] is None:
                 want_on = False

        # Schalten falls nötig
        if want_on != STATE["heating"]:
            print(f"[CTRL] Schalte {'AN' if want_on else 'AUS'} (T={temp}, Ziel={target})")
            cmd = "Power On" if want_on else "Power Off"
            await tasmota_cmnd(cmd)
            # Wir setzen den Status optimistisch (angenommen es klappt)
            STATE["heating"] = want_on

# -------------------------------------------------------------------------
# WEBSERVER TASK
# -------------------------------------------------------------------------
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
 <title>Heizung ESP32</title>
 <meta name="viewport" content="width=device-width, initial-scale=1">
 <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
 <style>
  body { font-family: sans-serif; text-align: center; padding: 20px; background: #222; color: #fff; }
  .card { background: #333; padding: 20px; margin: 10px auto; border-radius: 10px; max-width: 600px; }
  h1 { color: #faa; }
  .val { font-size: 2em; font-weight: bold; }
  .status-on { color: #4f4; } .status-off { color: #888; }
  input { font-size: 1.2em; width: 80px; text-align: center; padding: 5px; }
  button { font-size: 1.2em; padding: 5px 20px; background: #faa; border: none; cursor: pointer; border-radius: 5px;}
 </style>
</head>
<body>
 <div class="card">
  <h1>Heizung Monitor</h1>
  <div>Temp: <span id="temp" class="val">--</span> &deg;C</div>
  <div>Ziel: <span id="target_disp">--</span> &deg;C</div>
  <div>Status: <span id="state" class="val">--</span></div>
  <br>
  <div>
   <input type="number" id="new_target" step="0.1" value="21.0">
   <button onclick="setTemp()">Setzen</button>
  </div>
 </div>
 <div class="card">
  <div id="graph" style="width:100%;height:200px;"></div>
 </div>

 <script>
  async function update() {
    try {
      let r = await fetch('/api/data');
      let d = await r.json();
      
      document.getElementById('temp').innerText = d.temp !== null ? d.temp.toFixed(2) : '--';
      document.getElementById('target_disp').innerText = d.target.toFixed(1);
      
      let st = document.getElementById('state');
      st.innerText = d.heating ? "HEIZT" : "AUS";
      st.className = d.heating ? "val status-on" : "val status-off";
      
      // Update SVG Graph
      if(d.history.length > 1) {
         renderSVG(d.history);
      }
    } catch(e) { console.log(e); }
  }

  function renderSVG(history) {
    const graphDiv = document.getElementById('graph');
    const width = graphDiv.clientWidth;
    const height = graphDiv.clientHeight;
    
    const temps = history.map(p => p[1]);
    const minTemp = Math.min(...temps);
    const maxTemp = Math.max(...temps);
    const tempRange = maxTemp - minTemp;
    
    const points = history.map((p, i) => {
        const x = (i / (history.length - 1)) * width;
        const y = tempRange === 0 ? height / 2 : height - ((p[1] - minTemp) / tempRange) * height;
        return `${x},${y}`;
    }).join(' ');

    const svg = `
      <svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
        <polyline points="${points}" style="fill:none;stroke:#faa;stroke-width:2" />
        <text x="5" y="15" fill="#fff">${maxTemp.toFixed(1)}</text>
        <text x="5" y="${height - 5}" fill="#fff">${minTemp.toFixed(1)}</text>
      </svg>
    `;
    graphDiv.innerHTML = svg;
  }

  async function setTemp() {
    let val = document.getElementById('new_target').value;
    await fetch('/api/set?target=' + val);
    update();
  }

  window.onload = function() {
    update();
    setInterval(update, 5000); // Alle 5 Sek Refresh
  };
 </script>
</body>
</html>
"""

async def handle_client(reader, writer):
    try:
        request_line = await reader.readline()
        method, path, _ = request_line.decode().split()
        
        # Leere Rest-Header
        while await reader.readline() != b'\r\n': pass

        if path == "/":
            writer.write('HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n'.encode())
            writer.write(HTML_PAGE.encode())
        
        elif path.startswith("/api/data"):
            # JSON Daten senden
            data = {
                "temp": STATE["current_temp"],
                "heating": STATE["heating"],
                "target": SETTINGS["target_temp"],
                "hysteresis": SETTINGS["hysteresis"],
                # History optimieren: Nur letzten 50 Punkte senden um Traffic klein zu halten
                "history": STATE["history"][-50:] 
            }
            writer.write('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n'.encode())
            writer.write(json.dumps(data).encode())

        elif path.startswith("/api/set"):
            # /api/set?target=22.5
            try:
                parts = path.split("?")[1].split("&")
                for p in parts:
                    k, v = p.split("=")
                    if k == "target":
                        SETTINGS["target_temp"] = float(v)
                        save_settings() # Speichern!
            except: pass
            
            writer.write('HTTP/1.1 200 OK\r\n\r\n'.encode())
            writer.write('OK'.encode())
            
        else:
            writer.write('HTTP/1.1 404 Not Found\r\n\r\n'.encode())

    except Exception as e:
        print(f"[WEB] Error: {e}")
    finally:
        try:
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        except: pass

async def main():
    load_settings()
    await wifi_connect()
    
    # Scanner instanzieren
    scanner = BLEScanner()
    
    # Tasks starten
    # 1. Webserver
    print("[SYS] Starte Webserver auf Port 80...")
    server = await asyncio.start_server(handle_client, '0.0.0.0', 80)
    
    # 2. BLE Loop & Controller Loop
    # Wir benutzen gather um alles gleichzeitig laufen zu lassen
    await asyncio.gather(
        scanner.scan_loop(),
        controller_loop(),
        server.wait_closed()
    )

try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Beendet.")