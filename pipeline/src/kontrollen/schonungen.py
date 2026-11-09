# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schonungen (Landkreis Schweinfurt): Monatsberichte der kommunalen Verkehrsüberwachung.

Die Gemeinde stellt die Berichte des Zweckverbands Kommunale Verkehrsüberwachung Südostbayern
als PDF (einige als Word-Datei) in ihre Mediathek. Je Messung ein Absatz:

    Messstelle Mainberg, St2447, Mainleite / Bereich Hs.-Nr. 28
    Zulässige Geschwindigkeit: 50 km/h
    Messzeitpunkt: Dienstag, 10.03.2026, 11:54 Uhr – 16:54 Uhr
    Anzahl der Fahrzeuge: 3193
    Verstöße: 34
    Überschreitung: 25 innerhalb bis 10 km/h über zul. Geschwindigkeit
    8 innerhalb, 11-15 km/h über zul. Geschwindigkeit

Eine Zeile ist eine **Kontrolle** mit allen gemessenen Fahrzeugen (`alle_gezaehlt`), Beginn
und Ende. Die Klassen ergeben bis/über 20 km/h; passen sie nicht zur Zahl der Verstöße
(Mai 2020: „10 bis 10 km/h“), bleiben die Stufen leer. Dieselbe Messung in zwei Dateien (ein
Bericht zweimal hochgeladen) zählt einmal. Berichte ohne Messstellen (Geschwindigkeitsanzeige
„mobiles Messgerät“) bringen nichts.

Messstelle: Gemeindeteil, Straßennummer (St2447, SW 25, B26 – ungenutzt), Straße, Bereich
(„Hs.-Nr. 28“, „Einm. Bachstraße“, „ggü. Hs.-Nr. 4“). Gemeindeteile haben in OSM keine
Grenzen; gesucht wird in der ganzen Gemeinde.

Id: `S<Datum>-<Beginn>-<Kurzzeichen der Messstelle>`, z. B. `S2026-03-10-1154-3f2a`.
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

STUFE_KMH = 20
GEMEINDETEILE = (
    "Schonungen", "Mainberg", "Abersfeld", "Forst", "Hausen", "Löffelsterz", "Marktsteinach",
    "Reichmannshausen", "Waldsachsen", "Ottenhausen", "Rednershof", "Schonungen-Kreuzthal",
)  # fmt: skip

_BLOCK = re.compile(r"(?m)^\s*Messstelle\s+")
_TEMPO = re.compile(r"Zul(?:ä|ae)ssige\s+Geschwindigkeit:?\s*(\d{1,3})\s*km/h", re.I)
_ZEIT = re.compile(
    r"Messzeitpunkt:?\s*[A-Za-zäöü]*,?\s*(?:den\s+)?(\d{1,2})\.(\d{1,2})\.(\d{4}),?\s*"
    r"0?(\d{1,2})[:.](\d{2})\s*(?:Uhr)?\s*(?:[–—-]|bis)?\s*0?(\d{1,2})[:.](\d{2})"
)  # „15:29 Uhr – 018:00 Uhr“, „05:45 Uhr 07:45 Uhr“: so steht es in den Berichten
_FAHRZEUGE = re.compile(r"Anzahl\s+(?:der\s+)?Fahrzeuge:?\s*([\d.]+)")
# „Verstöße: 7 innerhalb bis 10 km/h …“ (2025-06): die 7 ist die erste Klasse, nicht die Summe
_VERSTOESSE = re.compile(
    r"Verst(?:ö|oe)(?:ß|ss)e:?\s*(\d+)(?!\d|\s+(?:innerhalb|außerhalb|mit|bis))"
)
_KLASSE = re.compile(
    r"(?m)^\s*(?:Überschreitung:?\s*|Verst(?:ö|oe)(?:ß|ss)e:?\s*)?(\d+)\s+"
    r"(?:innerhalb|außerhalb|ausserhalb|mit)?,?\s*"
    r"(?:bis\s+(\d+)|(\d+)\s*[-–]\s*(\d+)|(?:ab|über)\s+(\d+))\s*km/h"
)
_REF = re.compile(r"^(?:St|ST|SW|B|K|L)\s?\d{1,4}[a-z]?$")
_REF_VORN = re.compile(r"^(?:St|ST|SW)\s?\d{1,4}\s+(?=[A-ZÄÖÜ])")  # „St2266 Marktstein. Hauptstr.“


def bloecke(text: str) -> list[str]:
    """Der Bericht in Absätze, je Messstelle einer (ohne das Wort „Messstelle“)."""
    teile = _BLOCK.split(text)
    return [t for t in teile[1:] if t.strip()]


def messungen(block: str) -> list[dict]:
    """Ein Absatz -> je Messzeitpunkt: Messstelle, Tempo, Beginn/Ende, Fahrzeuge, Verstöße,
    Stufen. Steht dieselbe Messstelle mehrmals hintereinander (2026-01), gilt der Ort für alle."""
    ende_ort = _TEMPO.search(block)
    zeiten = list(_ZEIT.finditer(block))
    if not ende_ort or not zeiten:
        return []
    ort = " ".join(block[: ende_ort.start()].split())
    out = []
    for i, z in enumerate(zeiten):
        teil = block[z.start() : zeiten[i + 1].start() if i + 1 < len(zeiten) else len(block)]
        tempo = _TEMPO.search(block[: z.start()][-200:]) or ende_ort
        out.append(_messung(ort, int(tempo.group(1)), z, teil))
    return out


def _messung(ort: str, tempo: int, z: re.Match, teil: str) -> dict:
    tag, monat, jahr, h1, m1, h2, m2 = (int(x) for x in z.groups())
    beginn = datetime(jahr, monat, tag, h1, m1)
    ende = datetime(jahr, monat, tag, h2, m2)
    if ende < beginn:
        ende += timedelta(days=1)
    fz = _FAHRZEUGE.search(teil)
    v = _VERSTOESSE.search(teil)
    verstoesse = int(v.group(1)) if v else None
    s1 = s2 = 0
    for k in _KLASSE.finditer(teil):
        n = int(k.group(1))
        oben = k.group(2) or k.group(4)
        if oben and int(oben) <= STUFE_KMH:
            s1 += n
        else:
            s2 += n
    if verstoesse is None and s1 + s2:
        verstoesse = s1 + s2
    stufen_ok = verstoesse is not None and s1 + s2 == verstoesse
    return {
        "ort": ort,
        "tempo": tempo,
        "beginn": beginn,
        "dauer_min": int((ende - beginn).total_seconds() // 60),
        "messungen": int(fz.group(1).replace(".", "")) if fz else None,
        "ueberschreitungen": verstoesse,
        "stufe1": s1 if stufen_ok else None,
        "stufe2": s2 if stufen_ok else None,
    }


def messstelle(text: str) -> dict:
    """ "Mainberg, St2447, Mainleite / Bereich Hs.-Nr. 28" -> Gemeindeteil, Straße, Nummer,
    Kreuzung."""
    teile = re.split(r",|\s/\s?|/(?=\s?(?:Bereich|Einm|Höhe|S[tT]\s?\d|SW\s?\d|B\s?\d))", text)
    teile = [_REF_VORN.sub("", t.strip()) for t in teile]
    teile = [t for t in teile if t]
    teil = teile.pop(0) if teile and teile[0] in GEMEINDETEILE else None
    teile = [t for t in teile if not _REF.match(t)]
    a = adresse(", ".join(re.sub(r"^Bereich\s+", "", t) for t in teile))
    if a.strasse and re.match(r"(?i)^(?:Einm|Bereich|Höhe|Hs)", a.strasse):
        a = type(a)(None)  # nur Straßennummer und Bereich („St2447, Bereich Einm. Jahnstraße“)
    return {
        "bezirk_roh": teil,
        "strasse": a.strasse,
        "hausnummer": a.hausnummer,
        "gegenueber": a.gegenueber,
        "lage_art": "kreuzung" if a.quer else "keine",
        "quer1": a.quer,
    }


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, dict]:
    bericht = {"dateien": [], "hinweise": []}
    zeilen, gesehen = [], set()
    for f in sorted(dateien):
        try:
            t = dokumente.text(f)
        except Exception as e:  # kaputte Datei: melden, weiter
            bericht["hinweise"].append(f"{f.name}: nicht lesbar ({e})")
            continue
        n = doppelt = 0
        for b in bloecke(t):
            liste = messungen(b)
            if not liste:
                bericht["hinweise"].append(f"{f.name}: Absatz nicht gelesen: {b[:80]!r}")
            for m in liste:
                if (m["beginn"], m["ort"]) in gesehen:  # derselbe Bericht zweimal hochgeladen
                    doppelt += 1
                    continue
                gesehen.add((m["beginn"], m["ort"]))
                if m["stufe1"] is None and m["ueberschreitungen"]:
                    bericht["hinweise"].append(
                        f"{f.name}: Klassen passen nicht zu {m['ueberschreitungen']} Verstößen "
                        f"({m['ort'][:40]}, {m['beginn']:%d.%m.%Y}) – ohne Stufen"
                    )
                zeilen.append(_zeile(m, f.name.split("__")[0]))
                n += 1
        bericht["dateien"].append({"datei": f.name, "messungen": n, "doppelt": doppelt})
    df = in_schema(pd.DataFrame(zeilen))
    bericht["kontrollen"] = int(len(df))
    return df, bericht


def _zeile(m: dict, quelle: str) -> dict:
    kurz = hashlib.sha1(m["ort"].encode("utf-8")).hexdigest()[:4]
    alle = (
        m["messungen"] is not None
        and m["ueberschreitungen"] is not None
        and m["messungen"] >= m["ueberschreitungen"]
    )
    return {
        "id": f"S{m['beginn']:%Y-%m-%d-%H%M}-{kurz}",
        "stadt": "schonungen",
        "quelle": quelle,
        "datum": f"{m['beginn']:%Y-%m-%d}",
        "beginn": f"{m['beginn']:%H:%M}",
        "dauer_min": m["dauer_min"],
        "strasse_roh": m["ort"],
        **messstelle(m["ort"]),
        "tempo": m["tempo"],
        "messungen": m["messungen"],
        "ueberschreitungen": m["ueberschreitungen"],
        "stufe1": m["stufe1"],
        "stufe2": m["stufe2"],
        "stufe_kmh": STUFE_KMH if m["stufe1"] is not None else None,
        "alle_gezaehlt": alle,
    }
