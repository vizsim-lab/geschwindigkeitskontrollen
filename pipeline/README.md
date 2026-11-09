# kontrollen – Pipeline

uv-Paket, das aus den Rohdaten (Berlin, Aachen) und den OSM-Abzügen die Kartendaten baut.
Alle Befehle aus `pipeline/` heraus:

```bash
uv sync
uv run kontrollen info       # Pfade, Quellen, was fehlt
uv run kontrollen fetch      # Berlin-CSV + Aachener Monatsdateien (mit Prüfsummen)
                             #   --osm: OSM-Abzüge (Geofabrik)  --neu: Aachener Katalog neu fragen
uv run kontrollen osm        # PBF -> data/interim/osm/*.parquet
uv run kontrollen build      # Rohdaten -> data/interim/kontrollen.parquet (gemeinsames Schema)
uv run kontrollen geocode    # Verortung -> data/geokodierung.csv + geokodierung_validierung.json
uv run kontrollen site       # Kartendaten -> data/karte/*
uv run kontrollen alles      # fetch + build + (geocode) + site; --osm lädt und liest OSM neu

uv run pytest                # Tests an tests/fixtures, ohne Netz
uv run ruff check && uv run ruff format --check
```

## Ablauf

```text
sources.yaml ─ fetch ─> data/raw/berlin/kontrollen_2017-2019_v01.csv   (fester Commit, sha256)
                        data/raw/aachen/*.xlsx|*.csv                     (Liste: config/aachen_ressourcen.json)
                        data/raw/aachen_alt/geschw_aachen_juni2020.html  (Juni 2020, alte Karte)
                        data/raw/osm/berlin-latest.osm.pbf, koeln-regbez-latest.osm.pbf
osm      -> data/interim/osm/{strassen,adressen,knoten,gebiete}_<stadt>.parquet
build    -> data/interim/kontrollen.parquet   berlin.py, aachen.py -> schema.py
geocode  -> data/geokodierung.csv             je Kontrolle: lon, lat, Methode, Suchgebiet,
            data/geokodierung_validierung.json OSM-Straße, Abschnitt (WKT), Abstände, Hinweis
site     -> data/karte/messstellen.json       Messstellen (gebündelte Verortungen)
            data/karte/kontrollen.json        eine Zeile je Kontrolle, nur Zahlen + Verweise
            data/karte/abschnitte.geojson     Abschnitte zwischen Querstraßen / ganze Straßen
            data/karte/kontrollen.csv         Download, eine Zeile je Kontrolle
            data/karte/manifest.json          Stand, Zahlen, Quellen, Lizenzen, Verortung
```

Im Git liegen `data/karte/`, `data/geokodierung*` und `config/aachen_ressourcen.json`;
`data/raw/` und `data/interim/` bleiben lokal.

## Die Quellen

**Berlin.** Die Polizei hat 2020 per IFG Tabellen für 2017–2019 (und Januar–August 2020) als
PDF geliefert; `vizsim/geschwindigkeitskontrollen` hat 2017–2019 als CSV aufbereitet. Eine
Zeile je Kontrolle. `berlin.py` repariert, was die Aufbereitung mitbringt:

- Straßennamen sind nach ~22–26 Zeichen abgeschnitten, ihr Rest steht manchmal im Feld „Nr.“
  (`Charlottenburger Chauss` + `ee 43`) – wird angehängt.
- „Nr.“: Hausnummer (`423`), gegenüber (`g232`), vermutlich Lichtmast (`L2980`, nicht
  verortbar), Sonstiges (`k5,5`).
- „zwischen“: `A u. B`, `/C` (Kreuzung) oder ein Ort (`AS Kaiserdamm`, `Knobelsdorffbrücke`).
- „Verwaltungsbezirk“: ein oder zwei Bezirke, nach 32 Zeichen abgeschnitten.
- Messungen = Überschreitungen (ein Drittel): nur die zu schnellen erfasst ->
  `alle_gezaehlt = false`, kein Anteil.

**Aachen.** Je Jahr ein CKAN-Datensatz mit Monatsdateien – das Portal hält nur die **letzten
drei Monate** je Jahr. `fetch --neu` fragt den Katalog (sources.yaml: `ckan`, `suche`,
`titel_muster`) und schreibt die gefundenen Dateien samt Prüfsumme nach
`config/aachen_ressourcen.json`; ohne `--neu` lädt `fetch` genau diese Liste. Formate
(`aachen.py`): 2020 mit „bis/über 20 km/h“ (Juni: 15 km/h), ab 2021 nur „Verstöße“, ab
Oktober 2025 zusätzlich CSV mit langem Datum („Montag, 1. Dezember 2025“) – gibt es Excel, gilt
Excel. Den Juni 2020 liest `lies_folium` aus den Tooltips der alten Karte.

## Verortung

`geocode.py`, Muster aus `vizsim/berlin-traffic-counts_schulwege`: Namen auf eine
Vergleichsform bringen (`namen.schluessel`: klein, Umlaute ausgeschrieben, nur Buchstaben und
Ziffern, „Str.“ = „Straße“, „Prof“ = „Professor“), alte Namen über `old_name`/`alt_name`,
Brücken und Tunnel über `bridge:name`/`tunnel:name`; abgeschnittene Namen über den Anfang
(ab 12 Zeichen) und Tippfehler (Ähnlichkeit ≥ 0,9) nur im Suchgebiet und nur eindeutig.

Suchgebiete (`Gebiete.stufen`): die genannten Bezirke (+300 m), deren Umgebung (+2 km), die
Stadt. Die erste genaue Antwort gewinnt; Näherungen (nur eine Querstraße, Ort statt Querstraße)
und „nur Straße“ gelten erst, wenn keine Stufe Genaueres findet. Je Kontrolle:

1. **hausnummer** — OSM-Adresse (Knoten oder Gebäudemitte) mit dieser Hausnummer an der
   Hauptstraße, höchstens 200 m von deren Achse, auf die Achse gelegt. Gibt es die Nummer
   mehrfach, entscheidet die Nähe zum Abschnitt/zur Kreuzung, sonst keine Antwort. Liegt der
   Punkt mehr als 250 m außerhalb des Abschnitts A–B, gilt der Abschnitt (Hinweis).
2. **abschnitt** — Kreuzungen der Hauptstraße mit A und mit B (Treffpunkte im Umkreis von 40 m
   gebündelt, Richtungsfahrbahnen), das nächste Paar (≤ 3 km); das Stück der Straße dazwischen
   und dessen Mitte.
3. **kreuzung** — Kreuzung mit C; als Querangabe gehen auch Autobahnen („BAB A 111“), die
   Stadtgrenze und benannte Orte (Plätze, Bahnhöfe, Anschlussstellen; höchstens 500 m neben
   der Straße, eine nicht kreuzende Straße höchstens 150 m).
4. **anschlussstelle** — Autobahn: Anschlussstellen (alle Knoten eines Namens gemittelt),
   Tunnel, Brücken, Überleitungen auf der genannten A-Nummer; passt dort nichts, eine andere
   A-Nummer, wenn alle Orte ≤ 100 m daneben liegen (die Daten nennen die A 103 in Steglitz
   „A 100“).
5. **strasse** — nur der Name: Mitte des längsten Stücks; die ganze Straße geht als Linie mit.
   Stadtweit nur, wenn die Straße nicht an mehreren Orten liegt – außer in Aachen (keine
   Bezirke in der Quelle): dort mit Hinweis.

**Gegenprobe** (`validiere`): Wo Hausnummer und Querstraßen vorliegen, misst die Pipeline den
Abstand des Hausnummer-Punkts zum Abschnitt – Stand 9. November 2026 (Geofabrik-Abzug dieses Tages):
19.156 Kontrollen, 92,5 % höchstens 50 m, Median 0 m, 1,4 % über 250 m.

**Was offen bleibt** (Berlin, 83 Kontrollen): vor allem der Tunnel unter der Schlangenbader
Straße (ehemalige A 104, in OSM ohne Nummer und Namen), Verbindungsfahrbahnen und einzelne
Abkürzungen.

## Entwickeln ohne Netz

Wer keinen Zugang zu Geofabrik und dem Aachener Portal hat (etwa in einer Sandbox), startet
den Workflow „Entwicklungsauszug“. Er legt die kompakten OSM-Tabellen (~20 MB) und die
Aachener Rohdateien auf den Branch `dev/auszug`:

```bash
git fetch origin dev/auszug
git archive origin/dev/auszug | tar -x -C /tmp/auszug
cp /tmp/auszug/pipeline/data/interim/osm/*.parquet pipeline/data/interim/osm/
cp -r /tmp/auszug/pipeline/data/raw/aachen pipeline/data/raw/
```

## Neue Daten

- **Neue Aachener Monate:** Workflow „Kartendaten neu bauen“ mit „Aachener Katalog neu
  fragen“; der PR zeigt die neuen Dateien in `config/aachen_ressourcen.json`.
- **Neue Stadt:** Eintrag unter `staedte` in `sources.yaml` (Quelle, OSM-Abzug, `bbox`,
  `crs_m`, `stadtgrenze`), Leser nach dem Muster von `berlin.py`/`aachen.py`, Aufruf in
  `cli.build`; die Karte nimmt die Stadt aus dem Manifest.
