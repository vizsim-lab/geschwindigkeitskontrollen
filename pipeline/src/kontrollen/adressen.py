# SPDX-License-Identifier: AGPL-3.0-or-later
"""Adressen aus Freitext lesen: „Amsterdamer Str. 80-86“, „Kieskaulerweg ggü. Haus Nr.65“,
„Konrad-Adenauer-Damm Höhe Lichtmast Nr. 86“, „Butzweiler Str./Rochusstr.“.

Gebaut an den Standorttabellen von Köln, genutzt auch für Bonn und die kleinen Gemeinden. Regeln:

- Die Straße endet an einem Komma oder Doppelpunkt, an einem Zusatz („Höhe“, „ggü.“, „vor“,
  „Haus Nr.“, „Laterne“ …, auch direkt nach einem Punkt: „Friedr.-Schmidt-Str.ggü.Lat.56“), an
  einer Zahl oder an einem großgeschriebenen Wort nach „Str.“/„Straße“ („Frankfurter Str.
  S-Bahnbrücke“).
- Hausnummer: gleich nach den Zusätzen („ggü. 161“, „Höhe 179“, „80-86“ -> 80), sonst die erste
  nach „Haus“, „Hs.“, „Hausnr.“ oder „Nr.“.
- **Laternen, Lichtmasten, Kilometer und Meter sind keine Hausnummern** („Lat.Nr.106“, „L.21“,
  „Lichtmast Nr. 86“, „L 489 0,29“, „20mtr.“) – dann gilt nur die Straße.
- „A/B“, „vor B“, „Höhe B“, „unter B“, „Kreuzung B“ -> Kreuzung mit B (nur ohne Hausnummer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kontrollen import namen


@dataclass(frozen=True)
class Adresse:
    """„Tatstraße mit Hausnummer“, gelesen."""

    strasse: str | None
    hausnummer: str | None = None
    gegenueber: bool = False
    quer: str | None = None  # Kreuzung: "Butzweiler Str./Rochusstr.", "Kreuzung L92"


_GG = r"(?:gegen(?:ü|ue)ber|gg(?:ü|ue)(?:ber|b)?|geg|gg)"  # ggü., ggüb., ggüber, geg., gg.
_FREI = r"(?![a-zäöüß])"  # Zusatz endet (kein Wortteil: „vorm“, „Mastweg“, „nachts“)
_LAT = r"(?:Laterne|Lat\.?(?![a-zäöüß])|Lichtmast|Strommast|Mast|L\.?\s?(?=\d))"  # „L12“, „L.21“
# wo der Straßenname endet: Komma oder Doppelpunkt, ein Zusatz (mit Leerzeichen davor oder direkt
# nach einem Punkt: „Friedr.-Schmidt-Str.ggü.Lat.56“), eine Laterne (auch „L489“: Landesstraße),
# eine Zahl, ein großgeschriebenes Wort nach „Str.“/„Straße“ („Frankfurter Str. S-Bahnbrücke“)
_ENDE = re.compile(
    r"\s*[,:]"
    r"|(?:\s+|(?<=\.))(?:(?:in\s+)?[Hh](?:ö|oe)he|i\.\s*H\.|" + _GG + r"\.?|vor|v\.|hinter|"
    r"nach|unter|neben|neb\.|bis|zwischen|zw\.|Haus(?:nr|Nr|nummer|r)?|Hs\.?|HS|Nr|NR|Kreuzung|Ecke|"
    r"Einm(?:ü|ue)ndung|Einf\.|Ausf\.|Einfahrt|Ausfahrt|Km|km)" + _FREI + r"|"
    r"(?:\s+|(?<=\.)|(?<=[a-zäöüß]))" + _LAT + r"|"
    r"(?<=[a-zäöüß])(?=Höhe\b)"  # „AgrippinauferHöhe“
    r"|(?<=[a-zäöüß.])\s*(?=\d)"
    r"|(?<=[Ss]tr\.)\s*(?=[A-ZÄÖÜ])|(?<=traße)\s+(?=[A-ZÄÖÜ])"
)
# Laternen-, Mast-, Kilometer- und Meterangaben sind keine Hausnummern
_LATERNE = re.compile(
    r"(?:" + _LAT + r"|[Kk]m)\s*(?:-?\s*Nr\.?)?\s*\d+(?:[.,]\d+)?"
    r"\s*[a-zA-Z]?(?:\s*[-/]\s*\d+(?:[.,]\d+)?[a-zA-Z]?)?"
    r"|\d+\s*(?:m|mtr|Meter|meter)\b\.?"  # „20mtr.vor Lat.238“
)
_LATERNE_VORN = re.compile(r"^(?:Laterne|Lat\.?|Mast)\s*(?:-?\s*Nr\.?)?\s*\d+\s*-\s*(?=\D)")
# Zusätze vor der Nummer: „ggü. 161“, „gegenüber 11“, „Höhe 179“, „vor Haus Nr. 149“
_ZUSATZ = re.compile(
    r"^(?:(?:in\s+)?[Hh](?:ö|oe)he|i\.\s*H\.|"
    + _GG
    + r"|vor|v\.|hinter|nach|bis|ab)\.?"
    + _FREI
    + r"\s*"
)
_NUMMER = r"(\d{1,4})(?!\d|[.,]\d)\s*([a-zA-Z](?![a-zA-Z.]))?"  # nicht „0,24“ (Kilometer)
_HAUS = re.compile(r"\b(?:Haus|Hs)\b\.?\s*-?\s*(?:(?:Nr|Nummer)\b\.?)?\s*" + _NUMMER, re.I)
_HAUSNR = re.compile(r"\bHaus(?:nr|nummer|r)\b\.?\s*" + _NUMMER, re.I)
_NR = re.compile(r"\bNr\b\.?\s*" + _NUMMER, re.I)
_VORN = re.compile(r"^" + _NUMMER)
_GGUE = re.compile(r"(?<![a-zäöüß])" + _GG + _FREI, re.I)
_QUER = re.compile(
    r"(?:Kreuzung|Ecke|Einm(?:ü|ue)ndung|vor|v\.|hinter|unter|[Hh](?:ö|oe)he|i\.\s*H\.)\s*"
    r"(?P<q>[A-ZÄÖÜ][^,]*)$"
)
_KEINE_QUER = re.compile(r"^(?:Haus|Hs|HS|Nr|NR|Lat|Laterne|Mast|Kita|Schule|L\d)", re.I)
_SCHRAEG = re.compile(r"^(?P<a>[^/\d]+?)\s*/\s*(?P<b>[A-ZÄÖÜ][^/\d]+)$")


def adresse(text: str | None) -> Adresse:
    """ "Amsterdamer Str. 80-86" -> Straße "Amsterdamer Str.", Nr. 80;
    "Kieskaulerweg ggü. Haus Nr.65" -> Nr. 65, gegenüber; "Melatengürtel, Laterne 85-77" -> nur
    Straße; "Butzweiler Str./Rochusstr." und "Militärring v.Bachemer Landstr" -> Kreuzung."""
    s = " ".join(str(text or "").split())
    s = _LATERNE_VORN.sub("", s)  # „Lat.139 - Neusser Landstr.379“
    if not s:
        return Adresse(None)
    m = _SCHRAEG.match(s)
    if m:
        return Adresse(m.group("a").strip(" .,"), quer=m.group("b").strip(" .,"))
    e = _ENDE.search(s)
    strasse, rest = (s[: e.start()], s[e.start() :]) if e else (s, "")
    strasse = strasse.strip(" ,;:-")
    rest = rest.strip(" ,;:")
    ohne_laterne = _LATERNE.sub(" ", rest).strip(" ,;-")
    vorn = ohne_laterne
    while z := _ZUSATZ.match(vorn):
        vorn = vorn[z.end() :]
    # die Nummer gleich nach den Zusätzen, sonst die erste nach „Haus“, „Hs.“ oder „Nr.“
    n = _VORN.search(vorn) or min(
        (x for x in (p.search(ohne_laterne) for p in (_HAUSNR, _HAUS, _NR)) if x),
        key=lambda x: x.start(),
        default=None,
    )
    nr = namen.nummer(n.group(1) + (n.group(2) or "")).hausnummer if n else None
    q = _QUER.search(rest) if nr is None else None
    quer = q.group("q").strip(" .,") if q and not _KEINE_QUER.match(q.group("q")) else None
    return Adresse(strasse or None, hausnummer=nr, gegenueber=bool(_GGUE.search(rest)), quer=quer)
