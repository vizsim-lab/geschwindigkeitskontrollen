![Status: Beta](https://img.shields.io/badge/Status-Beta-4338ca)
![License: AGPL-3.0-or-later](https://img.shields.io/badge/License-AGPL--3.0--or--later-blue)

# Geschwindigkeitskontrollen (Berlin, Aachen, Köln, Bonn, Schonungen, Oberderdingen)

Wo wurde wie oft kontrolliert – und wie viele waren zu schnell? Die Karte zeigt **33.401
temporäre Geschwindigkeitskontrollen der Polizei Berlin (Januar 2017 bis August 2020)**,
**3.467 Kontrollen der Stadt Aachen (Juni 2020 bis September 2026)**, **44.633 mobile
Kontrollen der Stadt Köln (2017 bis 2025)**, **34.128 mobile Kontrollen der Bundesstadt Bonn
(2016 bis 2024)** sowie **123 Kontrollen in der Gemeinde Schonungen (2020 bis 2026)** und **150
in der Stadt Oberderdingen (2024 bis 2026)**, jede an ihrer Messstelle. Die Ebene **„Datenlage je
Stadt“** zeigt für 20 weitere Städte und Kreise, ob es solche Daten gibt – veröffentlicht, auf
Anfrage herausgegeben, nur als Summen oder abgelehnt –, mit einem Anfragetext für FragDenStaat.

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
(Berlin: 9.246, Aachen: 166, Köln: 1.368, Bonn: 1.517, Schonungen: 31, Oberderdingen: 44). Die
Farbe zeigt wahlweise

- **Anteil zu schnell** – Überschreitungen je gemessenem Fahrzeug (Berlin, Aachen, Schonungen,
  Oberderdingen),
- **je Stunde** – Überschreitungen je Stunde Messdauer (Berlin, Schonungen),
- **je Kontrolle** – Überschreitungen geteilt durch die Zahl der Kontrollen (überall),
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
- **Köln und Bonn nennen nur die Verstöße**, nicht alle gemessenen Fahrzeuge – einen Anteil gibt
  es dort nicht. Eine „Kontrolle“ ist dort: alle Verstöße eines Standorts an einem Tag; Uhrzeit
  und Dauer fehlen. In der Karte steht nur die **mobile Überwachung der Stadt** – die festen
  Anlagen messen fast jeden Tag und bleiben draußen (Bonn kennzeichnet sie nicht: Tatorte mit
  Verstößen an mehr als 250 Tagen eines Jahres gelten als fest), die Kontrollen der Polizei
  fehlen in den Daten.
- **Schonungen und Oberderdingen** veröffentlichen jede Messung als PDF – Schonungen die
  Monatsberichte der kommunalen Verkehrsüberwachung (mit Beginn und Ende, nicht lückenlos),
  Oberderdingen Quartalstabellen des Landratsamts (gefunden: 1/2024, 4/2025, 1/2026; ohne
  Uhrzeit). Zählt das Gerät in Oberderdingen beide Richtungen zusammen, ist das eine Kontrolle.
- **Kontrollen sind keine Stichprobe.** Kontrolliert wird, wo die Behörden es für nötig halten;
  eine hohe Quote heißt nicht, dass dort mehr gerast wird als anderswo.

## Verortung

Gesucht wird im OSM-Abzug von Geofabrik, in Berlin im genannten Bezirk (die Angabe ist oft
abgeschnitten und wird über den Anfang gelesen), in Köln im genannten Stadtteil, sonst in der
ganzen Stadt oder Gemeinde, von genau nach grob:

- **Hausnummer** – die OSM-Adresse auf der Straßenachse,
- **Abschnitt** – Mitte zwischen den Kreuzungen mit den beiden Querstraßen (nur Berlin nennt sie),
- **Kreuzung** – mit der genannten Straße, Brücke oder dem Platz,
- **Anschlussstelle** – Autobahn, Tunnel, Brücke,
- **nur Straße** – Punkt in der Mitte, die Linie zeigt die ganze Straße (≈).

| | Kontrollen | Hausnummer | Abschnitt | Kreuzung | Anschlussstelle | nur Straße | ohne Lage |
|---|--:|--:|--:|--:|--:|--:|--:|
| Berlin | 33.401 | 74,2 % | 11,7 % | 10,8 % | 2,6 % | 0,5 % | 0,3 % |
| Aachen | 3.467 | – | – | – | – | 100 % | – |
| Köln | 44.633 | 67,9 % | – | 1,2 % | – | 30,4 % | 0,5 % |
| Bonn | 34.128 | 49,3 % | – | 4,7 % | 0,5 % | 31,9 % | 13,6 % |
| Schonungen | 123 | 37,4 % | – | 27,6 % | – | 33,3 % | 1,6 % |
| Oberderdingen | 150 | 74,7 % | – | 7,3 % | – | 18,0 % | – |

In Köln bleibt es bei „nur Straße“ vor allem dort, wo die Stadt statt einer Hausnummer eine
Laterne nennt („Laterne 85-77“) – Laternennummern gibt es in OSM nicht. In Bonn steht an der
Autobahn meist nur der Kilometer („A 555; km 018,000“) – das sind 3.959 der 4.657 Kontrollen
ohne Lage.

**Gegenprobe** (GPS gibt es nicht): Wo Hausnummer *und* Querstraßen vorliegen – 23.459
Kontrollen in Berlin –, liegt der Hausnummer-Punkt bei 92,7 % höchstens 50 m neben dem Abschnitt
zwischen den Querstraßen (Median 0 m); bei 1,5 % liegt er mehr als 250 m daneben, dann gilt
der Abschnitt. Was die Behörden abkürzen („TRH“ = Tunnel Rudower Höhe, „Marktst. Hauptstr.“)
oder anders nennen als OSM, übersetzt [`pipeline/config/orte.yaml`](pipeline/config/orte.yaml);
solche Stellen tragen in der Karte einen Hinweis. Einzelheiten:
[`pipeline/README.md`](pipeline/README.md#verortung).

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
- **Köln:** Stadt Köln, [Offene Daten Köln](https://www.offenedaten-koeln.de/)
  „Geschwindigkeitsüberwachung Köln“ (Datensätze 2017–2022, 2023, 2024, 2025: je Verstoß eine
  Zeile, dazu die Standorttabellen), Datenlizenz Deutschland – Zero – Version 2.0.
- **Bonn:** Bundesstadt Bonn, [Open Data](https://opendata.bonn.de/) „Bußgelder fließender
  Verkehr“ (Jahresdateien 2016–2024, je Verstoß eine Zeile; gefunden über GovData), Creative
  Commons CC Zero (so bei [Open.NRW](https://ckan.open.nrw/dataset/bussgelder-fliessender-verkehr-2024-bn)).
- **Schonungen:** Gemeinde Schonungen, [Verkehrsstatistik](https://schonungen.de/) – Monatsberichte
  des Zweckverbands Kommunale Verkehrsüberwachung Südostbayern (PDF/Word), ohne Lizenzangabe.
- **Oberderdingen:** Stadt Oberderdingen, „Kommunale Geschwindigkeitsmessungen durch das
  Landratsamt“ (Quartalstabellen [1/2024](https://oberderdingen.de/resources/ecics_3985.pdf),
  [4/2025](https://www.oberderdingen.de/resources/ecics_4317.pdf),
  [1/2026](https://www.oberderdingen.de/resources/ecics_4342.pdf)), ohne Lizenzangabe.
- **Datenlage je Stadt:** Recherche mit Belegen je Eintrag in
  [`pipeline/config/sources.yaml`](pipeline/config/sources.yaml), Übersicht in
  [`docs/DATENLAGE.md`](docs/DATENLAGE.md); keine Rechtsberatung.
- **Straßennetz und Adressen:** © OpenStreetMap-Mitwirkende, ODbL (Abzüge von Geofabrik).
- **Code:** AGPL-3.0-or-later.
