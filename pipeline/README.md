# kontrollen – Pipeline

uv-Paket, das aus den Rohdaten (Berlin, Aachen, Köln, Bonn, Schonungen, Oberderdingen) und den
OSM-Abzügen die Kartendaten baut. Alle Befehle aus `pipeline/` heraus:

```bash
uv sync
uv run kontrollen info       # Pfade, Quellen, was fehlt
uv run kontrollen fetch      # Berliner PDF-Anlagen + Dateien der anderen Städte (mit Prüfsummen)
                             #   --osm: OSM-Abzüge (Geofabrik)  --neu: Kataloge neu fragen
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
sources.yaml ─ fetch ─> data/raw/berlin/anlage{1..4}_<jahr>.pdf         (FragDenStaat, sha256)
                        data/raw/aachen/*.xlsx|*.csv                     (Liste: config/aachen_ressourcen.json)
                        data/raw/aachen_alt/geschw_aachen_juni2020.html  (Juni 2020, alte Karte)
                        data/raw/{koeln,bonn}/*.csv(.gz)                 (Listen: config/<stadt>_ressourcen.json)
                        data/raw/{schonungen,oberderdingen}/*.pdf|*.docx
                        data/raw/osm/*.osm.pbf                           (Geofabrik, je Stadt in sources.yaml)
osm      -> data/interim/osm/{strassen,adressen,knoten,gebiete}_<stadt>.parquet
build    -> data/interim/kontrollen.parquet   berlin_pdf.py, berlin.py, aachen.py, koeln.py, bonn.py,
                                              schonungen.py, oberderdingen.py -> schema.py
            data/interim/build_bericht.json   je Datei: Zeilen, Übersprungenes, Nachträge
geocode  -> data/geokodierung.csv             je Kontrolle: lon, lat, Methode, Suchgebiet,
            data/geokodierung_validierung.json OSM-Straße, Abschnitt (WKT), Abstände, Hinweis
site     -> data/karte/messstellen.json       Messstellen (gebündelte Verortungen, Ids bleiben)
            data/karte/kontrollen.json        eine Zeile je Kontrolle, nur Zahlen + Verweise
            data/karte/abschnitte.geojson     Abschnitte zwischen Querstraßen / ganze Straßen
            data/karte/kontrollen.csv         Download, eine Zeile je Kontrolle
            data/karte/manifest.json          Stand, Zahlen, Quellen, Lizenzen, Verortung
```

Im Git liegen `data/karte/`, `data/geokodierung*` und `config/*_ressourcen.json`; `data/raw/`
und `data/interim/` bleiben lokal. `build` bricht ab, wenn zwei Kontrollen dieselbe Id tragen –
Verortung und Karte hängen an ihr.

**Messstellen-Ids** („K09412“, im Link `s=`, in der CSV `messstelle`) bleiben über Neubauten
hinweg: `site` liest vor dem Schreiben die bisherige `messstellen.json` und gibt jeder Messstelle
mit gleicher Stadt, Straße, gleichem Punkt und gleicher Genauigkeit ihre alte Id; neue bekommen
die nächste freie Nummer (`messstellen_naechste_id` im Manifest). Eine Nummer wird nie zweimal
vergeben – ein alter Link öffnet dann nichts statt einer anderen Stelle.

## Die Quellen

**Berlin.** Die Polizei hat 2020 per IFG je Zeitraum eine Tabelle als PDF geliefert (Anlagen
1–4 zum Bescheid vom 09.12.2020: 2017, 2018, 2019, 01.01.–31.08.2020), eine Zeile je
Kontrolle. `berlin_pdf.py` liest die Zeichen samt Lage (pdfplumber), ohne Tabellenerkennung:

- **Spalten** aus den senkrechten Linien im Tabellenkopf der ersten Seite; die Folgeseiten
  haben keine Linien, aber dasselbe Raster.
- **Zellen** = zusammenhängende Läufe im Inhaltsstrom; ein Lauf gehört zur Spalte, in der er
  beginnt (lange Texte laufen in leere Nachbarzellen, Zahlen stehen rechtsbündig).
- **Zeilen** nach der Unterkante der Zeichen – ein roter Nachtrag in größerer Schrift (Anlage
  3, S. 1) steht so in seiner Zeile. Was kein Datum trägt (der rote „Stand: 05.10.2020“ unter
  Anlage 4), wird übersprungen und im Build-Bericht genannt.

**Gegenprobe:** Anlage 3 ergibt alle 9.150 Zeilen von 2019 der früheren CSV
(`vizsim/geschwindigkeitskontrollen`, v01). Unterschiede gibt es nur, wo die CSV falsch gelesen
hatte: „50/30“ als Tempo 0 mit „50/3“ in der Richtung, „-“ als 0, abgeschnittene Zellen. Für
2017 und 2018 gilt dasselbe (9.540 und 9.255 Zeilen wie in der CSV); dort hatte die CSV vor
allem lange Namen zerteilt (`Charlottenburger Chauss` + `ee 43`), die das PDF ganz enthält.
`berlin.py` bringt die Zeilen ins gemeinsame Schema:

- „Nr.“: Hausnummer (`423`, auch `44-46`), gegenüber (`g232`), vermutlich Lichtmast
  (`L2980`, nicht verortbar), an der Autobahn Kilometer (`k16,5`, ungenutzt).
- „zwischen“: `A u. B`, `/C` (Kreuzung) oder ein Ort (`AS Kaiserdamm`, `Knobelsdorffbrücke`);
  steht `/C` in „Nr.“ (`gL2272/Überleitung A 115`), wird es geholt.
- „Verwaltungsbezirk“: ein oder mehrere Bezirke, oft abgeschnitten – gelesen wird der Anfang.
- „erlaubte Geschwindigkeit“ `50/30` bzw. `30/50` (wechselndes Limit, ohne Angabe wann): leer.
- Datum, Beginn, Ende: endet eine Kontrolle vor ihrem Beginn, lief sie über Mitternacht;
  mehrtägige tragen das Datum in Beginn und Ende.
- `-` in Stufen und Fahrverboten: keine Angabe -> leer, nicht 0.
- Messungen = Überschreitungen (ein Drittel): nur die zu schnellen erfasst ->
  `alle_gezaehlt = false`, kein Anteil.
- Id = Jahr der Anlage und Zeile darin (`B2019-00001`).

**Aachen.** Je Jahr ein CKAN-Datensatz mit Monatsdateien – das Portal hält nur die **letzten
drei Monate** je Jahr. `fetch --neu` fragt den Katalog (sources.yaml: `ckan`, `suche`,
`titel_muster`) und schreibt die gefundenen Dateien samt Prüfsumme nach
`config/aachen_ressourcen.json`; ohne `--neu` lädt `fetch` genau diese Liste. Formate
(`aachen.py`): 2020 mit „bis/über 20 km/h“ (Juni: 15 km/h), ab 2021 nur „Verstöße“, ab
Oktober 2025 zusätzlich CSV mit langem Datum („Montag, 1. Dezember 2025“) – gibt es Excel, gilt
Excel. Den Juni 2020 liest `lies_folium` aus den Tooltips der alten Karte.

**Köln.** Je Datensatz (2017–2022, 2023, 2024, 2025) eine Datei mit **einem Verstoß je Zeile**
und Tabellen der Standorte je Dienststelle („Standorttabelle s01“ …), alles auf
offenedaten-koeln.de (DKAN 2: `fetch` fragt `api/1/search`, dazu GovData als Spiegel; open.nrw
antwortet GitHub Actions nicht). Die Liste der Dateien steht in `config/koeln_ressourcen.json`;
manche Download-Adressen sind doppelt kodiert (`%25C3%25BC`) – `fetch` versucht dann die
einmal dekodierte. `koeln.py`:

- Vorgänge: `vorfallsdatum` `10117` = 1.1.2017 (Tag ohne führende Null; ab 2023 `010123`),
  `ueberschreitung` in km/h nach Toleranzabzug, `dienststelle`, `standort` = Kürzel. Kopf und
  Auffüllung wechseln je Jahr (`vorfallsdatum `, `010124        `); um ein Feld verrutschte
  Zeilen (2025: knapp 6.000 von 450.000) bleiben als unlesbar draußen.
- **Nur die mobile Überwachung.** `S-02` misst mobil (Median sechs Tage je Standort und Jahr),
  `S-01` sind die festen Anlagen und `K-04` die an Kreuzungen (über 300 Tage im Jahr) – draußen.
  2017 fehlt die Dienststelle, 2018/19 führt `S-01` einige Fälle an mobilen Standorten: dann
  zählt ein Fall als mobil, wenn sein Kürzel nur in der mobilen Tabelle (s02) steht, nicht auch
  in s01 (dieselben Kürzel stehen dort für andere Orte: 971–983 in s01 = Rheinbrücke der A 1, in
  s02 = Brühler Straße). Fälle an Kürzeln, die keine Tabelle kennt (2017–2019, rund 90.000),
  fehlen; der Bericht des Builds zählt alles (`mobil`, `fest`, `kreuzung`, `unbekannt`,
  `unlesbar`).
- Standorttabellen: Kürzel; Tempolimit Pkw/Lkw; „Stadtteil Tatort“ (oft mit einem Code davor:
  `AA   Riehl`, `1682 Riehl`); Tatstraße mit Hausnummer; Fahrtrichtung. 2024/2025 ohne
  Kopfzeile und mit einer Kennziffer nach dem Kürzel; **2023 ohne Kürzel** (vorn steht die
  Kennziffer – `pruefe_kuerzel` erkennt das am Abgleich mit den anderen Jahren, `ergaenze_kuerzel`
  holt das Kürzel über den gleichen Text aus 2024 bzw. 2017–2022). Kürzel werden über die Jahre
  neu vergeben, darum gilt immer die Tabelle desselben Datensatzes.
- Adressen (`adresse`): Hausnummer aus `80-86`, `Haus Nr.`, `Hs.Nr.`, `Hausnr.`, `ggü. 161`,
  `Höhe 179` – auch angeklebt (`Nettesheimerstr.Hs.Nr.76a`). Laternen, Masten, Kilometer und Meter
  (`Lat.Nr.106`, `L.21`, `L 489 0,29`, `20mtr.`) sind keine Hausnummern: dann nur die Straße.
  `A/B`, `vor B`, `Höhe B`, `unter B` -> Kreuzung mit B. Abkürzungen der älteren Tabellen
  (`Ber.Gl.Str.`, `K.-Aden.-Ufer`) übersetzt `config/orte.yaml`.
- **Kontrolle = alle Verstöße eines Standorts an einem Tag.** Gemessene Fahrzeuge nennt Köln
  nicht (`messungen` leer, `alle_gezaehlt = false`), Uhrzeit und Dauer einer Kontrolle auch nicht.
  Stufen: bis/über 20 km/h aus der Überschreitung jedes Verstoßes.
- Gelesen wird stückweise und gleich je Standort und Tag gezählt (4,9 Mio. Zeilen, ~10 s).
- Id = Tag und Kürzel (`K2019-01-01-0101`).

Adressen in Freitext liest `adressen.py` (aus `koeln.py` herausgelöst, genutzt von Köln, Bonn,
Schonungen und Oberderdingen): Die Straße endet an Komma, Zusatz („Höhe“, „ggü.“, „unterhalb“,
„Haus Nr.“, „Laterne“ …), Zahl oder einem großgeschriebenen Wort nach „Str.“; Hausnummer gleich
nach den Zusätzen, sonst nach „Haus“, „Hs.“, „Nr.“ (auch „Nr.: 100“).

**Bonn.** Je Jahr eine Datei „Bußgelder fließender Verkehr“ (GovData, `config/bonn_ressourcen.json`;
opendata.bonn.de weist Verbindungen zeitweise ab – `lade` wartet dann 5, 30 und 90 s), **ein
Verstoß je Zeile**: Tattag, Tatzeit, Tatort (Freitext), Tatbestandsnummer, Bußgeld. 2016 ist
als Mac-Roman gespeichert (`tabellen.kodierung` erkennt „Stra§e“), in manchen Zeilen steht
„"“ für „ö“ („H"he“). `bonn.py`:

- **Feste Anlagen** sind nicht gekennzeichnet: Ein Tatort mit Verstößen an mehr als 250 Tagen
  eines Jahres gilt als feste Anlage und bleibt in allen Jahren draußen (`FEST_TAGE`; 9 Tatorte,
  62 Tatort-Jahre mit über 300 Tagen, sonst höchstens 227).
- **Kontrolle = alle Verstöße eines Tatorts an einem Tag**, wie in Köln; gemessene Fahrzeuge,
  Tempolimit und Stufen fehlen (`alle_gezaehlt = false`).
- Tatort: `Bonn, <Straße> Höhe Haus-Nr. 15 Fahrtrichtung <Ziel>`, auch `Bonn - Mehlem, …`,
  `Bonn Beuel, …`, `53179, Bonn, …`; zwei Straßen mit Komma oder „/“ sind eine Kreuzung,
  „Höhe Überführung B“ die Kreuzung mit B, „BAB A 562 / B“ eine Autobahn mit Ort. An der
  Autobahn steht meist nur der Kilometer (`A 555; km 018,000`) – ohne Lage, ebenso Landes- und
  Kreisstraßen ohne Namen („L 16 Höhe Auf der Rötschen“: OSM kennt die Nummer, die Verortung
  sucht nur Namen).
- Id = Tag und die ersten 8 Zeichen des SHA-1 des Tatorts (`N2023-05-02-1a2b3c4d`).

**Schonungen** (Landkreis Schweinfurt). Monatsberichte des Zweckverbands Kommunale
Verkehrsüberwachung Südostbayern in der WordPress-Mediathek der Gemeinde (`kataloge: art:
wordpress` fragt `wp-json/wp/v2/media`; PDF, einige als Word-Datei – `dokumente.text`). Je
Messung ein Absatz („Messstelle Mainberg, St2447, Mainleite / Bereich Hs.-Nr. 28“, Tempolimit,
Messzeitpunkt mit Beginn und Ende, Fahrzeuge, Verstöße, Klassen). `schonungen.py`: eine Zeile =
eine Kontrolle mit allen Fahrzeugen; Stufen bis/über 20 km/h nur, wenn die Klassen die Summe
ergeben; derselbe Bericht zweimal hochgeladen zählt einmal. Gemeindeteil und Straßennummer
(St2447, SW 25) stehen vor der Straße; Gemeindeteile haben in OSM keine Grenzen. Abkürzungen
(„Marktst. Hauptstr.“) übersetzt `config/orte.yaml`. Id = Beginn und Messstelle
(`S2026-03-10-1154-3f2a`).

**Oberderdingen** (Landkreis Karlsruhe). Quartalstabellen des Landratsamts als PDF im CMS der
Stadt, ohne abfragbare Übersicht – `kataloge: art: liste` nennt die Dateien fest (neue Quartale
dort eintragen). `oberderdingen.py`: eine Tabellenzeile = eine Kontrolle mit allen Fahrzeugen,
ohne Uhrzeit. Stehen am selben Tag an derselben Stelle zwei Richtungen mit derselben Zahl
gemessener Fahrzeuge, hat das Gerät beide zusammen gezählt: eine Kontrolle, Richtung „beide“,
Beanstandungen addiert. Bei mehrtägigen Messungen steht mitunter an jedem Tag dieselbe Zahl
(vermutlich ein Tagesschnitt). Id = Tag und Messstelle (`O2026-01-15-3f2a1b`, eine zweite
gleiche Zeile `…-2`).

## Datenlage

`datenlage` in `config/sources.yaml`: je Stadt ein Eintrag mit Stand (`in_karte`, `offen`,
`geliefert`, `kandidat`, `teilweise`, `abgelehnt` – Texte in `site.STAND`), Lage, Empfehlung,
Belegen (Links) und – mit `anfrage: true` – einem Anfragetext aus `anfrage_vorlage` (Platzhalter
`{stelle}`, `{seit}`, `{zusatz}`). `recht` nennt je Land die Rechtsgrundlage, mit Beleg im
Kommentar. `kontrollen site` schreibt daraus `data/karte/datenlage.json` (ein Punkt je Stadt;
Städte in der Karte bekommen den Median ihrer Messstellen und die Zahl ihrer Kontrollen) und die
Übersicht `docs/DATENLAGE.md`. `tests/test_datenlage.py` prüft jeden Eintrag (Stand, Beleg,
Ort, Land, Platzhalter, Kontakt nur über die Behördensuche von FragDenStaat).

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
   Stadtweit nur, wenn die Straße nicht an mehreren Orten liegt – außer dort, wo die
   Verortung keine Bezirke kennt (Aachen, Bonn, Schonungen, Oberderdingen): dann mit Hinweis.

**Gegenprobe** (`validiere`): Wo Hausnummer und Querstraßen vorliegen, misst die Pipeline den
Abstand des Hausnummer-Punkts zum Abschnitt – Stand 9. November 2026 (Geofabrik-Abzug dieses Tages):
23.459 Kontrollen, 92,7 % höchstens 50 m, Median 0 m, 1,5 % über 250 m.

**Was offen bleibt** (Berlin, 106 Kontrollen): vor allem der Tunnel unter der Schlangenbader
Straße (ehemalige A 104, in OSM ohne Nummer und Namen), „Gerosteig“ an der A 113 (2020; die
Straße liegt 245 m neben der Autobahn, früher hieß es „TAG Gerosteig“), Verbindungsfahrbahnen
und einzelne Abkürzungen.

## Entwickeln ohne Netz

Wer keinen Zugang zu Geofabrik, FragDenStaat und den Portalen der Städte hat (etwa in einer
Sandbox), startet den Workflow „Entwicklungsauszug“ (oder pusht auf `dev/auszug-anfordern`). Er
legt die kompakten OSM-Tabellen, die Berliner PDF-Anlagen und die Rohdateien von Aachen, Köln,
Bonn, Schonungen und Oberderdingen (große CSV gzip-komprimiert) samt den neu erfragten Listen
`config/*_ressourcen.json` auf den Branch `dev/auszug`:

```bash
git fetch origin dev/auszug
git archive FETCH_HEAD | tar -x -C /tmp/auszug
cp /tmp/auszug/pipeline/data/interim/osm/*.parquet pipeline/data/interim/osm/
cp -r /tmp/auszug/pipeline/data/raw/* pipeline/data/raw/
```

Die Listen dort nur übernehmen, wenn sie vollständig sind (`fehler` leer bis auf Kataloge, die
nicht antworten) – sonst fehlen Dateien, die der Server gerade abgewiesen hat.

## Neue Daten

- **Neue Aachener Monate:** Workflow „Kartendaten neu bauen“ mit „Kataloge neu fragen“; der PR
  zeigt die neuen Dateien in `config/aachen_ressourcen.json`.
- **Neue Stadt:** Eintrag unter `staedte` in `sources.yaml`: Quelle, OSM-Abzug, `bbox`,
  `crs_m`, `stadtgrenze`; Dateien aus Katalogen (`kataloge` mit
  `art: ckan | dkan | wordpress | liste`, `suche`, `titel_muster`, `stadt_muster`,
  `ressourcen`), Leser nach dem Muster von `bonn.py` oder `oberderdingen.py`, Eintrag in
  `cli.LESER`; die Karte nimmt die Stadt aus dem Manifest (Knopf, Hinweise, Methode). Dazu den
  Eintrag in `datenlage` auf `stand: in_karte` mit `stadt:` umstellen.
- **Neue Monate oder Quartale:** Köln, Bonn und Schonungen über „Kataloge neu fragen“;
  Oberderdingen von Hand in die Liste in `sources.yaml`.
