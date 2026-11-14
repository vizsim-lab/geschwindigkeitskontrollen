# SPDX-License-Identifier: AGPL-3.0-or-later
"""Butzbach (Wetteraukreis): Geschwindigkeitsmessungen im gemeinsamen Ordnungsbehördenbezirk
Butzbach/Münzenberg/Rockenberg/Wölfersheim.

Die Stadt stellt je Monat einen Beitrag mit einer Tabelle als PDF auf ihre Seite
(„sb_oa-messung-2604.pdf“): Tag, von, bis, Gesamtstunden, Gesamt Fahrzeuge, Verwarnungen,
Bußgelder, Verstöße in %, Messstelle. Eine Zeile ist eine **Kontrolle** mit allen gemessenen
Fahrzeugen (`alle_gezaehlt`), Beginn und Dauer; Überschreitungen = Verwarnungen + Bußgelder.
Das Tempolimit nennt die Tabelle nicht. Unter den Kontrollen stehen eine leere Vorlagezeile und
die Summen – beide ohne Datum.

Messstelle: „Butzbach/Griedel, L3134 ggü Rockenberger Str.“ – Gemeinde und Ortsteil, dann
Straße (oder Straßennummer) mit Hausnummer, Querstraße („Ecke …“, „/ Seedammweg“, „ggü
Weidbrunnenstraße 2A“) oder einem Ort („/ Kiga Löwenherz“, „/ Parkplatz EDEKA“). Gesucht wird
zuerst im genannten Ortsteil, sonst in der genannten Gemeinde (`bezirk_roh`).

Id: `U<Datum>-<Beginn>-<Kurzzeichen der Messstelle>`, z. B. `U2026-04-01-0645-3f2a`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from kontrollen import dokumente
from kontrollen.adressen import adresse
from kontrollen.schema import in_schema
from kontrollen.weiterstadt import strassennummer

GEMEINDEN = ("Butzbach", "Münzenberg", "Rockenberg", "Wölfersheim")
# „01.04.2026“, auch „09.04..2026“ und „1.4.26“ (so steht es in den Tabellen)
_DATUM = re.compile(r"^\s*(\d{1,2})\s*\.+\s*(\d{1,2})\s*\.+\s*(\d{2}|\d{4})\s*$")
_UHR = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*(?:Uhr)?\s*$")
# Spalten nach ihrem Kopf (die Reihenfolge könnte wechseln)
_SPALTEN = {
    "tag": re.compile(r"(?i)^(?:tag|datum)"),
    "von": re.compile(r"(?i)^von"),
    "bis": re.compile(r"(?i)bis$|^…?\s*bis"),
    "dauer": re.compile(r"(?i)stun"),
    "fahrzeuge": re.compile(r"(?i)fahrzeuge"),
    "verwarnungen": re.compile(r"(?i)verwarn"),
    "bussgelder": re.compile(r"(?i)bu(?:ß|ss)geld"),
    "messstelle": re.compile(r"(?i)messstelle|ort"),
}
# „ggü Rockenberger Str.“ (gegenüber einer Straße) ist eine Querangabe, „ggü 12“ eine Hausnummer
_GGUE_STRASSE = re.compile(
    r"\bgg(?:ü|ue)\.?\s+(?:in\s+H(?:ö|oe)he\s+)?(?:Grundst(?:ü|ue)ck\s+)?(?=[A-ZÄÖÜ])"
)
_NEBEN = re.compile(r"(?i),?\s*\bneben\s+(?=[A-ZÄÖÜ])")
_NUMMER_HINTEN = re.compile(
    r"\s*(?:In\s+H(?:ö|oe)he\s+)?\d{1,4}\s*[a-zA-Z]?(?:\s*[-/]\s*\d{1,4}\s*[a-zA-Z]?)?$"
)


def _zahl(s: str | None) -> int | None:
    t = re.sub(r"[.\s]", "", str(s or ""))
    return int(t) if t.isdigit() else None


def _uhrzeit(s: str | None) -> tuple[int, int] | None:
    m = _UHR.match(str(s or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return (h, mi) if h < 24 and mi < 60 else None


def spalten(kopf: list[str | None]) -> dict[str, int]:
    """Kopfzeile -> Spaltennummern (tag, von, bis, dauer, fahrzeuge, verwarnungen, …)."""
    out: dict[str, int] = {}
    for i, zelle in enumerate(kopf):
        t = " ".join(str(zelle or "").replace("\n", " ").split())
        for name, muster in _SPALTEN.items():
            if name not in out and t and muster.search(t):
                out[name] = i
                break
    return out


def zeilen(pfad: Path) -> list[dict]:
    """Die Tabellenzeilen eines PDF -> Datum, Beginn, Ende, Dauer, Fahrzeuge, Verwarnungen,
    Bußgelder, Messstelle. Zeilen ohne Datum (Kopf, Vorlage, Summe) fallen weg."""
    out, sp = [], None
    for z in dokumente.tabellen(pfad):
        if not z:
            continue
        k = spalten(z)
        if {"tag", "fahrzeuge", "messstelle"} <= set(k):
            sp = k
            continue
        if sp is None:
            continue
        m = _DATUM.match(str(z[sp["tag"]] or ""))
        if not m:
            continue
        tag, monat, jahr = (int(x) for x in m.groups())
        jahr += 2000 if jahr < 100 else 0

        def zelle(name: str, z=z, sp=sp) -> str | None:
            i = sp.get(name)
            return z[i] if i is not None and i < len(z) else None

        out.append(
            {
                "datum": datetime(jahr, monat, tag),
                "von": _uhrzeit(zelle("von")),
                "bis": _uhrzeit(zelle("bis")),
                "dauer": _uhrzeit(zelle("dauer")),
                "messungen": _zahl(zelle("fahrzeuge")),
                "verwarnungen": _zahl(zelle("verwarnungen")),
                "bussgelder": _zahl(zelle("bussgelder")),
                "ort": dokumente.glaette(zelle("messstelle")),
            }
        )
    return out


def messstelle(text: str) -> dict:
    """ "Butzbach/Griedel, L3134 ggü Rockenberger Str." -> Ortsteil, Straße, Nummer, Kreuzung."""
    t = " ".join(text.split())
    gemeinde = ortsteil = None
    kopf, _, rest = t.partition(",")
    teile = [x.strip() for x in kopf.split("/")]
    if teile[0] in GEMEINDEN and rest.strip():
        gemeinde = teile[0]
        ortsteil = teile[1] if len(teile) > 1 and teile[1] else None
        t = rest.strip()
    t = re.sub(r"(?<=[a-zäöü])sr\.", "str.", t)  # „Alte Hauptsr.“
    t = _NEBEN.sub(" Höhe ", t)
    t = _GGUE_STRASSE.sub("Höhe ", t)
    links, schraeg, rechts = (x.strip() for x in t.partition(" / "))
    a = adresse(links if schraeg else t)
    quer = a.quer
    if schraeg and rechts and not quer and not a.hausnummer:
        quer = rechts  # „Tepler Str. / Seedammweg“, „B455 / Seestr. In Höhe 60-62“
    if quer:  # ein Ort („Kiga Löwenherz“) sucht die Verortung als Ort neben der Straße
        quer = _NUMMER_HINTEN.sub("", quer).strip(" .,") or None
    strasse = strassennummer(a.strasse) or a.strasse
    return {
        "bezirk_roh": ortsteil or gemeinde,
        "strasse": strasse,
        "hausnummer": a.hausnummer,
        "gegenueber": a.gegenueber,
        "lage_art": "kreuzung" if quer else "keine",
        "quer1": quer,
    }


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, dict]:
    bericht: dict = {"dateien": [], "hinweise": [], "doppelt": 0}
    out, gesehen = [], set()
    for f in sorted(dateien):
        try:
            z = zeilen(f)
        except Exception as e:  # kaputte Datei: melden, weiter
            bericht["hinweise"].append(f"{f.name}: nicht lesbar ({e})")
            continue
        if not z:
            bericht["hinweise"].append(f"{f.name}: keine Tabellenzeilen")
        n = 0
        for r in z:
            schluessel = (r["datum"], r["von"], r["ort"])
            if schluessel in gesehen:  # derselbe Monat zweimal hochgeladen
                bericht["doppelt"] += 1
                continue
            gesehen.add(schluessel)
            out.append(_zeile(r, f.name.split("__")[0], bericht))
            n += 1
        bericht["dateien"].append({"datei": f.name, "kontrollen": n})
    df = in_schema(pd.DataFrame(out))
    bericht["kontrollen"] = int(len(df))
    return df, bericht


def _zeile(r: dict, quelle: str, bericht: dict) -> dict:
    beginn = r["datum"].replace(hour=r["von"][0], minute=r["von"][1]) if r["von"] else None
    dauer = r["dauer"][0] * 60 + r["dauer"][1] if r["dauer"] else None
    if dauer is None and beginn is not None and r["bis"]:
        ende = r["datum"].replace(hour=r["bis"][0], minute=r["bis"][1])
        if ende < beginn:
            ende += timedelta(days=1)
        dauer = int((ende - beginn).total_seconds() // 60)
    w, b = r["verwarnungen"], r["bussgelder"]
    ueber = w + b if w is not None and b is not None else None
    if ueber is None:
        bericht["hinweise"].append(f"{quelle}: Verwarnungen/Bußgelder fehlen ({r['ort'][:40]})")
    alle = r["messungen"] is not None and ueber is not None and r["messungen"] >= ueber
    kurz = hashlib.sha1(r["ort"].encode("utf-8")).hexdigest()[:4]
    zeit = f"{beginn:%H%M}" if beginn else "0000"
    return {
        "id": f"U{r['datum']:%Y-%m-%d}-{zeit}-{kurz}",
        "stadt": "butzbach",
        "quelle": quelle,
        "datum": f"{r['datum']:%Y-%m-%d}",
        "beginn": f"{beginn:%H:%M}" if beginn else None,
        "dauer_min": dauer,
        "strasse_roh": r["ort"],
        **messstelle(r["ort"]),
        "messungen": r["messungen"],
        "ueberschreitungen": ueber,
        "alle_gezaehlt": alle,
    }
