![Status: Beta](https://img.shields.io/badge/Status-Beta-4338ca)
![License: AGPL-3.0-or-later](https://img.shields.io/badge/License-AGPL--3.0--or--later-blue)

# Geschwindigkeitskontrollen (Berlin, Aachen)

Wo wurde wie oft kontrolliert – und wie viele waren zu schnell? Die Karte zeigt **33.401
temporäre Geschwindigkeitskontrollen der Polizei Berlin (Januar 2017 bis August 2020)** und
**3.467 Kontrollen der Stadt Aachen (Juni 2020 bis September 2026)**, jede an ihrer Messstelle.

**Karte: <https://vizsim-lab.github.io/geschwindigkeitskontrollen/>** · Daten als
[CSV](pipeline/data/karte/kontrollen.csv)

Neubau von [vizsim/geschwindigkeitskontrollen](https://github.com/vizsim/geschwindigkeitskontrollen):
Die alte Karte zeigte für Berlin 70 Straßen mit je einem Punkt, für Aachen einen Monat. Jetzt
ist jede Kontrolle über Hausnummer und Querstraßen im Straßennetz von OpenStreetMap verortet –
für Berlin direkt aus den PDF-Tabellen der Polizei gelesen, samt Januar bis August 2020 –,
und die Karte folgt im Aufbau der [Unfallkarte](https://github.com/vizsim/unfallkarte); die
Verortung folgt dem Muster von
[berlin-traffic-counts_schulwege](https://github.com/vizsim/berlin-traffic-counts_schulwege).

## Was die Karte zeigt

Jeder Kreis ist eine **Messstelle** – Kontrollen an derselben Stelle derselben Straße
(Berlin: 9.246, Aachen: 166). Die Farbe zeigt wahlweise

- **Anteil zu schnell** – Überschreitungen je gemessenem Fahrzeug,
- **je Stunde** – Überschreitungen je Stunde Messdauer (nur Berlin),
- **Fahrverbote** (nur Berlin) oder die Zahl der **Kontrollen**;

die Größe zeigt, wie oft dort kontrolliert wurde. Ab Zoom 12 zeigt eine Linie den Abschnitt
zwischen den beiden Querstraßen. Filter: Jahr, Tempolimit, Verortung. Ein Klick listet alle
Kontrollen der Stelle; Ansicht, Filter und offene Stelle stehen im Link.

Wichtig für die Einordnung:

- **Berlin zählt nicht immer alle Fahrzeuge.** Bei einem Drittel der Kontrollen sind Messungen
  und Überschreitungen gleich – erfasst wurden nur die zu schnellen (vor allem Autobahn). Für
  diese Kontrollen gibt es keinen Anteil; „je Stunde“ geht immer.
- **„bis 20“ und „über 20 km/h“** ergeben zusammen oft weniger als alle Überschreitungen; die
  Polizei erklärt die Spalten nicht. Die Karte zeigt sie, wie geliefert.
- **Aachen veröffentlicht je Jahr nur die letzten drei Monate.** Im Portal stehen darum Oktober
  bis Dezember 2020–2025 und Januar bis September 2026; der Juni 2020 stammt aus der alten
  Karte. Aachen nennt weder Uhrzeit noch Dauer, Tempolimit oder die Stelle auf der Straße.
- **Kontrollen sind keine Stichprobe.** Kontrolliert wird, wo die Behörden es für nötig halten;
  eine hohe Quote heißt nicht, dass dort mehr gerast wird als anderswo.

## Verortung

Gesucht wird im OSM-Abzug von Geofabrik, in Berlin im genannten Bezirk (die Angabe ist oft
abgeschnitten und wird über den Anfang gelesen), von genau nach grob:

| Methode | Berlin | | Aachen |
|---|--:|--:|--:|
| **Hausnummer** – die OSM-Adresse auf der Straßenachse | 24.778 | 74,2 % | – |
| **Abschnitt** – Mitte zwischen den Kreuzungen mit A und B | 3.901 | 11,7 % | – |
| **Kreuzung** – mit der genannten Straße, Brücke, Platz | 3.593 | 10,8 % | – |
| **Anschlussstelle** – Autobahn, Tunnel, Brücke | 861 | 2,6 % | – |
| **nur Straße** – Punkt in der Mitte, Linie = ganze Straße (≈) | 162 | 0,5 % | 3.467 |
| ohne Lage | 106 | 0,3 % | 0 |

**Gegenprobe** (GPS gibt es nicht): Wo Hausnummer *und* Querstraßen vorliegen – 23.459
Kontrollen –, liegt der Hausnummer-Punkt bei 92,7 % höchstens 50 m neben dem Abschnitt
zwischen den Querstraßen (Median 0 m); bei 1,5 % liegt er mehr als 250 m daneben, dann gilt
der Abschnitt. Was die Polizei abkürzt („TRH“ = Tunnel Rudower Höhe) oder anders nennt als OSM,
übersetzt [`pipeline/config/orte.yaml`](pipeline/config/orte.yaml); solche Stellen tragen in
der Karte einen Hinweis. Einzelheiten: [`pipeline/README.md`](pipeline/README.md#verortung).

## Aufbau

- **Repo-Wurzel** – die Karte: `index.html`, `style.css`, `js/` (ES-Module ohne Build).
  MapLibre GL JS kommt von unpkg (mit Prüfsumme), die Hintergrundkarte von
  [OpenFreeMap](https://openfreemap.org/), die Suche von [Photon](https://photon.komoot.io/) –
  ohne API-Key. GitHub Pages liefert `main` aus („Deploy from a branch“).
- **`pipeline/`** – uv-Paket `kontrollen`: Rohdaten laden, einlesen, OSM auslesen, verorten,
  Kartendaten schreiben (`pipeline/data/karte/`, im Git).
- **`.github/workflows/`** – `ci.yml` (Pipeline- und Browser-Tests bei jedem PR),
  `daten.yml` („Kartendaten neu bauen“, schlägt das Ergebnis als Branch/PR vor),
  `auszug.yml` (Entwicklungsauszug ohne Netzzugang, siehe Pipeline-README).

## Lokal

```bash
python3 -m http.server 8000          # Karte: http://localhost:8000
npm ci && npm run test:unit          # reine Module, Sekunden
npx playwright install chromium && npm run test:web   # Karte im Browser

cd pipeline && uv sync
uv run kontrollen alles --osm        # Daten neu bauen (lädt Geofabrik-Abzüge, ~5 min)
uv run pytest && uv run ruff check
```

## Quellen und Lizenzen

- **Berlin:** Polizei Berlin, Auszug aus der Geschwindigkeitsdatenbank, IFG-Bescheid vom
  09.12.2020 ([FragDenStaat](https://fragdenstaat.de/anfrage/geschwindigkeitskontrollen-von-kfz-in-berlin/)),
  geliefert als PDF (Anlagen 1–4: 2017, 2018, 2019, 01.01.–31.08.2020); die Pipeline liest die
  PDFs direkt. Der Bescheid nennt keine Lizenz.
- **Aachen:** Stadt Aachen, [Open Data](https://offenedaten.aachen.de/) „Geschwindigkeitskontrollen
  der Stadt Aachen“, Datenlizenz Deutschland – Namensnennung – Version 2.0.
- **Straßennetz und Adressen:** © OpenStreetMap-Mitwirkende, ODbL (Abzüge von Geofabrik).
- **Code:** AGPL-3.0-or-later.
