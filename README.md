# HAFAS Bus Monitor für Home Assistant

Eine HACS-kompatible Home-Assistant-Custom-Integration für **Busabfahrten auf Basis von HAFAS**. Sie wurde für das **NAH.SH-HAFAS** (Schleswig-Holstein, z. B. Kiel) gebaut und ist dort ohne API-Key nutzbar.

Die Integration beantwortet zwei Fragen:

1. **Wann fährt mein Bus?** – pro Haltestelle/Kachel, gefiltert nach Linien und Zielen.
2. **Welcher Bus ist nach der Schule der schnellste?** – Vergleich mehrerer Haltestellen inklusive Fußweg.

> **Hinweis:** HAFAS ist ein System des Herstellers HaCon. Die NAH.SH-Schnittstelle ist eine öffentliche Fahrplan-Schnittstelle, keine offiziell dokumentierte, garantierte API. Endpunkte können sich ändern. Die Integration fragt standardmäßig alle **30 Sekunden** ab, aber nur zwischen **06:00 und 22:00 Uhr** und optional nicht in den Schulferien. Bitte die öffentliche API fair nutzen.

---

## Funktionen

- **Haltestellensuche** über Stadt + Suchbegriff (z. B. `Kiel` + `Hospitalstraße`)
- **Auswahl aus mehreren HAFAS-Treffern**
- **Pro Kachel/Haltestelle:** Stadt, Haltestelle, mehrere Linien, Fußweg
- **Ziele pro Linie auswählen** – die Integration fragt die nächsten 12 Stunden ab und zeigt die tatsächlich angefahrenen Ziele als Auswahl
- **Kachel-State** zeigt Linie, Ziel und Zeit: unter 20 Minuten `61 | Mettenhof · in 4 min`, ab 20 Minuten `61 | Mettenhof · 15:22` (der Haltestellenname steht im Entity-Namen)
- **Stabile Linienfarben** über `line_color`/`line_colors` – dieselbe Linie hat überall dieselbe Farbe
- **Nur erreichbare Abfahrten** im Dashboard: Abfahrten, für die der Fußweg nicht mehr reicht, werden aus `departures` herausgefiltert
- **Sehr detaillierte Attribute** inklusive Echtzeit, Verspätung, Steig, Fußweg, Losgehzeit und allen HAFAS-Rohfeldern, die die Integration parst
- **Sensor „Schnellste Verbindung“** mit Fußweg-Vergleich
- **GPS-Sensor „Nächste Haltestelle“** – findet die nächste eingerichtete Haltestelle per Handy-Standort
- **Aktualisierung alle 30 Sekunden**, ausschließlich **06:00–22:00**
- **Ferienmodus-Switch** `switch.hafas_ferienmodus` und optionaler Ferien-Sensor; bei aktiv pausiert die Abfrage (`Ferien`)
- **Hinzufügen-Button** für beliebig viele Kacheln; jede Kachel ist ein eigener Config-Subentry und editierbar
- **Service** `hafas_bus_monitor.refresh`
- **Keine externen Python-Abhängigkeiten** (nutzt `aiohttp` aus Home Assistant)

---

## Unterstütztes Netz

| Feld | Wert |
|---|---|
| HAFAS-Deployment | NAH.SH (Nahverkehrsverbund Schleswig-Holstein) |
| Endpunkt | `https://nahsh.hafas.cloud/gate` (Fallback: `https://nah.sh.hafas.de/bin/mgate.exe`) |
| Zeitraum | Schleswig-Holstein, u. a. Kiel, Lübeck, Flensburg, Eutin |
| Produktfilter | Busse und On-call-Busse (Bitmaske 544) |

Für andere HAFAS-Betreiber müssten `HAFAS_ENDPOINT`, `HAFAS_CLIENT`, `HAFAS_AUTH` und ggf. die Produkt-Bitmaske in [`const.py`](custom_components/hafas_bus_monitor/const.py) angepasst werden. Getestet ist der NAH.SH-Endpunkt.

---

## Installation

### Variante A: HACS (Custom Repository)

1. In Home Assistant **HACS → Integrationen** öffnen.
2. Oben rechts auf **⋮ → Benutzerdefinierte Repositories** klicken.
3. URL eintragen:

   ```text
   https://github.com/TechnoLau/hafas-bus-monitor
   ```

4. Kategorie **Integration** wählen – **nicht** Dashboard, App oder Frontend.
5. Nach `HAFAS Bus Monitor` suchen und installieren.
6. Home Assistant neu starten.
7. **Einstellungen → Geräte & Dienste → Integration hinzufügen → HAFAS Bus Monitor**.

### Variante B: Manuell

```bash
# Im Home-Assistant-Konfigurationsverzeichnis
cd /config
mkdir -p custom_components
cp -r /pfad/zu/hafas-bus-monitor/custom_components/hafas_bus_monitor custom_components/
```

Danach Home Assistant neu starten und die Integration über die UI hinzufügen.

### Voraussetzungen

- Home Assistant **2025.4** oder neuer
- Internetzugang zu `nahsh.hafas.cloud`
- Kein API-Key erforderlich

---

## Einrichtung

### 1. Integration anlegen

Beim ersten Hinzufügen wird **noch keine Haltestelle** abgefragt. Es entsteht nur der zentrale HAFAS-Bus-Monitor-Eintrag mit globalen Einstellungen:

| Feld | Bedeutung | Beispiel |
|---|---|---|
| **Vorschau-Fenster** | Wie weit HAFAS in die Zukunft sucht | `60` Minuten |
| **Aktualisierungsintervall** | Polling-Intervall (Minimum 30 s) | `30` Sekunden |
| **Schnellste-Verbindung-Sensor** | Routing-Sensor anlegen | `an` |
| **Ferien-Sensor (optional)** | `binary_sensor`/`input_boolean`, `on` = Ferien | `input_boolean.schulferien` |
| **Handy-/Geräte-Tracker (optional)** | `device_tracker`/`person` mit GPS-Koordinaten | `device_tracker.handy` |
| **Ferienmodus-Switch** | separat schaltbar, pausiert ebenfalls | `switch.hafas_ferienmodus` |

Nach dem Anlegen erscheint die Integration unter **Einstellungen → Geräte & Dienste**. Dort gibt es den Button **Hinzufügen** für Haltestellen/Kacheln. Damit lassen sich beliebig viele Entitäten anlegen – eine pro Kachel.

### 2. Haltestelle/Kachel hinzufügen

Der Button **Hinzufügen** öffnet den schrittweisen Dialog:

1. **Stadt auswählen** – z. B. `Kiel`
2. **Haltestelle** – Suchbegriff, z. B. `Hospitalstraße`; bei mehreren Treffern folgt eine Auswahl
3. **Busse** – eine oder mehrere Linien, z. B. `61, 62`
4. **Ziel pro Bus** – für jede Linie werden die HAFAS-Ziele der nächsten 12 Stunden angezeigt:
   - ein oder mehrere Ziele auswählen
   - **keine Auswahl** oder **„Alle Ziele / alle Richtungen“** = alle Ziele dieser Linie
   - wird kein Ziel gefunden, entfällt der Schritt
5. **Fußweg** – Minuten bis zum Steig; danach wird die Kachel angelegt

Die Ziele werden pro Linie gespeichert, z. B.:

```yaml
line_targets:
  "61": ["Mettenhof"]
  "62": ["Russee"]
```

### 3. Weitere Kacheln

Den Button **Hinzufügen** einfach erneut drücken. Jede Haltestelle wird eine eigene Sensor-Entität/Kachel, z. B.:

- `sensor.hafas_hospitalstrasse`
- `sensor.hafas_kunsthalle`

Der Routing-Sensor `sensor.hafas_schnellste_verbindung` vergleicht alle Kacheln.

### 4. Bearbeiten und Löschen

Jede Kachel ist ein eigener **Config-Subentry** und kann auf der Integrationsseite direkt bearbeitet oder gelöscht werden. Die globalen Einstellungen (Intervall, Vorschau, Routing, Ferien-Sensor) erreichst du über **Konfigurieren**.

Die Einrichtung erfolgt vollständig über die Home-Assistant-Oberfläche. Es ist **kein YAML in `configuration.yaml`** erforderlich; die YAML-Beispiele hier betreffen nur Dashboard und Automationen.

> **Hinweis:** Durch die Subentries wird Home Assistant **2025.4** oder neuer benötigt. Ein zentraler Eintrag verwaltet alle Kacheln (`single_config_entry`).

### 5. Nächste Haltestelle per GPS (optional)

In den globalen Einstellungen kann ein `device_tracker` oder eine `person`-Entität mit GPS-Koordinaten ausgewählt werden. Dann legt die Integration automatisch an:

```text
sensor.hafas_naechste_haltestelle
```

Dieser Sensor:

- ermittelt aus den GPS-Koordinaten die **nächste bereits eingerichtete Haltestelle**
- zeigt deren nächste erreichbare Abfahrt, z. B.:
  ```text
  Hospitalstraße: 61 | Mettenhof · in 4 min
  ```
- liefert `distance_m`, `stop`, `walking_minutes`, `departures` und `next_departure` als Attribute
- ignoriert Haltestellen, die nicht als Kachel eingerichtet sind
- zeigt `Tracker nicht gefunden`, wenn die Entität fehlt
- zeigt `Keine GPS-Koordinaten`, wenn der Tracker keine `latitude`/`longitude`-Attribute liefert
- nutzt bei `state == home` ohne GPS-Attribute die Koordinaten von `zone.home` als Fallback
- liefert `tracker_state` und `position_source` als Diagnose-Attribute

Der Sensor wird bei jeder Aktualisierung neu berechnet; die normale 30-Sekunden-Aktualisierung genügt also auch für Standortwechsel.

---

## Aktualisierung, Ruhezeit und Ferien

- Das Polling läuft standardmäßig alle **30 Sekunden**.
- Es läuft nur zwischen **06:00 und 22:00 Uhr** (Zeitzone `Europe/Berlin`).
- Außerhalb dieser Zeit zeigt der Sensor `Ruhezeit` und es werden keine HAFAS-Anfragen gesendet.
- Ist ein **Ferien-Sensor** konfiguriert und steht auf `on`, zeigt der Sensor `Ferien`; es wird nicht abgefragt.
- Zusätzlich gibt es den Switch **`switch.hafas_ferienmodus`** („Ferienmodus“). Er pausiert die Abfrage manuell und merkt sich seinen Zustand über einen Neustart.
- Der Switch hat einen klaren Entitätsnamen; sein Zustand ist `on`/`off` und wird von Home Assistant als Ein/Aus angezeigt.
- Ohne Ferien-Sensor/Switch wird auch in den Ferien abgefragt. Die Integration kann Schulferien nicht bundesweit automatisch kennen; dafür einen eigenen `binary_sensor`/`input_boolean` oder den Switch verwenden.

Beispiel für einen manuellen Helfer:

```yaml
input_boolean:
  schulferien:
    name: Schulferien
    icon: mdi:school
```

Diesen Helfer in der Integration als Ferien-Sensor auswählen. Für automatische Ferien kann ein Template-Binary-Sensor auf Basis eines Kalenders verwendet werden:

```yaml
template:
  - binary_sensor:
      - name: Schulferien
        state: >-
          {{ is_state('calendar.schulferien', 'on') }}
```

---

## Entitäten

Die Entity-IDs werden aus dem Haltestellennamen abgeleitet (Stadtpräfix wird entfernt):

| Entität | Beispiel |
|---|---|
| Haltestellen-Sensor/Kachel | `sensor.hafas_hospitalstrasse` |
| Haltestellen-Sensor/Kachel | `sensor.hafas_kunsthalle` |
| Routing-Sensor | `sensor.hafas_schnellste_verbindung` |
| Ferienmodus | `switch.hafas_ferienmodus` |
| Nächste Haltestelle per GPS | `sensor.hafas_naechste_haltestelle` |

### 1. Haltestellen-Sensor (Kachel)

**State:**

Unter 20 Minuten Restzeit:

```text
61 | Mettenhof · in 4 min
```

Ab 20 Minuten Restzeit:

```text
61 | Mettenhof · 15:22
```

Der Entity-Name ist nur der Haltestellenname, z. B. **Hospitalstraße**. Die Kachel zeigt damit Haltestelle (Name), Linie, Ziel und Abfahrtszeit.

Weitere Zustände:

| Zustand | Bedeutung |
|---|---|
| `Keine erreichbare Abfahrt` | Keine Abfahrt im Vorschau-Fenster, für die der Fußweg reicht |
| `Ruhezeit` | Außerhalb von 06:00–22:00 Uhr |
| `Ferien` | Ferien-Sensor ist `on` |
| `unknown` | Keine Daten, z. B. bei einem Fehler |

**Attribute:**

| Attribut | Inhalt |
|---|---|
| `stop` / `stop_id` / `city` | Haltestelle und Stadt |
| `lines` | Linienfilter |
| `line_targets` | Ziele pro Linie |
| `line_colors` | Stabile Farbe pro Linie, z. B. `{"61": "#3cb44b", "62": "#4363d8"}` |
| `walking_minutes` | Fußweg |
| `scan_minutes` | Vorschau-Fenster |
| `departures` | **Nur erreichbare** Abfahrten der gewählten Linien/Ziele (max. 12) |
| `unreachable_departures` | Passende Abfahrten, für die der Fußweg **nicht** reicht (max. 4) |
| `all_departures` | Alle Busse im Fenster (ungefiltert, Transparenz/Debug, max. 8) |
| `departure_count` | Anzahl der erreichbaren Abfahrten |
| `next_departure` | Nächste erreichbare Abfahrt als vollständiges Objekt |
| `minutes_until_departure` | Minuten bis zur nächsten erreichbaren Abfahrt (für Automationen) |
| `last_update` | Zeitpunkt des HAFAS-Abrufs (ISO 8601) |
| `error` | Letzter Fehler dieser Haltestelle, falls vorhanden |
| `paused_reason` | `holiday` oder `outside_hours` |
| `active_hours` | `06:00–22:00` |
| `paused` | `true`/`false` |

Jede Abfahrt in `departures`, `unreachable_departures` und `all_departures` enthält:

```yaml
line: "61"
line_name: "Bus 61"
line_id: "de:NAHSH:01002|61:"
destination: "Mettenhof"
departure_time: "2026-11-03T15:22:00+01:00"
departure_time_local: "15:22"
planned_departure_time: "2026-11-03T15:20:00+01:00"
planned_departure_time_local: "15:20"
delay: 2
delay_minutes: 2
delay_seconds: 120
minutes_until_departure: 4
walking_minutes: 3
leave_in_minutes: 1
reachable: true
platform: "A"
cancelled: false
realtime: true
trip_id: "..."
stop_name: "Kiel Hospitalstraße"
display_short: "61 | Mettenhof · 15:22"
line_destination: "61 | Mettenhof"
time_text: "in 4 min"
line_color: "#3cb44b"
```

Damit lassen sich eigene Karten, Tabellen oder Automationen bauen. `departures` ist bereits nach **Linie**, **Ziel** und **Fußweg** gefiltert.

### 2. Routing-Sensor „Schnellste Verbindung“

**State:** Zum Beispiel:

```text
Linie 61 ab Kunsthalle in 4 min
```

Ab 20 Minuten Restzeit:

```text
Linie 61 ab Kunsthalle um 15:45
```

Bei Pause:

```text
Ferien
```

oder:

```text
Ruhezeit
```

**Attribute:**

| Attribut | Inhalt |
|---|---|
| `best` | Gewählte Verbindung |
| `options` | Alle geprüften Haltestellen mit Ergebnis/Grund |
| `reason` | `no_departures`, `no_catchable_departure`, ... |
| `selection_method` | Erklärung der Auswahl |
| `stops` | Konfigurierte Haltestellen, Fußwege, Linien, Ziele |
| `last_update` | Zeitpunkt des Abrufs |
| `paused_reason` | `holiday`/`outside_hours` |
| `active_hours` | `06:00–22:00` |

`best` enthält u. a.:

```yaml
line: "61"
destination: "Mettenhof"
stop: "Kiel Kunsthalle"
stop_short: "Kunsthalle"
walk_minutes: 6
minutes_until: 4
time_text: "in 4 min"
leave_in_minutes: 0
departure_time_local: "15:22"
delay: 0
platform: "A"
catchable: true
line_targets:
  "61": ["Mettenhof"]
line_color: "#3cb44b"
```

### Wie das Routing rechnet

Für jede Haltestelle wird die **früheste Abfahrt** gesucht, die mit dem konfigurierten Fußweg noch erreichbar ist:

```text
Restminuten bis Abfahrt >= Fußweg in Minuten
```

Von den erreichbaren Abfahrten gewinnt die **früheste tatsächliche Abfahrtszeit** (Echtzeit, falls vorhanden). Bei gleicher Abfahrtszeit gewinnt der kürzere Fußweg.

`leave_in_minutes` sagt, wann man losgehen sollte:

```text
leave_in_minutes = max(0, Restminuten bis Abfahrt - Fußweg)
```

Die Ziel-Filter pro Linie werden bereits beim HAFAS-Abruf berücksichtigt. Dadurch vergleicht der Routing-Sensor nur Busse, die auch in die gewünschte Richtung fahren.

**Wichtig:** Die Integration kennt keine Fahrzeit bis zum endgültigen Ziel. Sie vergleicht die Abfahrt, nicht die Ankunft.

---

## Dashboard-Beispiel (Lovelace Markdown)

Das folgende Beispiel zeigt die **erreichbaren** Abfahrten inklusive Linie, Ziel, Uhrzeit, Restminuten, Fußweg und Losgehzeit. Es funktioniert ohne zusätzliche HACS-Karten.

```yaml
type: markdown
title: Busse ab Hospitalstraße
content: |
  {% set departures = state_attr('sensor.hafas_hospitalstrasse', 'departures') or [] %}
  {% if departures %}
  {% for dep in departures[:6] %}
  - <span style="color: {{ dep.line_color }}">●</span> **{{ dep.line_destination }}** · **{{ dep.time_text }}** · Fußweg {{ dep.walking_minutes }} Min · los in {{ dep.leave_in_minutes }} Min{% if dep.delay > 0 %} · +{{ dep.delay }} Min{% elif dep.delay < 0 %} · {{ dep.delay }} Min{% endif %}
  {% endfor %}
  {% else %}
  Keine erreichbare Abfahrt im Vorschau-Fenster.
  {% endif %}
```

### Kombinierte Ansicht mit Routing

```yaml
type: vertical-stack
cards:
  - type: markdown
    title: Schnellster Bus
    content: |
      {% set best = state_attr('sensor.hafas_schnellste_verbindung', 'best') %}
      {% if best %}
      ## {{ states('sensor.hafas_schnellste_verbindung') }}

      <span style="color: {{ best.line_color }}">●</span> **Ziel:** {{ best.destination }}  
      **Fußweg:** {{ best.walk_minutes }} Min  
      **Losgehen in:** {{ best.leave_in_minutes }} Min  
      **Steig:** {{ best.platform or '–' }}{% if best.delay > 0 %} · +{{ best.delay }} Min{% endif %}
      {% else %}
      Keine erreichbare Verbindung im Vorschau-Fenster.
      {% endif %}

  - type: markdown
    title: Nächste Haltestelle (GPS)
    content: |
      **{{ states('sensor.hafas_naechste_haltestelle') }}**

      {% set nearest = state_attr('sensor.hafas_naechste_haltestelle', 'departures') or [] %}
      Entfernung: {{ state_attr('sensor.hafas_naechste_haltestelle', 'distance_m') }} m
      {% for dep in nearest[:5] %}
      - <span style="color: {{ dep.line_color }}">●</span> **{{ dep.line_destination }}** · **{{ dep.time_text }}**
      {% endfor %}

  - type: markdown
    title: Busse ab Kunsthalle
    content: |
      {% set departures = state_attr('sensor.hafas_kunsthalle', 'departures') or [] %}
      {% if departures %}
      {% for dep in departures[:5] %}
      - <span style="color: {{ dep.line_color }}">●</span> **{{ dep.line_destination }}** · **{{ dep.time_text }}** · Fußweg {{ dep.walking_minutes }} Min
      {% endfor %}
      {% else %}
      Keine erreichbare Abfahrt.
      {% endif %}
```

### Detailansicht „alle Daten“

`all_departures` enthält alle Busse im Fenster, auch nicht gewählte Linien und nicht erreichbare Abfahrten. `unreachable_departures` enthält nur die passenden Linien/Ziele, für die der Fußweg zu kurz ist.

```yaml
type: markdown
title: HAFAS-Detaildaten Hospitalstraße
content: |
  {% set all = state_attr('sensor.hafas_hospitalstrasse', 'all_departures') or [] %}
  {% for dep in all %}
  - <span style="color: {{ dep.line_color }}">●</span> {{ dep.departure_time_local }} · {{ dep.line_destination }} · {{ dep.time_text }} · Steig {{ dep.platform or '–' }} · Delay {{ dep.delay }} Min · Echtzeit {{ dep.realtime }} · erreichbar {{ dep.reachable }}
  {% endfor %}
```

### Linienfarben

Jede Abfahrt enthält `line_color`, jede Kachel zusätzlich `line_colors`. Die Farbe wird deterministisch aus der Liniennummer berechnet: **Linie 61 hat an jeder Haltestelle und in jedem Dashboard dieselbe Farbe.**

- Für eigene Karten/Diagramme: `dep.line_color` bzw. `state_attr('sensor.hafas_hospitalstrasse', 'line_colors')` verwenden.
- Der normale Home-Assistant-History-Graph färbt **Entitäten**, nicht einzelne Linien. Für linienbasierte Graphen eine Karte verwenden, die `line_color` auswertet (z. B. ApexCharts mit `data_generator`).

> Passe die Entity-IDs an, falls deine Haltestellen anders heißen. Die ID findest du unter **Einstellungen → Geräte & Dienste → Entitäten**.

---

## Automation „Schulschluss“

Die Automation prüft nach Schulende automatisch, ob **Hospitalstraße** oder **Kunsthalle** die schnellere Option ist, und schickt das Ergebnis per Push.

### Voraussetzungen

- Beide Haltestellen sind im HAFAS-Bus-Monitor-Eintrag konfiguriert.
- Der Routing-Sensor ist aktiviert.
- Ein Benachrichtigungsdienst existiert, z. B. `notify.mobile_app_schulkind`.
- Optional: ein Ferien-Sensor; die Integration pausiert dann selbst.

### Komplette Automation

```yaml
alias: Schulschluss – schnellster Bus
description: >-
  Prüft nach Schulende, ob die Hospitalstraße oder die Kunsthalle
  die schnellere Busverbindung bietet, und sendet eine Push-Nachricht.
trigger:
  - platform: time
    at: "13:15:00"
condition:
  - condition: time
    weekday:
      - mon
      - tue
      - wed
      - thu
      - fri
  - condition: template
    value_template: >-
      {{ states('sensor.hafas_schnellste_verbindung')
         not in ['unknown', 'unavailable', 'Keine Verbindung', 'Ferien', 'Ruhezeit'] }}
action:
  - service: hafas_bus_monitor.refresh
  - delay: "00:00:03"
  - variables:
      best: "{{ state_attr('sensor.hafas_schnellste_verbindung', 'best') }}"
      message: >-
        {% if best %}
        Nimm Linie {{ best.line }} ab {{ best.stop_short }}.
        Abfahrt {{ best.departure_time_local }} Uhr, noch {{ best.minutes_until }} Minuten.
        Fußweg {{ best.walk_minutes }} Minuten – losgehen in {{ best.leave_in_minutes }} Minuten.
        Ziel: {{ best.destination }}.
        {% if best.delay > 0 %}({{ best.delay }} Minuten Verspätung){% endif %}
        {% else %}
        Keine erreichbare Verbindung im Vorschau-Fenster.
        {% endif %}
  - service: notify.mobile_app_schulkind
    data:
      title: "Schnellster Bus"
      message: "{{ message }}"
      data:
        tag: hafas_school_bus
        channel: Schule
mode: single
```

### Anpassen

- `13:15:00` durch das tatsächliche Schulende ersetzen.
- `notify.mobile_app_schulkind` durch den eigenen Notify-Service ersetzen.
- Für unregelmäßige Schulschlusszeiten einen Kalender-Trigger oder einen Helper (`input_datetime.schulende`) verwenden.
- `delay: 3` gibt dem Coordinator Zeit, den State nach dem Refresh zu aktualisieren.
- Die Bedingung schließt `Ferien` und `Ruhezeit` bereits aus.

### Alternative: Automation nur bei Änderung

```yaml
trigger:
  - platform: state
    entity_id: sensor.hafas_schnellste_verbindung
condition:
  - condition: time
    after: "13:00:00"
    before: "13:30:00"
    weekday: [mon, tue, wed, thu, fri]
  - condition: template
    value_template: >-
      {{ states('sensor.hafas_schnellste_verbindung')
         not in ['unknown', 'unavailable', 'Keine Verbindung', 'Ferien', 'Ruhezeit'] }}
action:
  - service: notify.mobile_app_schulkind
    data:
      title: "Schnellster Bus"
      message: "{{ states('sensor.hafas_schnellste_verbindung') }}"
mode: single
```

---

## Service

### `hafas_bus_monitor.refresh`

Fordert sofort frische Daten für alle konfigurierten Haltestellen an.

```yaml
service: hafas_bus_monitor.refresh
```

Der Service hat keine Felder. Außerhalb von 06:00–22:00 bzw. bei Ferien bleibt der Sensor im Pause-Zustand.

---

## Wie die Daten abgerufen werden

1. **LocMatch** löst `Stadt + Haltestelle` in eine HAFAS-Location-ID auf.
2. **StationBoard** liefert die nächsten Busabfahrten im Vorschau-Fenster.
3. Beim Einrichten werden für die gewählten Linien die Ziele der nächsten 12 Stunden ermittelt.
4. Die Integration filtert lokal nach Linien und pro Linie nach Zielen.
5. Echtzeitdaten (`dTimeR`) werden verwendet, falls vorhanden; andernfalls gilt die Planzeit (`dTimeS`).
6. Verspätung = Echtzeit minus Planzeit.
7. Der Sensor berechnet aus Fußweg und Abfahrtszeit, welche Abfahrten erreichbar sind.

Die HAFAS-Antwort wird defensiv geparst: fehlende Felder, abweichende Plattform-Schreibweisen und Abfahrten nach Mitternacht werden abgefangen.

---

## Troubleshooting

### „Keine Haltestelle gefunden“

- Kürzeren Suchbegriff verwenden (`Hospital` statt `Hospitalstraße Kiel`).
- Stadt prüfen (NAH.SH deckt Schleswig-Holstein ab, nicht ganz Deutschland).
- Sonderzeichen/ß/ä/ö/ü funktionieren normalerweise; ggf. Schreibweise variieren.

### Kachel zeigt `Keine erreichbare Abfahrt`

- Im Vorschau-Fenster fährt keine passende Linie zum gewählten Ziel.
- Fußweg zu groß: Eine Abfahrt in 2 Minuten ist bei 5 Minuten Fußweg nicht erreichbar.
- Linien-/Ziel-Filter prüfen; `unreachable_departures` und `all_departures` ansehen.
- Vorschau-Fenster erhöhen.

### Kachel zeigt `Ruhezeit`

- Es ist vor 06:00 oder nach 22:00 Uhr. Das ist beabsichtigt; es werden keine HAFAS-Anfragen gesendet.

### Kachel zeigt `Ferien`

- Der konfigurierte Ferien-Sensor ist `on`. Die Abfrage ist pausiert.

### Kachel zeigt `unavailable`

- HAFAS-Endpunkt nicht erreichbar, Timeout oder API-Fehler.
- Logs prüfen: **Einstellungen → System → Protokolle**, nach `hafas_bus_monitor` filtern.
- Bei nur einer fehlerhaften Haltestelle bleiben die anderen Sensoren verfügbar.

### Ziele werden beim Einrichten nicht angeboten

- In den nächsten 12 Stunden fährt die Linie nicht oder HAFAS liefert keine Ziele.
- Der Auswahlschritt wird dann übersprungen; die Linie zeigt alle Ziele.
- Später die Kachel auf der Integrationsseite bearbeiten (Zeilen/Ziele/Fußweg) oder löschen und neu hinzufügen.

### Falsche Entität / ID

- Entity-IDs werden beim ersten Anlegen aus dem Namen erzeugt.
- Unter **Einstellungen → Geräte & Dienste → Entitäten** umbenennen.
- Dashboard/Automation entsprechend anpassen.

### Eine Fahrtrichtung fehlt

- Wenn pro Linie nur ein Ziel ausgewählt wurde, wird logischerweise nur diese Richtung angezeigt.
- Kachel bearbeiten und beim Ziel **„Alle Ziele / alle Richtungen“** auswählen oder die Zielauswahl leeren.
- Ohne Ziel-Auswahl werden alle Richtungen der Linie angezeigt.
- `all_departures` prüfen: Dort stehen alle Busse, die HAFAS für die Haltestelle liefert.
- HAFAS liefert nur Richtungen, die die Haltestelle im Abfragefenster tatsächlich bedienen. Alle zugehörigen Steige der gewählten Haltestelle werden über die HAFAS-Haltestellen-ID abgefragt.

### „Diese Haltestelle ist bereits eingerichtet“

- Jede Haltestelle darf pro Eintrag nur einmal vorkommen.
- Für eine weitere Haltestelle den Button **Hinzufügen** auf der Integrationsseite verwenden.

### HAFAS-Endpunkt hat sich geändert

- `HAFAS_ENDPOINT` und `HAFAS_FALLBACK_ENDPOINT` in [`const.py`](custom_components/hafas_bus_monitor/const.py) anpassen.
- Die Integration nutzt zuerst den Cloud-Endpunkt und fällt bei Verbindungsfehlern auf den alten `mgate.exe`-Endpunkt zurück.

### Rate Limits / zu viele Anfragen

- Standard: 30 Sekunden, nur 06:00–22:00, optional Ferienpause.
- Bei zwei Haltestellen sind das bis zu vier HAFAS-Anfragen pro Minute.
- Die API ist ein öffentlicher Dienst. Bei 429/Fehlern wird der Sensor `unavailable`; das nächste Intervall versucht es erneut.
- Wer es ruhiger braucht, kann das Intervall unter **Konfigurieren** auf 60–300 Sekunden erhöhen.

---

## Datenschutz und Nutzung

- Es werden nur Haltestellen-Suchbegriffe und Abfahrtsanfragen an NAH.SH/HAFAS gesendet.
- Keine API-Keys, keine Standortdaten, keine Benutzerkonten.
- Die Integration speichert Haltestellen-ID, Namen, Linien-/Ziel-Filter und Einstellungen in der Home-Assistant-Konfiguration.
- Bitte die HAFAS-Schnittstelle fair nutzen.

---

## GitHub-Veröffentlichung

Das Repository ist veröffentlicht:

**https://github.com/TechnoLau/hafas-bus-monitor**

Die [`manifest.json`](custom_components/hafas_bus_monitor/manifest.json) ist auf `@TechnoLau` und die Repository-URL konfiguriert. Der User-Agent in [`const.py`](custom_components/hafas_bus_monitor/const.py) enthält ebenfalls den Projektlink.

### In HACS installieren

1. **HACS → Integrationen → ⋮ → Benutzerdefinierte Repositories**
2. URL `https://github.com/TechnoLau/hafas-bus-monitor` eintragen.
3. Kategorie **Integration** wählen.
4. Installieren und Home Assistant neu starten.

### Updates veröffentlichen

```bash
cd hafas-bus-monitor

git add .
git commit -m "Beschreibung der Änderung"
git push

git tag v3.3.4
git push origin v3.0.1
```

Die GitHub-Actions-Workflows **hassfest** und **HACS Validation** prüfen Pushes und Pull Requests automatisch.

### Repository-Struktur

```text
hafas-bus-monitor/
├── custom_components/
│   └── hafas_bus_monitor/
│       ├── __init__.py
│       ├── manifest.json
│       ├── config_flow.py
│       ├── const.py
│       ├── api.py
│       ├── coordinator.py
│       ├── routing.py
│       ├── sensor.py
│       ├── switch.py
│       ├── util.py
│       ├── services.yaml
│       ├── strings.json
│       ├── brand/
│       │   └── icon.png
│       └── translations/
│           ├── de.json
│           └── en.json
├── examples/
│   ├── automation_school_end.yaml
│   └── dashboard.yaml
├── tests/
│   ├── __init__.py
│   ├── loader.py
│   ├── test_api_parsing.py
│   ├── test_routing.py
│   └── test_util.py
├── .github/workflows/validate.yml
├── hacs.json
├── README.md
└── LICENSE
```

---

## Entwicklung und Tests

Die reine HAFAS-/Routing-Logik ist ohne Home-Assistant-Installation testbar:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install aiohttp

python -m unittest discover -s tests -v
```

Ein Live-Test gegen NAH.SH:

```bash
HAFAS_LIVE_TEST=1 python -m unittest tests.test_api_parsing -v
```

Die Home-Assistant-spezifischen Module werden zusätzlich durch die GitHub-Action **hassfest** und **HACS Validation** geprüft. Vor einem Release:

```bash
python -m compileall custom_components/hafas_bus_monitor
```

---

## Lizenz

MIT – siehe [LICENSE](LICENSE).

HAFAS ist eine Marke/Software von HaCon. NAH.SH ist der Nahverkehrsverbund Schleswig-Holstein. Diese Integration ist ein unabhängiges Community-Projekt und steht in keiner offiziellen Verbindung zu NAH.SH, KVG oder HaCon.
