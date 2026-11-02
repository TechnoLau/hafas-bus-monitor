# HAFAS Bus Monitor für Home Assistant

Eine HACS-kompatible Home-Assistant-Custom-Integration für **Busabfahrten auf Basis von HAFAS**. Sie wurde für das **NAH.SH-HAFAS** (Schleswig-Holstein, z. B. Kiel) gebaut und ist dort ohne API-Key nutzbar.

Die Integration beantwortet zwei Fragen:

1. **Wann fährt mein Bus?** – pro Haltestelle, gefiltert nach bevorzugten Linien.
2. **Welcher Bus ist nach der Schule der schnellste?** – Vergleich mehrerer Haltestellen inklusive Fußweg.

> **Hinweis:** HAFAS ist ein System des Herstellers HaCon. Die NAH.SH-Schnittstelle ist eine öffentliche Fahrplan-Schnittstelle, keine offiziell dokumentierte, garantierte API. Endpunkte können sich ändern. Die Integration fragt standardmäßig nur alle 60 Sekunden ab; bitte nicht auf wenige Sekunden herunterdrehen.

---

## Funktionen

- **Haltestellensuche** über Stadt + Suchbegriff (z. B. `Kiel` + `Hospitalstraße`)
- **Auswahl aus mehreren HAFAS-Treffern** (statt blindem ersten Treffer)
- **Linienfilter** pro Haltestelle (z. B. `61, 62`); leer = alle Linien
- **Optionaler Ziel-Filter** pro Haltestelle für das Routing (z. B. `Russee`)
- **Transparente Abfahrtsattribute**: Linie, Ziel, Abfahrtszeit, Restminuten, Verspätung, Steig
- **Mehrere Haltestellen** in einem Eintrag
- **Sensor „Schnellste Verbindung“** mit Fußweg-Vergleich
- **Options-Flow** zum Hinzufügen/Entfernen/Bearbeiten von Haltestellen und Einstellungen
- **Service** `hafas_bus_monitor.refresh` zum sofortigen Aktualisieren
- **Keine externen Python-Abhängigkeiten** (nutzt `aiohttp` aus Home Assistant)

---

## Unterstütztes Netz

| Feld | Wert |
|---|---|
| HAFAS-Deployment | NAH.SH (Nahverkehrsverbund Schleswig-Holstein) |
| Endpunkt | `https://nahsh.hafas.cloud/gate` (Fallback: `https://nah.sh.hafas.de/bin/mgate.exe`) |
| Zeitraum | Schleswig-Holstein, u. a. Kiel, Lübeck, Flensburg, Eutin |
| Produktfilter | Busse und On-call-Busse (Bitmaske 544) |

Für andere HAFAS-Betreiber müssten `HAFAS_ENDPOINT`, `HAFAS_CLIENT`, `HAFAS_AUTH` und ggf. die Produkt-Bitmaske in [`const.py`](custom_components/hafas_bus_monitor/const.py) angepasst werden. Die Integration ist bewusst generisch aufgebaut, getestet ist der NAH.SH-Endpunkt.

---

## Installation

### Variante A: HACS (Custom Repository)

1. Repository auf GitHub veröffentlichen (siehe [GitHub-Veröffentlichung](#github-veröffentlichung)).
2. In Home Assistant **HACS → Integrationen** öffnen.
3. Oben rechts auf **⋮ → Benutzerdefinierte Repositories** klicken.
4. Repository-URL eintragen, Kategorie **Integration** wählen, **Hinzufügen**.
5. Nach `HAFAS Bus Monitor` suchen, installieren.
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

- Home Assistant **2024.6** oder neuer
- Internetzugang zu `nahsh.hafas.cloud`
- Kein API-Key erforderlich

---

## Einrichtung

Beim ersten Einrichten fragt die Integration:

| Feld | Bedeutung | Beispiel |
|---|---|---|
| **Stadt** | Stadt für die Haltestellensuche | `Kiel` |
| **Haltestelle (Suchbegriff)** | Name oder Teilname | `Hospitalstraße` |
| **Bevorzugte Linien** | Kommagetrennt; leer = alle Linien | `61, 62` |
| **Ziel-Filter (optional)** | Nur für den Routing-Sensor; Teilstring des Ziels | `Russee` |
| **Fußweg zu dieser Haltestelle** | Minuten von der Schule bis zum Steig | `3` |
| **Vorschau-Fenster** | Wie weit HAFAS in die Zukunft sucht | `60` Minuten |
| **Aktualisierungsintervall** | Polling-Intervall | `60` Sekunden |
| **Schnellste-Verbindung-Sensor** | Routing-Sensor anlegen | `an` |

Bei mehreren Treffern erscheint eine Auswahlliste. Nach der ersten Haltestelle kann direkt eine zweite hinzugefügt werden (z. B. `Kunsthalle` mit einem anderen Fußweg).

> **Ein Eintrag für alle Haltestellen:** Die Integration ist als ein zentraler Eintrag ausgelegt (`single_config_entry`). Alle Haltestellen werden über den Options-Flow verwaltet. Das hält die Entity-IDs stabil und stellt sicher, dass der Routing-Sensor alle Haltestellen vergleicht.

Die Einrichtung erfolgt vollständig über die Home-Assistant-Oberfläche. Es ist **kein YAML in `configuration.yaml`** erforderlich; die YAML-Beispiele in diesem README betreffen nur Dashboard und Automationen.

### Spätere Änderungen

**Einstellungen → Geräte & Dienste → HAFAS Bus Monitor → Konfigurieren** öffnet den Options-Flow:

- Abfrage- und Routing-Einstellungen ändern
- Haltestelle hinzufügen
- Linien / Fußweg / Ziel-Filter bearbeiten
- Haltestelle entfernen
- **Speichern und neu laden**

Mindestens eine Haltestelle muss bestehen bleiben.

---

## Entitäten

Die Entity-IDs werden aus dem Haltestellennamen abgeleitet (Stadtpräfix wird entfernt):

| Entität | Beispiel |
|---|---|
| Haltestellen-Sensor | `sensor.hafas_hospitalstrasse` |
| Haltestellen-Sensor | `sensor.hafas_kunsthalle` |
| Routing-Sensor | `sensor.hafas_schnellste_verbindung` |

### 1. Haltestellen-Sensor

**State:** Restminuten bis zur nächsten Abfahrt der gefilterten Linien (ganzzahlig, `min`).  
Wenn im Vorschau-Fenster keine passende Abfahrt liegt: `unknown`.

**Attribute:**

| Attribut | Inhalt |
|---|---|
| `stop` | Vollständiger HAFAS-Haltestellenname |
| `stop_id` | HAFAS-ID |
| `city` | Stadt |
| `lines` | Aktiver Linienfilter (Liste) |
| `destination_filter` | Optionaler Zielfilter |
| `walking_minutes` | Fußweg |
| `scan_minutes` | Vorschau-Fenster |
| `departures` | **Nur gefilterte Linien**: Liste der Abfahrten (max. 12) |
| `all_departures` | Alle Busse im Fenster (Transparenz/Debug, max. 12) |
| `departure_count` | Anzahl in `departures` |
| `next_departure` | Nächste gefilterte Abfahrt als Objekt |
| `last_update` | Zeitpunkt des HAFAS-Abrufs (ISO 8601) |
| `error` | Letzter Fehler dieser Haltestelle, falls vorhanden |

Jede Abfahrt in `departures` enthält:

```yaml
line: "61"
line_name: "Bus 61"
destination: "Kiel Hbf"
departure_time: "2026-11-02T13:19:00+01:00"
departure_time_local: "13:19"
planned_departure_time: "2026-11-02T13:17:00+01:00"
planned_departure_time_local: "13:17"
delay: 2
delay_minutes: 2
delay_seconds: 120
minutes_until_departure: 4
platform: "A"
cancelled: false
realtime: true
trip_id: "..."
stop_name: "Kiel Hospitalstraße"
```

**Wichtig:** `departures` ist bereits nach den bevorzugten Linien gefiltert. `all_departures` ist nur für Transparenz/Debug gedacht.

### 2. Routing-Sensor „Schnellste Verbindung“

**State:** Zum Beispiel:

```text
Linie 61 ab Kunsthalle in 4 Min
```

Wenn keine Verbindung gefunden wird:

```text
Keine Verbindung
```

**Attribute:**

| Attribut | Inhalt |
|---|---|
| `best` | Gewählte Verbindung (siehe unten) |
| `options` | Alle geprüften Haltestellen mit Ergebnis/Grund |
| `reason` | `no_departures`, `no_catchable_departure`, ... |
| `selection_method` | Erklärung der Auswahl |
| `stops` | Konfigurierte Haltestellen, Fußwege, Linien |
| `last_update` | Zeitpunkt des Abrufs |

`best` enthält u. a.:

```yaml
line: "61"
destination: "Kiel Hbf"
stop: "Kiel Kunsthalle"
stop_short: "Kunsthalle"
walk_minutes: 6
minutes_until: 4
leave_in_minutes: 0
departure_time_local: "13:22"
delay: 0
platform: "A"
catchable: true
```

### Wie das Routing rechnet

Für jede Haltestelle wird die **früheste Abfahrt** gesucht, die man mit dem konfigurierten Fußweg noch erreichen kann:

```text
Abfahrt in Minuten >= Fußweg in Minuten
```

Von den erreichbaren Abfahrten gewinnt die **früheste tatsächliche Abfahrtszeit** (Echtzeit, falls vorhanden). Der Fußweg dient also als Ausschlusskriterium: Ein Bus, der in 2 Minuten fährt, man aber 5 Minuten braucht, wird übersprungen. Bei gleicher Abfahrtszeit gewinnt der kürzere Fußweg.

`leave_in_minutes` sagt, wann man losgehen sollte:

```text
leave_in_minutes = max(0, Restminuten bis Abfahrt - Fußweg)
```

**Wichtig:** Die Integration kennt keine Fahrzeit bis zum endgültigen Ziel. Sie vergleicht die Abfahrt, nicht die Ankunft. Wenn an einer Haltestelle mehrere Richtungen derselben Linie halten, kann der optionale **Ziel-Filter** (z. B. `Russee`) helfen.

---

## Dashboard-Beispiel (Lovelace Markdown)

Das folgende Beispiel zeigt die gefilterten Linien 61 und 62 inklusive Linienbezeichnung, Ziel, Uhrzeit, Restminuten und Verspätung. Es funktioniert ohne zusätzliche HACS-Karten.

```yaml
type: markdown
title: Busse ab Hospitalstraße
content: |
  {% set entity_id = 'sensor.hafas_hospitalstrasse' %}
  {% set departures = state_attr(entity_id, 'departures') or [] %}
  {% if departures %}
  {% for dep in departures[:6] %}
  - **Linie {{ dep.line }}** → {{ dep.destination }} · **{{ dep.minutes_until_departure }} Min** · {{ dep.departure_time_local }}{% if dep.delay > 0 %} · +{{ dep.delay }} Min{% elif dep.delay < 0 %} · {{ dep.delay }} Min{% endif %}{% if dep.cancelled %} · **fällt aus**{% endif %}
  {% endfor %}
  {% else %}
  Keine passenden Abfahrten im Vorschau-Fenster.
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

      **Ziel:** {{ best.destination }}  
      **Fußweg:** {{ best.walk_minutes }} Min  
      **Losgehen in:** {{ best.leave_in_minutes }} Min  
      **Steig:** {{ best.platform or '–' }}{% if best.delay > 0 %} · +{{ best.delay }} Min{% endif %}
      {% else %}
      Keine erreichbare Verbindung im Vorschau-Fenster.
      {% endif %}

  - type: markdown
    title: Busse ab Kunsthalle
    content: |
      {% set departures = state_attr('sensor.hafas_kunsthalle', 'departures') or [] %}
      {% if departures %}
      {% for dep in departures[:5] %}
      - **Linie {{ dep.line }}** → {{ dep.destination }} · **{{ dep.minutes_until_departure }} Min** · {{ dep.departure_time_local }}{% if dep.delay > 0 %} (+{{ dep.delay }}){% endif %}
      {% endfor %}
      {% else %}
      Keine passenden Abfahrten.
      {% endif %}
```

> Passe die Entity-IDs an, falls deine Haltestellen anders heißen. Die ID findest du unter **Einstellungen → Geräte & Dienste → Entitäten**.

---

## Automation „Schulschluss“

Die Automation prüft nach Schulende automatisch, ob **Hospitalstraße** oder **Kunsthalle** die schnellere Option ist, und schickt das Ergebnis per Push.

### Voraussetzungen

- Beide Haltestellen sind in **einem** HAFAS-Bus-Monitor-Eintrag konfiguriert.
- Der Routing-Sensor ist aktiviert.
- Ein Benachrichtigungsdienst existiert, z. B. `notify.mobile_app_schulkind`.
- Optional: ein Binary Sensor `binary_sensor.schultag` oder eine Kalender-/Workday-Bedingung.

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
  # Optional: nur an Schultagen
  # - condition: state
  #   entity_id: binary_sensor.schultag
  #   state: "on"
  - condition: template
    value_template: >-
      {{ states('sensor.hafas_schnellste_verbindung')
         not in ['unknown', 'unavailable', 'Keine Verbindung'] }}
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
- `delay: 3` ist optional; es gibt dem Coordinator Zeit, den State nach dem Refresh zu aktualisieren.
- Wenn du keine Push-Benachrichtigung willst, kann die Automation stattdessen eine Lampe, einen TTS-Ansage oder einen persistenten Hinweis auslösen.

### Alternative: Automation nur bei Änderung

Wenn nur dann benachrichtigt werden soll, wenn sich die schnellste Verbindung ändert:

```yaml
trigger:
  - platform: state
    entity_id: sensor.hafas_schnellste_verbindung
condition:
  - condition: time
    after: "13:00:00"
    before: "13:30:00"
    weekday: [mon, tue, wed, thu, fri]
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

Der Service hat keine Felder. Der normale Coordinator aktualisiert danach wieder im eingestellten Intervall.

---

## Wie die Daten abgerufen werden

1. **LocMatch** löst `Stadt + Haltestelle` in eine HAFAS-Location-ID auf.
2. **StationBoard** liefert die nächsten Busabfahrten im Vorschau-Fenster.
3. Die Integration filtert lokal nach den gewünschten Linien.
4. Echtzeitdaten (`dTimeR`) werden verwendet, falls vorhanden; andernfalls gilt die Planzeit (`dTimeS`).
5. Verspätung = Echtzeit minus Planzeit.

Die HAFAS-Antwort wird defensiv geparst: Fehlende Felder, abweichende Plattform-Schreibweisen und Abfahrten nach Mitternacht werden abgefangen.

---

## Troubleshooting

### „Keine Haltestelle gefunden“

- Kürzeren Suchbegriff verwenden (`Hospital` statt `Hospitalstraße Kiel`).
- Stadt prüfen (NAH.SH deckt Schleswig-Holstein ab, nicht ganz Deutschland).
- Sonderzeichen/ß/ä/ö/ü funktionieren normalerweise; ggf. Schreibweise variieren.

### Sensor ist `unknown`

- Im Vorschau-Fenster fährt keine Linie, die dem Filter entspricht.
- Linienfilter leeren (alle Linien) oder Vorschau-Fenster erhöhen.
- Nachts fahren viele Linien nicht.
- Attribute `all_departures` prüfen: Dort stehen alle Busse, auch wenn der Filter sie ausblendet.

### Sensor ist `unavailable`

- HAFAS-Endpunkt nicht erreichbar, Timeout oder API-Fehler.
- Logs prüfen: **Einstellungen → System → Protokolle**, nach `hafas_bus_monitor` filtern.
- Bei nur einer fehlerhaften Haltestelle bleiben die anderen Sensoren verfügbar; die betroffene Haltestelle wird `unavailable`.

### Falsche Entität / ID

- Entity-IDs werden beim ersten Anlegen aus dem Namen erzeugt.
- Bereits vergebene IDs werden nicht automatisch umbenannt.
- Unter **Einstellungen → Geräte & Dienste → Entitäten** umbenennen.
- Die ID im Dashboard/der Automation entsprechend anpassen.

### „Diese Haltestelle ist bereits eingerichtet“

- Jede Haltestelle darf pro Eintrag nur einmal vorkommen.
- Für eine zweite Haltestelle den Options-Flow verwenden (`Haltestelle hinzufügen`), nicht einen zweiten Eintrag mit derselben primären Haltestelle.

### HAFAS-Endpunkt hat sich geändert

- `HAFAS_ENDPOINT` und `HAFAS_FALLBACK_ENDPOINT` in [`const.py`](custom_components/hafas_bus_monitor/const.py) anpassen.
- Einen GitHub-Issue/PR mit dem neuen Endpunkt anlegen.
- Die Integration nutzt zuerst den neuen Cloud-Endpunkt und fällt bei Verbindungsfehlern auf den alten `mgate.exe`-Endpunkt zurück.

### Rate Limits / zu viele Anfragen

- Standard: 60 Sekunden, Minimum: 30 Sekunden.
- Bei zwei Haltestellen sind das zwei HAFAS-Anfragen pro Intervall.
- Bitte nicht dauerhaft auf 30 Sekunden oder weniger stellen; die API ist ein öffentlicher Dienst.

---

## Datenschutz und Nutzung

- Es werden nur Haltestellen-Suchbegriffe und Abfahrtsanfragen an NAH.SH/HAFAS gesendet.
- Keine API-Keys, keine Standortdaten, keine Benutzerkonten.
- Die Integration speichert nur Haltestellen-ID, Namen, Linienfilter und Einstellungen in der Home-Assistant-Konfiguration.
- Bitte die HAFAS-Schnittstelle fair nutzen (angemessenes Polling-Intervall, kein Massenabruf).

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

git tag v1.0.1
git push origin v1.0.1
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
│       ├── util.py
│       ├── services.yaml
│       ├── strings.json
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
│   └── test_routing.py
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

Ein Live-Test gegen NAH.SH (benötigt Internet):

```bash
HAFAS_LIVE_TEST=1 python -m unittest tests.test_api_parsing -v
```

Die Home-Assistant-spezifischen Module (`config_flow.py`, `sensor.py`, `__init__.py`) werden zusätzlich durch die GitHub-Action **hassfest** und **HACS Validation** geprüft. Vor einem Release:

```bash
python -m compileall custom_components/hafas_bus_monitor
```

---

## Lizenz

MIT – siehe [LICENSE](LICENSE).

HAFAS ist eine Marke/Software von HaCon. NAH.SH ist der Nahverkehrsverbund Schleswig-Holstein. Diese Integration ist ein unabhängiges Community-Projekt und steht in keiner offiziellen Verbindung zu NAH.SH, KVG oder HaCon.
