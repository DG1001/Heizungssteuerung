# Heizungsteuerung 

## Hintergrund

Ein guter Freund hat mich nach einer einfachen Heizungssteuerung gefragt. Er hat einen Raum, welchen er mit einen kleinen Heizlüfter zusätzlich beheizen will. Hier würde er gerne eine Temperatur festlegen, bei der der Lüfter angeschaltet wird (und über eine Hysterese wieder ausgeschaltet wird).

Es gibt zwar fertige und auch günstige Lösungen hierfür, mein Ansatz war jedoch eine offene und einfach zu erweiterende Lösung zu erstellen. Also mit Open Source Software und offenen Protokollen, so dass man dies auch einfach in eine Hausautomatisierung einbinden könnte. Und als Standalone Lösung mit Features wie Temperaturverlauf per Handyansicht.

Hinweis: Das Setup und die Konfiguration ist aufwendiger als propriatäre Lösungen und sollte von technisch versierten Personen vorgenommen werden. 

## Komponenten

![Kompnonenten](komponenten.png "Komponenten")

Folgende Komoponente habe ich verwendet (Amazon Links, die Produkte sind aber auch anderweitig zu bekommen):
* [WIFI Schaltsteckdose mit Open Source Tasmota Firmware](https://www.amazon.de/Steckdose-Stromz%C3%A4hler-Greensun-Stromverbrauch-Assistant/dp/B0CMLYL8FG)
* [Bluetooth Temperatur/Feuchte Sensor](https://www.amazon.de/Govee-Thermometer-Benachrichtigungs-Datenspeicherung-Gew%C3%A4chshaus/dp/B086YX1MKB)
* [ESP32-C3 Mini zur Steuerung](https://www.amazon.de/DUBEUYEW-Entwicklungsboard-unterst%C3%BCtzt-Bluetooth-kompatibel/dp/B0DMNBWTFD)
* [kleines Gehäuse für den 3D Drucker](https://www.thingiverse.com/thing:6653126)

Der Govee Sensor ist aus Erfahrung gut geeignet, da die Anbindung an den ESP32 prima klappt und das Gerät sehr robust gebaut ist (habe dies auch im Ausseneinsatz, obwohl eigentlich ein Indoor Sensor). Zusätzlich halten die Baterien recht lange.

Die Schaltsteckdose ist zwar etwas teuerer als andere WIFI Steckdosen, dafür ist die Fimrware komplett Open Source und kann problemlos aktualisiert werden. Es werden keine Daten in irgeneine Herstellercloud versendet und man benötigt auch keine extra App um die Steckdose zu konfigurieren.

Der ESP32-C3 ist eine sehr kostengünstige Lösung um WIFI und Bluetooth (zumindest BLE) einfach zu verbinden. Im direkten Versand aus Asien bekommt man das kleine Module schon ab 1,50€. Micropyhton eignet sich hervorragend für solche kleine Lösungen, ansonsten ist die Softwareentwicklung mit z.B. C und Visual Studio Code mit PlatformIO und dem Arduino Framework zu empfehlen. Inzwischen klappt hierbei auch gut die Verwendung einer KI zur unterstützung der Implementierung. Ich habe gute Erfahrungen mit Claude Code, Google Gemini, OpenAI Codex sowie dem Open Source Agenten 'Opencode' gemacht. 

Das 3D Gehäuse ist nicht unbedingt notwendig, sieht aber besser aus. Ich hab noch zusätzlich ein kleines Loch gebohrt um die rote Power-LED sichtbar zu machen.

## Setup

Der ESP32-C3 liest per Bluetooth die Temperatur vom Govee Sensor. Das Micropyhton Programm prüft regelmäßig die Temperatur und sendet per WIFI REST (HTTP) Call entsprechende Steuerbefehle an die Steckdose. 

Die aktuelle Implementierung basiert auf der Annahme, dass der ESP32 sowie die Tasmota Steckdose ins das lokale Netz eingebunden sind. Eine Erweiterung hierzu könnten eine komplette Standalone Lösung sein, d.h. der ESP32 öffnet einen Access Point an welchen sich die Steckdose verbindet. 

Für Micropyhton kann man einen Webinstaller verwenden (funktioniert nicht mit allen Browsern): https://bipes.net.br/flash/2025/, die passende Firmware findet man hier: https://micropython.org/download/ESP32_GENERIC_C3/

## Software

![Web Oberfläche](screenshot.png)

Die Micropyhton Software für den ESP32 wurde fast komplett mit Hilfe von Google Gemini 3 erstellt. Enthalten ist eine kleine Webpage, welche per u.a. Smartphone verwendet werden kann.



## Disclaimer

Anwendung auf eigene Gefahr. 

## Lizenz

MIT
