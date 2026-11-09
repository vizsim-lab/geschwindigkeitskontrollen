# SPDX-License-Identifier: AGPL-3.0-or-later
"""Straßennamen, Hausnummern und Lageangaben lesen und vergleichbar machen.

Die Vergleichsform (`schluessel`) stammt aus vizsim/berlin-traffic-counts_schulwege
(`bezeichnung.py`): klein, Umlaute ausgeschrieben, nur Buchstaben und Ziffern –
"Köpenicker Straße", "Koepenicker Strasse" und "Köpenicker Str." werden gleich.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_LEER = re.compile(r"\s+")

_ABK = [
    (re.compile(r"(?<=\w)str\.?(?=\s|$|[,;)/])", re.IGNORECASE), "straße"),  # "Friedrichstr."
    (re.compile(r"\bStr\.?(?=\s|$|[,;)/])"), "Straße"),  # "Potsdamer Str.", "…-Str"
    (re.compile(r"\bCh\.?(?=\s|$)"), "Chaussee"),  # "Oranienburger Ch."
    (re.compile(r"\bPl\.?(?=\s|$)"), "Platz"),
    (re.compile(r"\bd\.\s*(?=[A-ZÄÖÜ])"), "der "),  # "Allee d.Kosmonauten"
    (re.compile(r"(?<=\w)sttraße\b", re.IGNORECASE), "straße"),  # Tippfehler "Schillersttraße"
]


def bereinige(name: str) -> str:
    """Leerraum, Satzzeichen am Rand und Abkürzungen ("Str.", "Ch.", "Pl.") glätten."""
    s = _LEER.sub(" ", str(name).replace("\xa0", " ")).strip(" ,:;-!")
    for muster, ersatz in _ABK:
        s = muster.sub(ersatz, s)
    return s.strip(" .")


def schluessel(name: str) -> str:
    """Vergleichsform: klein, Umlaute ausgeschrieben, nur Buchstaben/Ziffern."""
    s = bereinige(name).lower()
    s = s.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if c.isalnum())
    # Titel und Heilige schreiben Quellen mal aus, mal nicht ("Prof Pirlett Straße" ~
    # "Professor-Pirlet-Straße"): in beiden Richtungen auf die Kurzform
    for lang, kurz in (("professor", "prof"), ("doktor", "dr"), ("sankt", "st")):
        s = s.replace(lang, kurz)
    return s


def schluessel_varianten(name: str) -> list[str]:
    """Vergleichsformen inkl. Beugung ("Indischen Straße" -> auch "Indische Straße")."""
    varianten = [schluessel(name)]
    gebeugt = re.sub(
        r"(\w+)en\s+(Straße|Allee|Weg|Platz|Damm|Ufer|Ring|Chaussee|Brücke|Steig|Pfad)\b",
        r"\1e \2",
        bereinige(name),
    )
    for v in (schluessel(gebeugt),):
        if v and v not in varianten:
            varianten.append(v)
    return [v for v in varianten if v]


# --- Hausnummern ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Nummer:
    """Was im Feld „Nr.“ steht. `hausnummer` ist für die Suche normalisiert ("12a")."""

    roh: str
    hausnummer: str | None = None
    gegenueber: bool = False  # "g232": gegenüber Nr. 232 (Lesart, nicht amtlich erklärt)
    mast: str | None = None  # "L2980": vermutlich Lichtmast-Nummer, nicht verortbar
    sonst: str | None = None  # alles andere ("k5,5", "K21" …)


_HNR = re.compile(r"^(\d{1,4})\s*([a-zA-Z])?(?:\s*[-/]\s*\d{1,4}\s*[a-zA-Z]?)?$")


def nummer(roh: str | None) -> Nummer:
    s = _LEER.sub(" ", str(roh or "")).strip()
    if not s:
        return Nummer(roh="")
    gegenueber = False
    rest = s
    if re.match(r"^g(?=[\dL])", rest, re.IGNORECASE):
        gegenueber, rest = True, rest[1:].strip()
    if re.match(r"^L\s*\d+", rest):
        return Nummer(roh=s, gegenueber=gegenueber, mast=rest.replace(" ", ""))
    m = _HNR.match(rest)
    if m:
        return Nummer(
            roh=s, hausnummer=m.group(1) + (m.group(2) or "").lower(), gegenueber=gegenueber
        )
    return Nummer(roh=s, gegenueber=gegenueber, sonst=rest)


def hausnummer_schluessel(hnr: str) -> list[str]:
    """Suchformen einer OSM-Hausnummer: "12 a" -> ["12a"], "12-14" -> ["12-14", "12", "14"],
    "12;14" -> ["12", "14"]. Die Zahl ohne Buchstaben steht zusätzlich am Ende ("12a" -> "12")."""
    out: list[str] = []
    for teil in re.split(r"[;,]", str(hnr)):
        t = teil.strip().lower().replace(" ", "")
        if not t:
            continue
        out.append(t)
        for z in re.findall(r"\d+[a-z]?", t):
            if z not in out:
                out.append(z)
    for t in list(out):
        z = re.match(r"^(\d+)[a-z]$", t)
        if z and z.group(1) not in out:
            out.append(z.group(1))
    return out


# --- Lageangaben ---------------------------------------------------------------------------

_KOMPASS = {
    "norden": "N",
    "nordosten": "NO",
    "osten": "O",
    "suedosten": "SO",
    "sueden": "S",
    "suedwesten": "SW",
    "westen": "W",
    "nordwesten": "NW",
}
GRAD = {"N": 0, "NO": 45, "O": 90, "SO": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}


@dataclass(frozen=True)
class Richtung:
    roh: str
    kompass: str | None = None  # "NW"
    ziel: str | None = None  # "Michael-Brüc" (oft abgeschnitten)


def richtung(roh: str | None) -> Richtung:
    """ "Nordwesten/Michael-Brüc" -> (NW, "Michael-Brüc"); ohne Himmelsrichtung nur das Ziel."""
    s = _LEER.sub(" ", str(roh or "")).strip()
    if not s:
        return Richtung(roh="")
    kopf, _, ziel = s.partition("/")
    k = _KOMPASS.get(schluessel(kopf))
    if k is None:
        return Richtung(roh=s, ziel=s or None)
    return Richtung(roh=s, kompass=k, ziel=ziel.strip() or None)


@dataclass(frozen=True)
class Lage:
    """Feld „zwischen“: zwei Querstraßen, eine Kreuzung ("/C") oder ein Ort ("AS Kaiserdamm")."""

    roh: str
    art: str  # "zwischen" | "kreuzung" | "ort" | "keine"
    namen: tuple[str, ...] = ()


_UND = re.compile(r"\s+u(?:nd|\.)?\s+|\s+u\.(?=\S)")


def lage(roh: str | None) -> Lage:
    s = _LEER.sub(" ", str(roh or "")).strip()
    if not s:
        return Lage(roh="", art="keine")
    if s.startswith("/"):
        return Lage(roh=s, art="kreuzung", namen=(s[1:].strip(),))
    teile = [t.strip() for t in _UND.split(s) if t.strip()]
    if len(teile) == 2:
        return Lage(roh=s, art="zwischen", namen=(teile[0], teile[1]))
    return Lage(roh=s, art="ort", namen=(s,))


# Autobahn-Orte: "AS Kaiserdamm" (Anschlussstelle), "AD Funkturm" (Dreieck), "AK Zehlendorf"
# (Kreuz), "Ausf./Einf. Tunnel Schlangenbader Str."
_AB_VORSATZ = [
    (re.compile(r"^(?:AS|Anschlussstelle)\s+", re.I), ""),
    (re.compile(r"^(?:AD|Autobahndreieck)\s+", re.I), "Dreieck "),
    (re.compile(r"^(?:AK|Autobahnkreuz)\s+", re.I), "Kreuz "),
    (re.compile(r"^(?:Ausf|Einf|Ausfahrt|Einfahrt)\.?\s+", re.I), ""),
]


def autobahn_ort(text: str) -> tuple[str, str]:
    """-> (Art, Name): ("AS", "Kaiserdamm"), ("AD", "Dreieck Funkturm"), ("", "ICC")."""
    s = bereinige(text)
    art = ""
    for muster, ersatz in _AB_VORSATZ:
        m = muster.match(s)
        if m:
            art = art or m.group(0).strip(". ").upper()[:2]
            s = ersatz + s[m.end() :]
    return art, s.strip()


_AUTOBAHN = re.compile(r"^(?:BAB\s*)?A\s*(\d{1,3})\b\s*(.*)$", re.I)


def autobahn(strasse: str) -> tuple[str, str] | None:
    """ "BAB A 100" -> ("A 100", ""); "BAB A 100 AS Messedamm" -> ("A 100", "AS Messedamm")."""
    s = _LEER.sub(" ", str(strasse or "")).strip()
    if not re.match(r"^(?:BAB\b|A\s*\d)", s, re.I):
        return None
    m = _AUTOBAHN.match(s.removeprefix("BAB").strip())
    if not m:
        return None
    return f"A {int(m.group(1))}", m.group(2).strip()
