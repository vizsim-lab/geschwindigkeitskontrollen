# SPDX-License-Identifier: AGPL-3.0-or-later
"""Butzbach (Wetteraukreis): Geschwindigkeitsmessungen im gemeinsamen Ordnungsbehördenbezirk
Butzbach/Münzenberg/Rockenberg/Wölfersheim.

Die Stadt stellt je Monat einen Beitrag mit einer Tabelle als PDF auf ihre Seite
(„sb_oa-messung-2604.pdf“), ältere Tabellen stehen nur noch in der Mediathek: Tag, von, bis,
Gesamtstunden, Gesamt Fahrzeuge, Verwarnungen, Bußgelder, Verstöße in %, Messstelle. Eine Zeile
ist eine **Kontrolle** mit allen gemessenen Fahrzeugen (`alle_gezaehlt`), Beginn und Dauer;
Überschreitungen = Verwarnungen + Bußgelder. Das Tempolimit nennt die Tabelle nicht.

- Leere Vorlagezeilen (mitunter mit vorgetragenem Datum) und die Summe darunter fallen weg;
  Monate ohne Messung sind leere Vorlagen.
- Bußgelder „-“ oder leer (bis 2023 häufig): 0, wenn der Anteil in „Verstöße in %“ dann zu den
  Verwarnungen passt (2019-05-09: 8 von 1.051 = 0,76 %); sonst bleiben die Überschreitungen leer.
- Datum „09.04..2026“, „03.02.20206“, „05.02.2014“ zwischen Zeilen vom 05.02.2015 (Tippfehler im
  Jahr: dann das Jahr der übrigen Zeilen dieses Monats), Gesamtstunden „2,42“ = 2:42. Die Dauer
  kommt aus Beginn und Ende (auch über Mitternacht).
- „CD war nicht auswertbar“ statt einer Querangabe: die Kontrolle zählt, ihre Überschreitungen
  bleiben leer (die Tabelle nennt 0).
- Dieselbe Messung in zwei Dateien (ein Monat zweimal hochgeladen) zählt einmal.

Messstelle: „Butzbach/Griedel, L3134 ggü Rockenberger Str.“, früher auch „Griedel / Alte
Hauptstr.“, „Nieder - Weisel / Zum Bahnhof“, „Trais-Münzenberg, Wetterstr.“ – Kommune und
Ortsteil (`ORTE`), dann Straße oder Straßennummer mit Hausnummer, Querstraße („Ecke …“, „/
Seedammweg“, „ggü Weidbrunnenstraße 2A“) oder einem Ort („/ Kiga Löwenherz“, „/ BHS“). Steht
vor der Straße ihre Nummer („L3053 / Griedeler Str. in Höhe Hs. Nr. 49“), zählt die Straße.
`bezirk_roh` ist das engste genannte Gebiet mit seinem Namen in OSM: der Ortsteil, sonst die
Kommune – dann ihr gleichnamiger Kernort („Butzbach, Weiseler Str.“ liegt in der Kernstadt).

Id: `U<Datum>-<Beginn>-<Kurzzeichen der Messstelle>`, z. B. `U2026-04-01-0645-3f2a`.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from kontrollen import dokumente
from kontrollen.adressen import adresse
from kontrollen.schema import in_schema
from kontrollen.weiterstadt import strassennummer

# Kommunen (zuerst) und Ortsteile des Bezirks: Name -> Muster für die Schreibweisen der
# Tabellen („Nieder - Weisel“, „Kirch Göns“, „Butzabch“, „Erbersgöns“, „Münzenberg-Trais“).
# Die Namen sind die der Gebiete in OSM (Stadtteile auf admin_level 9, die Ortsteile von
# Rockenberg und Wölfersheim auf 10), bis auf die in OSM_NAME.
KOMMUNEN = ("Butzbach", "Münzenberg", "Rockenberg", "Wölfersheim")
ORTE = {
    "Butzbach": r"Butz(?:bach|abch|bacvh)d?",
    "Münzenberg": r"M(?:ü|ue)nzenberg",
    "Rockenberg": r"Rockenber[grb]",
    "Wölfersheim": r"W(?:ö|oe)lfersheim",
    "Bodenrod": r"Bodenrod",
    "Ebersgöns": r"Er?bersg(?:ö|oe)ns",
    "Fauerbach vor der Höhe": r"Fauerbach(?:\s*v\.?\s*d\.?\s*H\.?|\s+vor\s+der\s+H(?:ö|oe)he)?",
    "Griedel": r"Griedel",
    "Hausen-Oes": r"Hausen(?:\s*-?\s*Oes)?|Oes",
    "Hoch-Weisel": r"Hoch\s*-?\s*Weisel",
    "Kirch-Göns": r"Kirch\s*-?\s*G(?:ö|oe)ns",
    "Maibach": r"Maibach",
    "Münster": r"M(?:ü|ue)nster",
    "Nieder-Weisel": r"Nh?ieder\s*-?\s*Weisel",
    "Ostheim": r"Ostheim",
    "Pohl-Göns": r"Pohl\s*-?\s*G(?:ö|oe)[nm]s",
    "Wiesental": r"Wiesental",
    "Gambach": r"Gambach",
    "Ober-Hörgern": r"Ober\s*-?\s*H(?:ö|oe)rgern",
    "Trais-Münzenberg": (
        r"Trais(?:\s*-?\s*(?:M(?:ü|ue)nzenberg|Mzb\.?))?|M(?:ü|ue)nzenberg\s*-\s*Trais"
    ),
    "Oppershofen": r"Opp?er(?:s)?hof(?:f)?en",
    "Berstadt": r"Berstadt",
    "Melbach": r"Meh?lbach",
    "Södel": r"S(?:ö|oe)del",
    "Wohnbach": r"Wohnbach",
    "Geisenheim": r"Geisenheim",
    "Waldsiedlung": r"Waldsiedlung",
}
# Name des Gebiets in OSM, wo er abweicht: Trais-Münzenberg heißt dort „Treis“. „Geisenheim“
# und die Waldsiedlung haben kein eigenes Gebiet: die Messstelle in Geisenheim („Wölfersheim/
# Geisenheim, B455 / Seestr.“) liegt an der Seestraße im Ortsteil Wölfersheim, die Stettiner
# Straße der Waldsiedlung in der Kernstadt Butzbach.
OSM_NAME = {"Trais-Münzenberg": "Treis", "Geisenheim": "Wölfersheim", "Waldsiedlung": "Butzbach"}
# längere Muster zuerst („Münzenberg-Trais“ vor „Münzenberg“); kein Wortteil („Butzbacher Str.“)
_ORT_VORN = re.compile(
    r"^\s*[,/.\-–]?\s*(?:"
    + "|".join(
        f"(?P<o{i}>{m})" for i, m in sorted(enumerate(ORTE.values()), key=lambda x: -len(x[1]))
    )
    + r")(?![a-zäöüß]|-[A-Za-zÄÖÜäöüß]+-)\s*(?:[,/.]|[-–](?=\s)|\s(?=[A-ZÄÖÜ]))?\s*"
)
_ORT_NAMEN = list(ORTE)

# „01.04.2026“, auch „09.04..2026“, „1.4.26“ und „03.02.20206“ (so steht es in den Tabellen)
_DATUM = re.compile(r"^\s*(\d{1,2})\s*\.+\s*(\d{1,2})\s*\.+\s*(\d{2,5})\s*$")
_UHR = re.compile(r"^\s*(\d{1,2})[:.,](\d{2})\s*(?:Uhr)?\s*$")
# Spalten nach ihrem Kopf (die Reihenfolge könnte wechseln; 2024 auch „Verwarnunge“ „n Bußgelder“)
_SPALTEN = {
    "tag": re.compile(r"(?i)^(?:tag|datum)"),
    "von": re.compile(r"(?i)^von"),
    "bis": re.compile(r"(?i)bis$|^…?\s*bis"),
    "dauer": re.compile(r"(?i)stun"),
    "fahrzeuge": re.compile(r"(?i)fahrzeuge"),
    "verwarnungen": re.compile(r"(?i)verwarn"),
    "bussgelder": re.compile(r"(?i)bu(?:ß|ss)geld"),
    "anteil": re.compile(r"%"),
    "messstelle": re.compile(r"(?i)messstelle"),
}
_LEER = {"", "-", "–", "—"}

# Straßennummer: „B3“, „L 3053“, „K363“; allein, vorn oder hinten in der Angabe
_NUMMER = r"[BLK]\s?\d{1,4}"
_NUR_NUMMER = re.compile(rf"^{_NUMMER}$")
_NUMMER_VORN = re.compile(rf"^(?P<nr>{_NUMMER})(?:\s*,\s*|\s+)(?P<rest>\S.*)$")
_NUMMER_HINTEN_ALLEIN = re.compile(rf"^(?P<rest>[^,]+?)\s+(?P<nr>{_NUMMER})$")
# sieht aus wie eine Straße (sonst ein Ort: „BHS“, „Kinderheim“, „Windhofkurve“, „Forsthaus“)
_STRASSE = re.compile(
    r"(?i)(?:stra(?:ß|ss)e|str\b\.?|weg\b|gasse\b|platz\b|allee\b|ring\b|pfad\b|steg\b|damm\b)"
    r"|^(?:Am|An der|An den|Auf der|Auf dem|Im|In der|In den|Zum|Zur|Unter[e]?[rn]?)\s"
)
# nur eine Hausnummer hinter dem Schrägstrich („/ Höhe 82-68“, „/ ggü Hs.Nr. 47“)
_NUR_HAUSNUMMER = re.compile(
    r"(?i)^(?:(?:in\s+)?h(?:ö|oe)he|gg(?:ü|ue)\.?)?\s*(?:(?:hs|haus)\.?\s*nr\.?|nr\.?)?\s*\d"
)
# „ggü Rockenberger Str.“ (gegenüber einer Straße) ist eine Querangabe, „ggü Hs. Nr. 11“ nicht
_GGUE_STRASSE = re.compile(
    r"(?i:\b(?:gegen(?:ü|ue)ber|gg(?:ü|ue)(?:b(?:er)?)?|geg(?:ü|ue)?))\.?\s+"
    r"(?:(?:in\s+)?H(?:ö|oe)he\s+)?(?:Grundst(?:ü|ue)ck\s+)?"
    r"(?=[A-ZÄÖÜ])(?!H(?:s|S|aus)\b|Nr\b|HS\b)"
)
_NEBEN = re.compile(r"(?i),?\s*\bneben\s+(?=[A-ZÄÖÜ])")
# „Nordecke Grundstück Büchnerstr. 6“, „NordeckeGrundstück …“, „Nordecke Anwesen …“ -> „Ecke …“
_ECKE_GRUNDSTUECK = re.compile(
    r"(?:(?:Nord|Süd|Ost|West)e|E)cke(?![a-zäöüß]),?\s*"
    r"(?:(?:Grundst(?:ü|ue)ck|Grundst\.|Anwesen)\s*)?"
)
# Bemerkung statt Ort: „Rockenberg/Schillerstr./CD war nicht auswertbar“ (70 Fahrzeuge,
# „0“ Verstöße)
_NICHT_AUSWERTBAR = re.compile(r"(?i)[\s/,]*(?:\bCD\s+)?(?:war\s+)?nicht\s+auswertbar\.?")
_TIPPFEHLER = [
    (re.compile(r"(?<=[a-zäöü])sr\."), "str."),  # „Alte Hauptsr.“
    (re.compile(r"(?<=-)Sr\."), "Str."),  # „Alexander-Weitzel-Sr.“
    (re.compile(r"\s+an der\s+"), " / "),  # „Münzenberger Straße an der BHS“
    (re.compile(r"(?<=[a-zäöü])sraße\b"), "straße"),  # „Hauptsraße“
    (re.compile(r"\bDtr\."), "Str."),  # „Falkensteiner Dtr.“
    (re.compile(r"\bH(?:ö|oe)hne\b"), "Höhe"),  # „Höhne Haus Nr. 27“
    (re.compile(r"\b(?:Hsn|Hnr)\b\.?\s*"), "Hs. Nr. "),  # „ggü Hsn. 11“, „Ggü Hnr 12“
    (re.compile(r"\bHS\s+Nr\b"), "Hs. Nr"),
    (re.compile(r"\bGgü\b"), "ggü"),
    (re.compile(r"\bIn\s+(?=H(?:ö|oe)he\b)"), "in "),  # „Seestr. In Höhe 60-62“
    # „Höe Am Dreschplatz“, „in Hhhe Singbergschule“, „B3Höe Grundstück“
    (re.compile(r"(?<![A-Za-zÄÖÜäöüß])H(?:öe|hhe)\b"), "Höhe"),
    (re.compile(r"(?<=\d)-?(?=H(?:ö|oe)he\b)"), " "),  # „B3-Höhe Grundstück …“, „B3Höhe“
    (re.compile(r"(?<=str)(\.?)l\b"), r"\1"),  # „Taunusstrl 45“, „An der Landstr.l 6a“
    (re.compile(r"\bgeg(?:ü|ue)\b\.?:?"), "ggü."),  # „Steinbergstr.gegü: Haus-Nr. 23“
    (re.compile(r"\s+bei\s+(?=[A-ZÄÖÜ])"), " / "),  # „Butzbacher Str. bei EDEKA“
]
# Reste, die keine Querangabe sind („/ Nordecke“, „Höhe Grundstück / Wiesengrund 19“)
_GRUNDSTUECK = re.compile(r"(?i)^(?:grundst(?:ü|ue)ck|grundst\.?|anwesen)(?:\s+|$)")
_KEINE_QUER = re.compile(r"(?i)^(?:ecke|einm(?:ü|ue)ndung|kreuzung)?$")
_QUER_VORSATZ = re.compile(
    r"(?i)^(?:ecke|einm(?:ü|ue)ndung|kreuzung|gg(?:ü|ue)\.?|neben|(?:in\s+)?h(?:ö|oe)he"
    r"|(?:vor|hinter)(?!\s+(?:der|dem|den|die)\b))\s+(?:grundst(?:ü|ue)ck\s+)?"
)
_IN_HOEHE = re.compile(r"(?i)\b(?:in\s+)?h(?:ö|oe)he\s+(?P<x>[A-ZÄÖÜ].*)$")
_NUMMER_HINTEN = re.compile(
    r"\s*(?:[Ii]n\s+H(?:ö|oe)he\s+)?\d{1,4}\s*[a-zA-Z]?(?:\s*[-/]\s*\d{1,4}\s*[a-zA-Z]?)?$"
)


def _zahl(s: str | None) -> int | None:
    t = re.sub(r"[.\s]", "", str(s or ""))
    return int(t) if t.isdigit() else None


def _anteil(s: str | None) -> float | None:
    """„4,4%“, „0,76“ -> Prozent; „#DIV/0!“ -> None."""
    t = str(s or "").replace("%", "").replace(",", ".").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _jahr(j: int) -> int:
    """„26“ -> 2026; „2014“ bleibt; „20206“ bleibt (und fällt später auf)."""
    return j + 2000 if j < 100 else j


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
    Bußgelder, Anteil, Messstelle. Zeilen ohne Datum (Kopf, Vorlage, Summe) fallen weg."""
    roh, sp = [], None
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

        def zelle(name: str, z=z, sp=sp) -> str | None:
            i = sp.get(name)
            return z[i] if i is not None and i < len(z) else None

        if _zahl(zelle("fahrzeuge")) is None and not dokumente.glaette(zelle("messstelle")):
            continue  # Vorlagezeile mit vorgetragenem Datum, ohne Messung
        roh.append(
            {
                "tmj": tuple(int(x) for x in m.groups()),
                "von": _uhrzeit(zelle("von")),
                "bis": _uhrzeit(zelle("bis")),
                "dauer": _uhrzeit(zelle("dauer")),
                "messungen": _zahl(zelle("fahrzeuge")),
                "verwarnungen": _zahl(zelle("verwarnungen")),
                "bussgelder": _zahl(zelle("bussgelder")),
                "w_leer": str(zelle("verwarnungen") or "").strip() in _LEER,
                "b_leer": str(zelle("bussgelder") or "").strip() in _LEER,
                "anteil": _anteil(zelle("anteil")),
                "ort": dokumente.glaette(zelle("messstelle")),
            }
        )
    # Jahr: „26“ -> 2026. Tippfehler im Jahr („20206“, „05.02.2014“ zwischen Zeilen vom
    # 05.02.2015) -> das Jahr der übrigen Zeilen dieses Monats
    jm = [(_jahr(j), mo) for _, mo, j in (r["tmj"] for r in roh)]
    monate = Counter(x for x in jm if 2000 <= x[0] < 2100)
    haupt = monate.most_common(1)[0][0] if monate else None  # (Jahr, Monat) der meisten Zeilen
    out = []
    for r in roh:
        tag, monat, jahr = r.pop("tmj")
        jahr = _jahr(jahr)
        if haupt and (not 2000 <= jahr < 2100 or (monat == haupt[1] and jahr != haupt[0])):
            jahr = haupt[0]
        if not 2000 <= jahr < 2100:
            continue
        try:
            r["datum"] = datetime(jahr, monat, tag)
        except ValueError:
            continue
        out.append(r)
    return out


def _ist_strasse(name: str | None) -> bool:
    return bool(name) and bool(_STRASSE.search(name))


def _quer(text: str | None) -> str | None:
    """ "Ecke Kleeberger Str. 6" -> "Kleeberger Str"; "Abschnitt 026 in Höhe August-Storch-Str"
    -> "August-Storch-Str"."""
    t = (text or "").strip(" ,.")
    if _NUR_NUMMER.match(t):
        return strassennummer(t)  # „/ B455“
    if m := _IN_HOEHE.search(t):
        t = m["x"]
    t = _GRUNDSTUECK.sub("", _QUER_VORSATZ.sub("", t))
    t = _NUMMER_HINTEN.sub("", t).strip(" .,")
    return None if _KEINE_QUER.match(t) else t


def orte(text: str) -> tuple[list[str], str]:
    """Kommune und Ortsteile am Anfang -> (Namen, Rest): "Butzbach/Griedel, L3134 …" ->
    (["Butzbach", "Griedel"], "L3134 …")."""
    gefunden, t = [], text
    while (m := _ORT_VORN.match(t)) and m.end() < len(t):
        name = _ORT_NAMEN[int(next(k for k, v in m.groupdict().items() if v)[1:])]
        gefunden.append(name)
        t = t[m.end() :]
    return gefunden, t


def bezirk(namen_: list[str]) -> str | None:
    """Das engste genannte Gebiet: ["Butzbach", "Griedel"] -> "Griedel"; ["Butzbach"] ->
    "Butzbach" (die Kernstadt); ["Münzenberg", "Trais-Münzenberg"] -> "Treis"."""
    teile = [n for n in namen_ if n not in KOMMUNEN] or namen_
    return ", ".join(dict.fromkeys(OSM_NAME.get(n, n) for n in teile)) or None


def messstelle(text: str) -> dict:
    """ "Butzbach/Griedel, L3134 ggü Rockenberger Str." -> Ortsteil und Kommune, Straße,
    Nummer, Kreuzung."""
    t = " ".join(re.sub(r"\([^)]*\)|[\"'„“”‚‘’]", " ", _NICHT_AUSWERTBAR.sub("", text)).split())
    namen_, t = orte(t)
    for muster, ersatz in _TIPPFEHLER:
        t = muster.sub(ersatz, t)
    t = _ECKE_GRUNDSTUECK.sub("Ecke ", t)
    t = _NEBEN.sub(" Höhe ", t)
    t = _GGUE_STRASSE.sub("Höhe ", t)
    teile = [x.strip() for x in re.split(r"\s*/\s*|\s+[-–]\s+", t) if x.strip()]
    kopf, weitere = (teile[0], teile[1:]) if teile else ("", [])
    kopf = re.sub(r"^Ecke\s+", "", kopf)  # „Nordecke Anwesen Büchnerstr. 6“: das Grundstück
    quer = None
    if _NUR_NUMMER.match(kopf) and weitere:
        # „L3053 / Griedeler Str. in Höhe Hs. Nr. 49“: die Straße mit Hausnummer gilt, sonst ist
        # das zweite Stück eine Querstraße oder ein Ort („B3 / Ecke August-Storch-Str“, „/ BHS“)
        a = adresse(weitere[0])
        if _ist_strasse(a.strasse) and a.hausnummer:
            kopf, weitere = weitere[0], weitere[1:]
        else:
            quer, weitere = _quer(weitere[0]), []
    elif (m := _NUMMER_VORN.match(kopf)) and not _QUER_VORSATZ.match(m["rest"]):
        if _ist_strasse(adresse(m["rest"]).strasse):
            kopf = m["rest"]  # „L3053 Griedeler Str.“, „L 3136 Falkensteiner Str. in Höhe Nr. 66“
        else:
            kopf, quer = m["nr"], _quer(m["rest"])  # „B3 Windhofkurve“, „L3136 BHS“
    elif (m := _NUMMER_HINTEN_ALLEIN.match(kopf)) and not _ist_strasse(m["rest"]):
        kopf, quer = m["nr"], _quer(m["rest"])  # „Windhofkurve B3“
    a = adresse(kopf)
    nr, gg = a.hausnummer, a.gegenueber
    if quer is None:
        quer = _quer(a.quer) if a.quer else None
    if weitere and not nr and not quer:
        if _NUR_HAUSNUMMER.match(weitere[0]):
            b = adresse(f"{kopf} {weitere[0]}")  # „Weiseler Str. / Höhe 82-68“
            nr, gg = b.hausnummer, b.gegenueber or gg
        else:
            quer = _quer(weitere[0])  # „Tepler Str. / Seedammweg“, „Hauptstraße / Kiga …“
    strasse = strassennummer(a.strasse) or a.strasse
    if quer:
        quer = strassennummer(quer) or quer
    return {
        "bezirk_roh": bezirk(namen_),
        "strasse": strasse,
        "hausnummer": nr,
        "gegenueber": gg,
        "lage_art": "kreuzung" if quer else "keine",
        "quer1": quer,
    }


def _ueberschreitungen(r: dict) -> int | None:
    """Verwarnungen + Bußgelder. Fehlt eine der beiden („-“, leer), zählt sie 0, wenn der Anteil
    in „Verstöße in %“ dann stimmt – sonst keine Angabe."""
    w, b, n, p = r["verwarnungen"], r["bussgelder"], r["messungen"], r["anteil"]
    if w is not None and b is not None:
        return w + b
    if not n or p is None:
        return None
    for wert, leer in ((w, r["b_leer"]), (b, r["w_leer"])):
        if wert is not None and leer and abs(100 * wert / n - p) <= 0.06:
            return wert
    return None


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, dict]:
    bericht: dict = {"dateien": [], "hinweise": [], "doppelt": 0, "ohne_ueberschreitungen": 0}
    out, gesehen = [], set()
    for f in sorted(dateien):
        try:
            z = zeilen(f)
        except Exception as e:  # kaputte Datei: melden, weiter
            bericht["hinweise"].append(f"{f.name}: nicht lesbar ({e})")
            continue
        if not z:
            bericht["hinweise"].append(f"{f.name}: keine Messungen (leere Vorlage)")
        n = 0
        for r in z:
            schluessel = (r["datum"], r["von"], r["ort"])
            if schluessel in gesehen:  # derselbe Monat zweimal hochgeladen
                bericht["doppelt"] += 1
                continue
            gesehen.add(schluessel)
            zeile = _zeile(r, f.name.split("__")[0])
            if zeile["ueberschreitungen"] is None:
                bericht["ohne_ueberschreitungen"] += 1
                bericht["hinweise"].append(
                    f"{f.name}: Verwarnungen/Bußgelder unklar ({r['ort'][:40]}, "
                    f"{r['datum']:%d.%m.%Y})"
                )
            out.append(zeile)
            n += 1
        bericht["dateien"].append({"datei": f.name, "kontrollen": n})
    df = in_schema(pd.DataFrame(out))
    bericht["kontrollen"] = int(len(df))
    return df, bericht


def _zeile(r: dict, quelle: str) -> dict:
    tag = r["datum"]
    beginn = tag.replace(hour=r["von"][0], minute=r["von"][1]) if r["von"] else None
    dauer = None
    if beginn is not None and r["bis"]:
        ende = tag.replace(hour=r["bis"][0], minute=r["bis"][1])
        if ende < beginn:  # über Mitternacht
            ende += timedelta(days=1)
        dauer = int((ende - beginn).total_seconds() // 60)
    elif r["dauer"]:
        dauer = r["dauer"][0] * 60 + r["dauer"][1]
    ueber = None if _NICHT_AUSWERTBAR.search(r["ort"]) else _ueberschreitungen(r)
    alle = r["messungen"] is not None and ueber is not None and r["messungen"] >= ueber
    kurz = hashlib.sha1(r["ort"].encode("utf-8")).hexdigest()[:4]
    zeit = f"{beginn:%H%M}" if beginn else "0000"
    return {
        "id": f"U{tag:%Y-%m-%d}-{zeit}-{kurz}",
        "stadt": "butzbach",
        "quelle": quelle,
        "datum": f"{tag:%Y-%m-%d}",
        "beginn": f"{beginn:%H:%M}" if beginn else None,
        "dauer_min": dauer,
        "strasse_roh": r["ort"],
        **messstelle(r["ort"]),
        "messungen": r["messungen"],
        "ueberschreitungen": ueber,
        "alle_gezaehlt": alle,
    }
