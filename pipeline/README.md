# kontrollen – Pipeline

uv-Paket, das aus den Rohdaten (Berlin, Aachen) und einem OSM-Abzug die Kartendaten baut.
Alle Befehle aus `pipeline/` heraus:

```bash
uv sync
uv run kontrollen info       # Pfade, Quellen, was fehlt
uv run kontrollen fetch      # Berlin-CSV (Prüfsumme) + Aachener Monatsdateien; --osm: OSM-Abzüge; --neu: Aachener Katalog neu fragen
uv run kontrollen osm        # OSM-PBF -> data/interim/osm/*.parquet (Straßen, Adressen, Anschlussstellen, Gebiete)
uv run kontrollen build      # Rohdaten -> data/interim/kontrollen.parquet (gemeinsames Schema)
uv run kontrollen geocode    # Verortung -> data/geokodierung.csv + geokodierung_validierung.json
uv run kontrollen site       # Kartendaten -> data/karte/*
uv run kontrollen alles      # fetch + build + (geocode) + site; --osm lädt und liest OSM neu

uv run pytest                # Tests an tests/fixtures, ohne Netz
uv run ruff check && uv run ruff format --check
```

*Ausführliche Beschreibung folgt.*
