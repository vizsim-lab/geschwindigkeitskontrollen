# SPDX-License-Identifier: AGPL-3.0-or-later
"""Berlin: temporäre Geschwindigkeitskontrollen 2017 bis August 2020 (Polizei Berlin, IFG).

Je Zeitraum eine Anlage zum Bescheid vom 09.12.2020 (PDF, gelesen von `berlin_pdf.py`), eine
Zeile je Kontrolle. Was in den Zellen steht und wie es gelesen wird:

- **„Nr.“**: Hausnummer ("423"), gegenüber ("g232"), vermutlich Lichtmast ("L2980"), an der
  Autobahn auch Kilometer ("k16,5" – bleibt ungenutzt).
- **Abgeschnittene Straßennamen**, deren Rest in „Nr.“ steht ("Charlottenburger Chauss" +
  "ee 43", in den CSV-Zeilen von 2018): der Rest wird angehängt; was dann noch fehlt
  ("Platz der Vereinten Nation"), findet die Verortung über den Anfang des Namens.
- **„zwischen“**: "A u. B" (Abschnitt zwischen zwei Querstraßen), "/C" (an der Kreuzung mit C)
  oder ein Ort ("AS Kaiserdamm", "Knobelsdorffbrücke").
- **„Verwaltungsbezirk“**: ein oder mehrere Bezirke, oft abgeschnitten
  ("Charlottenburg-Wilmersdorf, Mitt") – gelesen wird der Anfang.
- **„erlaubte Geschwindigkeit“**: "50/30" oder "30/50" (wechselndes Limit, ohne Angabe wann)
  bleibt leer.
- **Datum, Beginn, Ende**: endet eine Kontrolle vor ihrem Beginn, lief sie über Mitternacht;
  mehrtägige tragen das Datum in Beginn und Ende.
- **„-“** in den Stufen und Fahrverboten heißt keine Angabe – leer, nicht 0.
- **Messungen = Überschreitungen** (ein Drittel der Kontrollen, vor allem Autobahn): dann sind
  nur die zu schnellen Fahrzeuge erfasst; einen Anteil gibt es dort nicht (`alle_gezaehlt`).

Die Id einer Kontrolle ist Jahr der Anlage und Zeile darin: "B2019-00001".
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from kontrollen import berlin_pdf, namen
from kontrollen.schema import in_schema

# Rest eines abgeschnittenen Namens vor der Nummer: "-Str 31", "ee L47", "n g1"
_UEBERLAUF = re.compile(r"^([A-Za-zÄÖÜäöüß.\-]+)\s+(\S.*)$")
_CODE = re.compile(r"^g?L?\d|^[gG]$|^[kK]\d")


def repariere_ueberlauf(strasse: str, nr: str) -> tuple[str, str]:
    """("Charlottenburger Chauss", "ee 43") -> ("Charlottenburger Chaussee", "43")."""
    m = _UEBERLAUF.match(nr or "")
    if not m or _CODE.match(m.group(1)):
        return strasse, nr
    return f"{strasse}{m.group(1)}", m.group(2).strip()


def bezirke(roh: str | None) -> list[str]:
    """ "Charlottenburg-Wilmersdorf, Mitt" -> ["Charlottenburg-Wilmersdorf", "Mitt"]."""
    return [t.strip() for t in str(roh or "").split(",") if t.strip()]


def tempo(roh: str | None) -> int | None:
    """ "50" -> 50; "50/30", "", "0" -> None (kein eindeutiges Limit)."""
    t = str(roh or "").strip()
    return int(t) if t.isdigit() and int(t) > 0 else None


def lies(anlagen: list[tuple[dict, Path]]) -> tuple[pd.DataFrame, list[dict]]:
    """Alle Anlagen -> Kontrollen im gemeinsamen Schema, dazu ein Bericht je Datei.

    `anlagen`: (Eintrag aus sources.yaml mit `jahr`, Pfad der PDF-Datei)."""
    zeilen: list[dict] = []
    berichte: list[dict] = []
    for anlage, pfad in anlagen:
        bericht = berlin_pdf.Bericht(pfad.name)
        roh = berlin_pdf.zeilen(pfad, bericht)
        jahr = int(anlage["jahr"])
        fremd = 0
        for r in roh:
            try:
                z = zeile(r, f"B{jahr}-{r['zeile']:05d}", pfad.stem, bericht)
            except ValueError as e:  # ohne lesbares Datum keine Kontrolle
                bericht.fehler.append(f"S. {r['seite']}: {e}")
                continue
            fremd += not z["datum"].startswith(str(jahr))
            zeilen.append(z)
        b = bericht.als_dict()
        b["jahr"] = jahr
        b["andere_jahre"] = fremd  # Zeilen, deren Datum nicht im Jahr der Anlage liegt
        berichte.append(b)
    return in_schema(pd.DataFrame(zeilen)), berichte


def zeile(r: dict, id_: str, quelle: str, bericht: berlin_pdf.Bericht | None = None) -> dict:
    """Eine Zeile der Polizei-Tabelle (Spalten wie `berlin_pdf.KOPF`) -> gemeinsames Schema."""

    def zahl(spalte: str) -> int | None:
        try:
            return berlin_pdf.zahl(r[spalte])
        except ValueError as e:
            if bericht is not None:
                bericht.fehler.append(f"{id_} {spalte}: {e}")
            return None

    strasse_roh, nr_roh = r["Straßenname"], r["Nr."]
    strasse, nr = repariere_ueberlauf(strasse_roh.strip(), nr_roh.strip())
    num = namen.nummer(nr)
    lg = namen.lage(r["zwischen"])
    ri = namen.richtung(r["Richtung"])
    ab = namen.autobahn(strasse)
    beginn, ende = berlin_pdf.zeitraum(r["Datum"], r["Beginn"], r["Ende"])
    dauer = (ende - beginn).total_seconds() / 60 if ende is not None else None
    if dauer is not None and dauer < 0:
        dauer = None
    messungen = zahl("Messungen")
    ueber = zahl("Überschreitungen")
    quer = list(lg.namen) + [None, None]
    return {
        "id": id_,
        "stadt": "berlin",
        "quelle": quelle,
        "datum": beginn.strftime("%Y-%m-%d"),
        "beginn": beginn.strftime("%H:%M"),
        "dauer_min": dauer,
        "strasse_roh": strasse_roh,
        "nr_roh": nr_roh,
        "lage_roh": r["zwischen"],
        "bezirk_roh": r["Verwaltungsbezirk"],
        "richtung_roh": r["Richtung"],
        "strasse": strasse,
        "hausnummer": num.hausnummer,
        "gegenueber": num.gegenueber,
        "mast": num.mast,
        "lage_art": lg.art,
        "quer1": quer[0] if lg.art != "ort" else None,
        "quer2": quer[1] if lg.art == "zwischen" else None,
        # "BAB A 100 AS Messedamm": der Ort steckt im Straßennamen
        "ort": lg.namen[0] if lg.art == "ort" else (ab[1] if ab and ab[1] else None),
        "autobahn": ab[0] if ab else None,
        "kompass": ri.kompass,
        "richtung_ziel": ri.ziel,
        "tempo": tempo(r["erlaubte Geschwindigkeit"]),
        "messungen": messungen,
        "ueberschreitungen": ueber,
        "stufe1": zahl("bis 20 km/h"),
        "stufe2": zahl("über 20 km/h"),
        "stufe_kmh": 20,
        "fahrverbote": zahl("Fahrverbote"),
        "alle_gezaehlt": (messungen is not None and ueber is not None and messungen > ueber),
    }
