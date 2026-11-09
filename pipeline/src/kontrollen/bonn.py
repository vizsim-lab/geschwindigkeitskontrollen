# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bonn: Geschwindigkeitsverstöße der Bundesstadt (Open Data „Bußgelder fließender Verkehr“).

Je Jahr eine Datei („Geschwindigkeitsverstoesse<Jahr>.csv“, gefunden über GovData), ein
**Verstoß je Zeile**: TATTAG (`01.01.2016`), TATZEIT, TATORT (Freitext), TBNR (Tatbestands-
nummer), GELDBUSSE. 2016 ist als Mac-Roman gespeichert (`tabellen.kodierung` erkennt das).

- **Feste Anlagen** sind nicht gekennzeichnet. Ein Tatort, an dem in einem Jahr an mehr als
  `FEST_TAGE` Tagen Verstöße stehen, gilt als feste Anlage und bleibt in allen Jahren draußen
  (B9 Mainzer Straße, Straßentunnel Bad Godesberg, Reichsstraße, Konrad-Adenauer-Damm,
  Ludwig-Erhard-Allee). 2016–2024 sind das 57 Tatort-Jahre mit über 300 Tagen; die mobile
  Messung mit den meisten Tagen liegt bei 221 (An der Josefshöhe 2023, vermutlich ein Anhänger)
  – die Grenze liegt in der Lücke.
- Eine **Kontrolle** ist hier: alle Verstöße eines Tatorts an einem Tag. Gemessene Fahrzeuge,
  Tempolimit und die Höhe der Überschreitung nennt Bonn nicht (sie steckt nur in der
  Tatbestandsnummer) – `messungen`, `tempo` und die Stufen bleiben leer.
- **Tatort:** „Bonn, <Straße> Höhe Haus-Nr. 15  Fahrtrichtung <Ziel>“, auch „Bonn - Mehlem, …“,
  „… Höhe Lichtmast Nr. 86 …“ (keine Hausnummer), an der Autobahn „Bonn, A 555; km 018,000;
  RF Köln“ (nur Kilometer – nicht verortbar). Gelesen mit `adressen.adresse`.

Die Id einer Kontrolle: `N<Datum>-<Kurzzeichen des Tatorts>` (die ersten 8 Zeichen des
SHA-1 des Tatort-Texts), z. B. `N2023-05-02-1a2b3c4d`.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

from kontrollen import namen, tabellen
from kontrollen.adressen import adresse
from kontrollen.schema import in_schema

FEST_TAGE = 250  # Tage mit Verstößen in einem Jahr, ab denen ein Tatort eine feste Anlage ist


def _text(s: str) -> str:
    return " ".join(str(s or "").split())


def lies_datei(pfad: Path) -> pd.DataFrame:
    """Eine Jahresdatei -> Spalten tag (ISO), tatort (Leerraum geglättet)."""
    df = tabellen.lies(pfad)
    spalten = {c: c for c in df.columns}
    tag = next((c for c in spalten if c.startswith("tattag")), None)
    ort = next((c for c in spalten if c.startswith("tatort")), None)
    if tag is None or ort is None:
        raise ValueError(f"{pfad.name}: Spalten TATTAG/TATORT fehlen ({list(df.columns)})")
    d = pd.to_datetime(df[tag].str.strip(), format="%d.%m.%Y", errors="coerce")
    return pd.DataFrame({"tag": d.dt.strftime("%Y-%m-%d"), "tatort": df[ort].map(_text)})


def feste_anlagen(v: pd.DataFrame, grenze: int | None = None) -> set[str]:
    """Tatorte mit Verstößen an mehr als `grenze` (Standard `FEST_TAGE`) Tagen in mindestens
    einem Jahr."""
    grenze = FEST_TAGE if grenze is None else grenze
    je = v.groupby([v["tag"].str[:4], "tatort"])["tag"].nunique()
    return set(je[je > grenze].index.get_level_values("tatort"))


# --- Tatort lesen --------------------------------------------------------------------------

_PLZ = re.compile(r"^\d{5}\s*,?\s*")  # „53179, Bonn, Mainzer Straße …“
_BONN = re.compile(r"^Bonn\b(?:\s*-\s*(?P<ortsteil>[^,;]+?)\s*(?=[,;]))?\s*[,;]?\s*")
# „Bonn Beuel, Maarstr. …“, „Bonn Bad Godesberg, …“: Ortsteil ohne Bindestrich
_BONN_TEIL = re.compile(
    r"^Bonn\s+(?P<ortsteil>(?:Bad\s+)?[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?)\s*,\s*"
)
_RICHTUNG = re.compile(
    r"(?:[,;]\s*|\s+)(?:\(?\s*)?(?:[Ii]n\s+|[Aa]us\s+)?(?:Fahrtrichtung|Fahrtr\.|i\.\s*Fr\.|Fr\.|"
    r"FR\b\.?|RF\b\.?|Rtg\.|Richtung\b)\s*(?P<ziel>.*)$"
)
_AB = r"(?:BAB\s?(?:A\s?)?|A\s?)(?P<nr>\d{1,3})\b"  # „A 555“, „A555“, „BAB 565“, „BAB A 562“
_AUTOBAHN = re.compile(r"^" + _AB + r"[\s,;/]*(?P<rest>.*)$")
_KM = re.compile(r"\bkm\b\.?\s*[\d.,]+(?:\s*-\s*(?:km\b\.?\s*)?[\d.,]+)?", re.I)
# „August-Bebel-Allee / BAB 562“, „… / A562“: Kreuzung mit der Autobahn
_MIT_AUTOBAHN = re.compile(r"^(?P<strasse>[^/]+?)\s*/\s*" + _AB + r"\s*$")
_BAB = re.compile(r"\b(?:BAB\s?(?:A\s?)?|A\s?)(\d{2,3})\b")  # Querangabe -> „A 565“
_ENDUNG = r"(?i:straße|strasse|str\.|weg|allee|platz|ring|gasse|ufer|damm|wall|pfad|chaussee)"
_STRASSE = re.compile(r"^[A-ZÄÖÜ][^\d,;/]*(?:" + _ENDUNG + r"|(?i:brücke))$")
# Straßennummer vor dem Namen: „L261 Reichsstraße …“ (nicht „L 16 Höhe Auf der Rötschen“)
_REF_VORN = re.compile(
    r"^[BLK]\s?\d{1,4}[a-z]?\s+(?!(?:Höhe|Hoehe|Ecke|Einm|Kreuzung|gg|geg|ggü)\b)"
    r"(?=[A-ZÄÖÜ][\wäöüß.-]*(?:\s+[A-ZÄÖÜ][\wäöüß.-]*)?" + _ENDUNG + r")"
)
_REF_KLAMMER = re.compile(r"\s*\(\s*(?:[BLK]|BAB|A)\s?\d{1,4}[a-z]?\s*\)")  # „Straße (L 16)“


def tatort(text: str) -> dict:
    """Tatort -> Felder des Schemas (Straße, Hausnummer, Kreuzung, Autobahn, Richtung)."""
    s = _PLZ.sub("", _text(text.replace("^", " ")))  # „Siebengebirgsstr.^Höhe“
    m = _BONN_TEIL.match(s)
    if m and _STRASSE.match(m.group("ortsteil")):
        m = None  # „Bonn Kennedyallee, …“ wäre eine Straße, kein Ortsteil
    m = m or _BONN.match(s)
    ortsteil = (m.group("ortsteil") or "").strip() or None if m else None
    rest = s[m.end() :] if m else s
    r = _RICHTUNG.search(rest)
    ziel = r.group("ziel").strip(" .,;)") if r else ""
    if r:
        rest = rest[: r.start()]
    rest = _REF_KLAMMER.sub("", rest)
    rest = " ".join(re.sub(r"[()]", " ", rest).split()).strip(" ,;")  # „(Höhe Brückenforum“
    rest = _REF_VORN.sub("", rest)
    teile = re.split(r"\s*/\s*", rest)
    if len(teile) > 2:  # „Willy-Brandt-Allee / Adenauerallee / Unterführung“: die ersten zwei
        rest = " / ".join(teile[:2])
    out = {
        "strasse": None,
        "hausnummer": None,
        "gegenueber": False,
        "lage_art": "keine",
        "quer1": None,
        "ort": None,
        "autobahn": None,
        "bezirk_roh": ortsteil,
        "richtung_roh": ziel or None,
    }
    ab = _AUTOBAHN.match(rest)
    if ab:
        ort = _KM.sub("", ab.group("rest")).strip(" ,;/-") or None
        einzeln = ort and re.fullmatch(r"[A-ZÄÖÜ][\wäöüß-]*", ort) and not _STRASSE.match(ort)
        if einzeln and not out["richtung_roh"]:
            out["richtung_roh"], ort = ort, None  # „BAB 555; KM 018,000; Bonn“: die Richtung
        out.update(autobahn=f"A {int(ab.group('nr'))}", ort=ort, lage_art="ort" if ort else "keine")
        return out
    mab = _MIT_AUTOBAHN.match(rest)
    if mab:
        q = f"A {int(mab.group('nr'))}"
        out.update(strasse=mab.group("strasse").strip(" ,;"), lage_art="kreuzung", quer1=q)
        return out
    a = adresse(rest)
    quer = a.quer
    # „Oberkasseler Straße, Königswinterer Straße“: zwei Straßen -> Kreuzung
    if not quer and not a.hausnummer and "," in rest:
        zweite = rest.split(",", 1)[1].strip()
        if _STRASSE.match(zweite):
            quer = zweite
    if quer:
        quer = _BAB.sub(r"A \1", quer)
    out.update(
        strasse=a.strasse,
        hausnummer=a.hausnummer,
        gegenueber=a.gegenueber,
        lage_art="kreuzung" if quer else "keine",
        quer1=quer,
    )
    return out


def _kurz(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# --- alles ---------------------------------------------------------------------------------


def lies_alle(dateien: list[Path]) -> tuple[pd.DataFrame, dict]:
    """Alle Jahresdateien -> Kontrollen (mobile Tatorte × Tag) im Schema und ein Bericht."""
    teile, bericht = [], {"dateien": [], "hinweise": []}
    for f in sorted(dateien):
        try:
            d = lies_datei(f)
        except ValueError as e:
            bericht["hinweise"].append(str(e))
            continue
        d["quelle"] = f.name.split("__")[0]
        bericht["dateien"].append(
            {"datei": f.name, "kodierung": tabellen.kodierung(f), "zeilen": int(len(d))}
        )
        teile.append(d)
    if not teile:
        return in_schema(pd.DataFrame()), bericht
    v = pd.concat(teile, ignore_index=True)
    ohne = v["tag"].isna() | (v["tatort"] == "")
    v = v[~ohne]
    fest = feste_anlagen(v)
    ist_fest = v["tatort"].isin(fest)
    bericht.update(
        unlesbar=int(ohne.sum()),
        feste_anlagen=sorted(fest),
        verstoesse_fest=int(ist_fest.sum()),
        verstoesse_mobil=int((~ist_fest).sum()),
    )
    agg = (
        v[~ist_fest]
        .groupby(["tag", "tatort"], as_index=False)
        .agg(verstoesse=("tatort", "size"), quelle=("quelle", "first"))
    )
    orte = {t: tatort(t) for t in agg["tatort"].unique()}
    zeilen = []
    for r in agg.itertuples(index=False):
        o = orte[r.tatort]
        ri = namen.richtung(o["richtung_roh"] or "")
        zeilen.append(
            {
                "id": f"N{r.tag}-{_kurz(r.tatort)}",
                "stadt": "bonn",
                "quelle": r.quelle,
                "datum": r.tag,
                "strasse_roh": r.tatort,
                **{k: o[k] for k in ("strasse", "hausnummer", "gegenueber", "lage_art")},
                "quer1": o["quer1"],
                "ort": o["ort"],
                "autobahn": o["autobahn"],
                "bezirk_roh": o["bezirk_roh"],
                "richtung_roh": o["richtung_roh"],
                "kompass": ri.kompass,
                "richtung_ziel": ri.ziel,
                "ueberschreitungen": int(r.verstoesse),
                "alle_gezaehlt": False,
            }
        )
    df = in_schema(pd.DataFrame(zeilen))
    bericht["kontrollen"] = int(len(df))
    return df, bericht
