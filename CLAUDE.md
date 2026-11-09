# CLAUDE.md — geschwindigkeitskontrollen

Karte der Geschwindigkeitskontrollen in Berlin (Polizei Berlin, 2017 bis August 2020), Aachen
(Stadt Aachen, Open Data seit 2020) und Köln (Stadt Köln, Open Data 2017–2025, Einzelverstöße
der mobilen Überwachung), jede Kontrolle über OSM verortet – dazu die Ebene „Datenlage je Stadt“
(wo es solche Daten sonst gibt; Bonn wird schon geladen, aber noch nicht gelesen).
Überblick: `README.md`, Pipeline und Datenfluss: `pipeline/README.md`. Diese Datei = die Regeln,
die in jeder Session gelten.

## Repo-Layout
- **Repo-Wurzel** — die Karte: `index.html`, `style.css`, `js/` (ES-Module, kein Build).
  GitHub Pages liefert `main` aus („Deploy from a branch“). MapLibre kommt von unpkg.
  `js/daten.js`, `js/permalink.js`, `js/popup.js`, `js/methode.js`, `js/datenlage.js` sind
  REIN (kein DOM) und browserlos getestet (`tests/unit/`); DOM und Karte nur in `main.js`,
  `karte.js`, `suche.js`.
- **`pipeline/`** — uv-Paket `kontrollen` (Code `src/`, Config `config/`, Tests `tests/`).
  Ausgaben für die Karte: `pipeline/data/karte/*` (im Git), dazu `pipeline/data/geokodierung*`
  und die Übersicht `docs/DATENLAGE.md`.
- **`tests/web/`** — Playwright-Tests der Karte, `tests/unit/` — node --test.

## Harte Regeln
- **Nie direkt auf `main` pushen** — `main` ist die Live-Karte. Änderungen per Pull Request,
  dort läuft die CI.
- **Erzeugte Dateien nicht von Hand ändern:** `pipeline/data/karte/*`,
  `pipeline/data/geokodierung*`, `pipeline/config/*_ressourcen.json`, `docs/DATENLAGE.md`.
  Immer über die CLI bzw. den Workflow „Kartendaten neu bauen“; das Ergebnis kommt als
  Branch/PR.
- **`pipeline/config/sources.yaml` ist die einzige Quellenliste.** Quellen und Lizenzen in der
  Karte kommen aus `manifest.json`; nie im Frontend nachtragen. Ebenso die Datenlage
  (`datenlage`, `recht`, `anfrage_vorlage`): Texte, Stand und Belege nur dort, die Karte liest
  `datenlage.json`. Rechtliche Aussagen nur mit Beleg (Link oder Kommentar mit Quelle);
  Kontakte nur über die Behördensuche von FragDenStaat (`kontakt.fds_suche`), keine Namen.
- **Frontend-Vertrag:** Feldnamen in `messstellen.json`/`kontrollen.json` (`felder`), die Liste
  `methoden`, die Dateinamen in `manifest.dateien` und die Permalink-Kürzel
  (`js/permalink.js`: `m`, `j`, `t`, `v`, `s`, `d` und die Werte von `m` und `v`) – nie
  umdeuten, nur ergänzen. Wer Felder ändert, zieht `site.py`, `js/` und `tests/` im selben Schritt mit
  (`tests/web/vertrag.spec.js` prüft die Feldnamen).
- **MapLibre-Version** in `index.html` (samt `integrity`) und `package.json` nur gemeinsam
  ändern (`tests/web/vertrag.spec.js`).
- **Keyless:** OpenFreeMap, Photon, OSM-/Esri-Kacheln – keine API-Keys, keine Secrets im Repo.
- **CRS:** metrisch je Stadt (`crs_m` in sources.yaml: Berlin EPSG:25833, Aachen und Köln
  EPSG:25832), Ausgabe immer EPSG:4326.
- **Lieber keine Lage als eine falsche.** Neue Regeln in `geocode.py` nie ohne Test in
  `pipeline/tests/test_geocode.py` (Ausschnitt `tests/fixtures/mini.osm`); nach Änderungen die
  Gegenprobe in `geokodierung_validierung.json` vergleichen (Anteil `unter_50m` darf nicht
  sinken, `ohne_lage` nicht steigen, ohne dass der PR das begründet).
- **Von Hand zugeordnete Orte** nur in `config/orte.yaml`, nur eindeutige, mit Kommentar.
- **Wording:** „Kontrollen“ und „Messstellen“, nie „Blitzer“ als Tatsache. Ein Anteil gibt es
  nur aus Kontrollen, die alle Fahrzeuge zählen (`alle_gezaehlt`); Berlin hat viele, die nur
  Überschreitungen zählen, Köln (und Bonn, sobald es einen Leser gibt) nennt nur Verstöße –
  dann „kein Wert“, nie 100 %. In Köln ist eine „Kontrolle“ alle Verstöße eines Standorts an
  einem Tag (so steht es auch in der Karte); feste Anlagen gehören nicht dazu. Fehlende Werte
  sind leer, nie 0.
  Hohe Quoten nicht als „hier wird am meisten gerast“ formulieren (Kontrollen sind keine
  Stichprobe).
- **Lizenz:** AGPL-3.0-or-later; neue Quelldateien mit SPDX-Kopfzeile.

## Konventionen
- **uv**, nie `pip install`. Alles aus `pipeline/`: `uv run kontrollen <befehl>`,
  `uv run pytest`, `uv run ruff check`, `uv run ruff format`.
- **Sprache:** Deutsch – UI, Doku, Kommentare und Bezeichner.
- **Tests:** `npm run test:unit`, `npm run test:web` (lokal ohne heruntergeladenen Browser:
  `PW_CHANNEL=chrome npm run test:web`). Die Browser-Tests suchen sich ihre Fälle aus den
  Kartendaten selbst – keine festen Messstellen oder Pixel.
- **Ohne Netz entwickeln:** Workflow „Entwicklungsauszug“ (auch per Push auf
  `dev/auszug-anfordern`) legt OSM-Tabellen, die Berliner PDF-Anlagen und die Rohdateien von
  Aachen, Köln und Bonn auf `dev/auszug` (große CSV gzip-komprimiert); `git fetch origin
  dev/auszug` und nach `pipeline/data/` kopieren (siehe `pipeline/README.md`).
