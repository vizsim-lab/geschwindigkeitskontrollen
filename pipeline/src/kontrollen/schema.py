# SPDX-License-Identifier: AGPL-3.0-or-later
"""Das gemeinsame Schema einer Kontrolle – beide Städte liefern diese Spalten.

Zahlen, die eine Quelle nicht kennt, bleiben leer (<NA>), nie 0: Aachen nennt (bisher)
weder Dauer noch Tempolimit, Berlin hat zu jeder Kontrolle Beginn und Ende.
"""

from __future__ import annotations

import pandas as pd

SPALTEN: dict[str, str] = {
    "id": "string",  # "B00001" (Berlin, Zeile der Quelle), "A…" (Aachen, Datei + Zeile)
    "stadt": "string",  # "berlin" | "aachen"
    "quelle": "string",  # Datei bzw. Lieferung
    "datum": "string",  # YYYY-MM-DD
    "beginn": "string",  # HH:MM, wenn bekannt
    "dauer_min": "Int64",
    "strasse_roh": "string",
    "nr_roh": "string",
    "lage_roh": "string",  # Berlin „zwischen“, Aachen leer
    "bezirk_roh": "string",
    "richtung_roh": "string",
    "strasse": "string",  # repariert, für die Suche
    "hausnummer": "string",
    "gegenueber": "boolean",
    "mast": "string",
    "lage_art": "string",  # zwischen | kreuzung | ort | keine
    "quer1": "string",
    "quer2": "string",
    "ort": "string",  # Ort statt Querstraße: "AS Kaiserdamm", "Knobelsdorffbrücke", "ICC"
    "autobahn": "string",  # "A 100"
    "kompass": "string",  # "NW"
    "richtung_ziel": "string",
    "tempo": "Int64",
    "messungen": "Int64",
    "ueberschreitungen": "Int64",
    "stufe1": "Int64",  # Berlin: bis 20 km/h, Aachen 2020: bis 15 bzw. 20 km/h
    "stufe2": "Int64",  # darüber
    "stufe_kmh": "Int64",  # Grenze zwischen stufe1 und stufe2 (Berlin 20, Aachen 2020: 15/20)
    "fahrverbote": "Int64",
    "alle_gezaehlt": "boolean",  # Messungen = alle Fahrzeuge (sonst nur die zu schnellen)
}


def leer(n: int = 0) -> pd.DataFrame:
    return pd.DataFrame({k: pd.Series([None] * n, dtype=t) for k, t in SPALTEN.items()})


def in_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Spalten ergänzen/ordnen und Typen setzen (fehlende Spalten -> leer)."""
    out = pd.DataFrame(index=df.index)
    for k, t in SPALTEN.items():
        s = df[k] if k in df else pd.Series([None] * len(df), index=df.index)
        if t == "Int64":
            s = pd.to_numeric(s, errors="coerce").round().astype("Int64")
        elif t == "boolean":
            s = s.astype("boolean")
        else:
            s = s.astype("string").str.strip().replace({"": pd.NA})
        out[k] = s
    return out.reset_index(drop=True)
