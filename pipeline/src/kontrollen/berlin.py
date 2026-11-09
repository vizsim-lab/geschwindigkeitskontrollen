# SPDX-License-Identifier: AGPL-3.0-or-later
"""Berlin: temporäre Geschwindigkeitskontrollen 2017–2019 (Polizei Berlin, IFG-Auskunft).

Eine Zeile je Kontrolle. Was die Aufbereitung aus dem PDF mitbringt und hier repariert wird:

- **Abgeschnittene Straßennamen**, deren Rest ins Feld „Nr.“ gerutscht ist:
  "Manfred-von-Richthofen" + "-Str 31", "Charlottenburger Chauss" + "ee 43". Der Rest wird
  angehängt; was dann noch fehlt ("Platz der Vereinten Nation"), findet die Verortung über
  den Anfang des Namens.
- **„Nr.“**: Hausnummer ("423"), gegenüber ("g232"), vermutlich Lichtmast ("L2980").
- **„zwischen“**: "A u. B" (Abschnitt zwischen zwei Querstraßen), "/C" (an der Kreuzung mit C)
  oder ein Ort ("AS Kaiserdamm", "Knobelsdorffbrücke").
- **„Verwaltungsbezirk“**: ein oder zwei Bezirke, nach 32 Zeichen abgeschnitten
  ("Charlottenburg-Wilmersdorf, Mitt") – gelesen wird der Anfang.
- **Messungen = Überschreitungen** (ein Drittel der Kontrollen, vor allem Autobahn): dann sind
  nur die zu schnellen Fahrzeuge erfasst; einen Anteil gibt es dort nicht (`alle_gezaehlt`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from kontrollen import namen
from kontrollen.schema import in_schema

QUELLE = "berlin-2017-2019-v01"

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


def lies(pfad: Path) -> pd.DataFrame:
    roh = pd.read_csv(pfad, sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    zeilen = []
    for i, r in enumerate(roh.to_dict("records"), start=1):
        strasse, nr = repariere_ueberlauf(r["Straßenname"].strip(), r["Nr."].strip())
        num = namen.nummer(nr)
        lg = namen.lage(r["zwischen"])
        ri = namen.richtung(r["Richtung"])
        ab = namen.autobahn(strasse)
        beginn = pd.Timestamp(r["Beginn_date"])
        ende = pd.Timestamp(r["Ende_date"]) if r["Ende_date"] else pd.NaT
        dauer = (ende - beginn).total_seconds() / 60 if pd.notna(ende) else None
        messungen = _zahl(r["Messungen"])
        ueber = _zahl(r["Überschreitungen"])
        tempo = _zahl(r["erlaubte Geschwindigkeit"])
        quer = list(lg.namen) + [None, None]
        zeilen.append(
            {
                "id": f"B{i:05d}",
                "stadt": "berlin",
                "quelle": QUELLE,
                "datum": beginn.strftime("%Y-%m-%d"),
                "beginn": beginn.strftime("%H:%M"),
                "dauer_min": dauer,
                "strasse_roh": r["Straßenname"],
                "nr_roh": r["Nr."],
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
                "tempo": tempo if tempo else None,  # 0 = keine Angabe
                "messungen": messungen,
                "ueberschreitungen": ueber,
                "stufe1": _zahl(r["bis 20 km/h"]),
                "stufe2": _zahl(r["über 20 km/h"]),
                "fahrverbote": _zahl(r["Fahrverbote"]),
                "alle_gezaehlt": (
                    messungen is not None and ueber is not None and messungen > ueber
                ),
            }
        )
    return in_schema(pd.DataFrame(zeilen))


def _zahl(v) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None
