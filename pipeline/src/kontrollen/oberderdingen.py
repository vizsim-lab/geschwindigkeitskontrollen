# SPDX-License-Identifier: AGPL-3.0-or-later
"""Oberderdingen (Landkreis Karlsruhe): kommunale Geschwindigkeitsmessungen des Landratsamts.

Die Stadt veröffentlicht je Quartal eine Tabelle als PDF: Datum, Messstelle/Straße,
festgesetzte Geschwindigkeit, Zahl der gemessenen Fahrzeuge, Zahl der Beanstandungen (ab
Ende 2025 auch in Prozent). Eine Zeile ist eine **Kontrolle** mit allen gemessenen Fahrzeugen
(`alle_gezaehlt`); Uhrzeit, Dauer und Stufen fehlen.

Messstelle: „Oberderdingen, Flehingen, Franz-von-Sickingen-Straße 12, FR Derdinger Straße“ –
Stadt, Ortsteil (Flehingen, Großvillars), Straße mit Hausnummer oder „in Höhe …“, Fahrtrichtung.

**Beide Richtungen gezählt:** Stehen am selben Tag an derselben Stelle zwei Zeilen mit
derselben Zahl gemessener Fahrzeuge, aber verschiedener Fahrtrichtung (Flehinger Straße 27,
15.01.2026: je 1.762), hat das Gerät beide Richtungen zusammen gezählt – dann ist das eine
Kontrolle mit den Beanstandungen beider Zeilen (sonst zählte die Karte die Fahrzeuge doppelt).

Id: `O<Datum>-<Kurzzeichen der Messstelle>`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from kontrollen import dokumente
from kontrollen.adressen import adresse
from kontrollen.schema import in_schema

ORTSTEILE = ("Flehingen", "Großvillars", "Oberderdingen")
_DATUM = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")
_FR = re.compile(r"^(?:FR|Fahrtrichtung)\.?\s+(?P<ziel>.+)$")


def _zahl(s: str | None) -> int | None:
    t = re.sub(r"[.\s]", "", str(s or ""))
    return int(t) if t.isdigit() else None


def zeilen(pfad: Path) -> list[dict]:
    """Die Tabellenzeilen eines PDF -> Datum, Messstelle, Tempo, Fahrzeuge, Beanstandungen."""
    out = []
    for z in dokumente.tabellen(pfad):
        if not z or not z[0]:
            continue
        m = _DATUM.match(z[0])
        if not m or len(z) < 5:
            continue
        tag, monat, jahr = (int(x) for x in m.groups())
        out.append(
            {
                "datum": datetime(jahr, monat, tag).strftime("%Y-%m-%d"),
                "ort": dokumente.glaette(z[1]),
                "tempo": _zahl(z[2]),
                "messungen": _zahl(z[3]),
                "ueberschreitungen": _zahl(z[4]),
            }
        )
    return out


def messstelle(text: str) -> dict:
    """ "Oberderdingen, Flehingen, Bahnbrücker Straße 11, FR Franz-von-Sickingen-Straße" ->
    Ortsteil, Straße, Nummer, Kreuzung, Richtung."""
    teile = [t.strip() for t in text.split(",") if t.strip()]
    ortsteil, richtung = None, None
    while teile and teile[0] in ORTSTEILE:
        ortsteil = teile.pop(0)  # „Oberderdingen, Flehingen, …“ -> Flehingen
    if teile and (fr := _FR.match(teile[-1])):
        richtung = fr.group("ziel").strip(" .")
        teile.pop()
    a = adresse(", ".join(teile))
    return {
        "bezirk_roh": ortsteil,
        "richtung_roh": richtung,
        "strasse": a.strasse,
        "hausnummer": a.hausnummer,
        "gegenueber": a.gegenueber,
        "lage_art": "kreuzung" if a.quer else "keine",
        "quer1": a.quer,
    }


def _ohne_richtung(ort: str) -> str:
    return re.sub(r",\s*(?:FR|Fahrtrichtung)\.?\s+[^,]+$", "", ort)


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, dict]:
    bericht = {"dateien": [], "hinweise": [], "beide_richtungen": 0}
    roh = []
    for f in sorted(dateien):
        try:
            z = zeilen(f)
        except Exception as e:  # kaputte Datei: melden, weiter
            bericht["hinweise"].append(f"{f.name}: nicht lesbar ({e})")
            continue
        for r in z:
            r["quelle"] = f.name.split("__")[0]
        bericht["dateien"].append({"datei": f.name, "zeilen": len(z)})
        roh += z
    df = pd.DataFrame(roh)
    if df.empty:
        return in_schema(df), bericht
    df = df.drop_duplicates(["datum", "ort", "messungen", "ueberschreitungen"])
    df["stelle"] = df["ort"].map(_ohne_richtung)
    zeilen_out = []
    for (datum, stelle, _), g in df.groupby(["datum", "stelle", "messungen"], dropna=False):
        beide = len(g) > 1 and g["ort"].nunique() > 1  # beide Richtungen in einer Zählung
        if beide:
            bericht["beide_richtungen"] += 1
            teile = [
                g.iloc[0].to_dict()
                | {"ort": stelle, "ueberschreitungen": g["ueberschreitungen"].sum()}
            ]
        else:
            teile = [r.to_dict() for _, r in g.iterrows()]
        for r in teile:
            ms = messstelle(r["ort"])
            if beide:
                ms["richtung_roh"] = "beide"
            kurz = hashlib.sha1(r["ort"].encode("utf-8")).hexdigest()[:6]
            zeilen_out.append(
                {
                    "id": f"O{datum}-{kurz}",
                    "stadt": "oberderdingen",
                    "quelle": r["quelle"],
                    "datum": datum,
                    "strasse_roh": r["ort"],
                    **ms,
                    "tempo": r["tempo"],
                    "messungen": r["messungen"],
                    "ueberschreitungen": r["ueberschreitungen"],
                    "alle_gezaehlt": r["messungen"] is not None
                    and not pd.isna(r["messungen"])
                    and r["ueberschreitungen"] is not None
                    and not pd.isna(r["ueberschreitungen"])
                    and r["messungen"] >= r["ueberschreitungen"],
                }
            )
    out = in_schema(pd.DataFrame(zeilen_out))
    bericht["kontrollen"] = int(len(out))
    return out, bericht
