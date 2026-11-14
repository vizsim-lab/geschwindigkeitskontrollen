# SPDX-License-Identifier: AGPL-3.0-or-later
"""Weiterstadt (Landkreis Darmstadt-Dieburg): mobile Geschwindigkeitskontrollen der Kommunalen
Bußgeldstelle.

Die Stadt veröffentlicht seit Januar 2025 je Monat eine Tabelle als PDF („Statistik GemOBB“):
Datum, „Straße, Hausnummer, Fahrtrichtung“, zulässige Höchstgeschwindigkeit, durchfahrene
Fahrzeuge, davon mit Geschwindigkeitsüberschreitung. Eine Zeile ist eine **Kontrolle** mit allen
gemessenen Fahrzeugen (`alle_gezaehlt`); Uhrzeit, Dauer und Stufen fehlen.

Messstelle: „Gräfenhäuser Straße 17, FR Gräfenhausen“, „Darmstädter Landstraße HH Nr. 55 FR
L3113“, „B42, Höhe Vor den Löserbecken, FR Darmstadt“, „L 3113 FR Weiterstadt“ – Straße oder
Straßennummer (B 42, L 3113, K 165), Hausnummer („HH Nr.“, „Höhe Nr.“) oder „Höhe …“ (Querstraße
oder Ort), zuletzt die Fahrtrichtung („FR“, „Fr.“).

Id: `W<Datum>-<Kurzzeichen der Messstelle>`, eine zweite gleiche Zeile `…-2`.
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

_DATUM = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")
_FR = re.compile(r"(?:,\s*|\s+)(?:FR|Fr)\b\.?\s*(?P<ziel>[^,]+?)\s*$")
# Straßennummer vorn: „B42“, „L 3113“, „K 165“ (Bundes-, Landes-, Kreisstraße)
_NUMMER = re.compile(r"^(?P<art>[BLK])\s?(?P<nr>\d{1,4})$")
_NUMMER_ORT = re.compile(
    r"^(?P<nr>[BLK]\s?\d{1,4})\s+(?!(?:H(?:ö|oe)he|vor|hinter|bei|zwischen)\b)(?P<ort>\S.*)$",
    re.I,
)
_HH_NR = re.compile(r"\bHH\s*Nr\b\.?")
_HH = re.compile(r"\bHH\b")
_EINMUENDUNG = re.compile(
    r"(?i)^(?:(?:hinter|vor)\s+(?:der\s+)?)?(?:einm(?:ü|ue)ndung|kreuzung)\s+"
)


def _zahl(s: str | None) -> int | None:
    t = re.sub(r"[.\s]", "", str(s or ""))
    return int(t) if t.isdigit() else None


def zeilen(pfad: Path) -> list[dict]:
    """Die Tabellenzeilen eines PDF -> Datum, Messstelle, Tempo, Fahrzeuge, Überschreitungen.
    Leerzeilen zwischen den Kontrollen und der Kopf haben kein Datum."""
    out = []
    for z in dokumente.tabellen(pfad):
        if not z or len(z) < 5 or not z[0]:
            continue
        m = _DATUM.match(z[0])
        if not m:
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


def strassennummer(text: str | None) -> str | None:
    """ "B42", "L 3113" -> "B 42", "L 3113" (wie `ref` in OSM); sonst None."""
    m = _NUMMER.match(" ".join(str(text or "").split()))
    return f"{m['art']} {int(m['nr'])}" if m else None


def messstelle(text: str) -> dict:
    """ "L3113, Höhe Weiterstädter Weg, FR Mörfelden-Walldorf" -> Straße, Nummer, Kreuzung,
    Richtung."""
    t = " ".join(re.sub(r"\([^)]*\)", " ", text).split())  # „Vor den Löserbecken (JVA)“
    richtung = None
    if fr := _FR.search(t):
        richtung = fr.group("ziel").strip(" .")
        t = t[: fr.start()]
    t = _HH_NR.sub("Hausnr.", t)  # „HH Nr. 55“ = Hausnummer
    t = _HH.sub("Höhe", t)  # „R.-Diesel-Straße HH Feuerwehr“
    if m := _NUMMER_ORT.match(t):  # „B42 BAB5 Anschlussstelle SW“: ein Ort ohne „Höhe“
        t = f"{m['nr']} Höhe {m['ort']}"
    a = adresse(t)
    strasse = strassennummer(a.strasse) or a.strasse
    quer = _EINMUENDUNG.sub("", a.quer).strip() or None if a.quer else None
    return {
        "richtung_roh": richtung,
        "strasse": strasse,
        "hausnummer": a.hausnummer,
        "gegenueber": a.gegenueber,
        "lage_art": "kreuzung" if quer else "keine",
        "quer1": quer,
    }


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, dict]:
    bericht: dict = {"dateien": [], "hinweise": [], "doppelt": 0}
    roh = []
    for f in sorted(dateien):
        try:
            z = zeilen(f)
        except Exception as e:  # kaputte Datei: melden, weiter
            bericht["hinweise"].append(f"{f.name}: nicht lesbar ({e})")
            continue
        if not z:
            bericht["hinweise"].append(f"{f.name}: keine Tabellenzeilen")
        for r in z:
            r["quelle"] = f.name.split("__")[0]
        bericht["dateien"].append({"datei": f.name, "zeilen": len(z)})
        roh += z
    df = pd.DataFrame(roh)
    if df.empty:
        return in_schema(df), bericht
    # derselbe Monat zweimal hochgeladen: jede Zeile einmal
    vorher = len(df)
    df = df.drop_duplicates(["datum", "ort", "tempo", "messungen", "ueberschreitungen"])
    bericht["doppelt"] = int(vorher - len(df))
    zeilen_out = []
    for r in df.itertuples(index=False):
        kurz = hashlib.sha1(r.ort.encode("utf-8")).hexdigest()[:6]
        alle = (
            r.messungen is not None
            and not pd.isna(r.messungen)
            and r.ueberschreitungen is not None
            and not pd.isna(r.ueberschreitungen)
            and r.messungen >= r.ueberschreitungen
        )
        zeilen_out.append(
            {
                "id": f"W{r.datum}-{kurz}",
                "stadt": "weiterstadt",
                "quelle": r.quelle,
                "datum": r.datum,
                "strasse_roh": r.ort,
                **messstelle(r.ort),
                "tempo": r.tempo,
                "messungen": r.messungen,
                "ueberschreitungen": r.ueberschreitungen,
                "alle_gezaehlt": alle,
            }
        )
    # zwei Kontrollen am selben Tag an derselben Stelle (andere Zahlen): eigene Ids
    gezaehlt: dict[str, int] = {}
    for z in zeilen_out:
        n = gezaehlt[z["id"]] = gezaehlt.get(z["id"], 0) + 1
        if n > 1:
            z["id"] = f"{z['id']}-{n}"
    out = in_schema(pd.DataFrame(zeilen_out))
    bericht["kontrollen"] = int(len(out))
    return out, bericht
