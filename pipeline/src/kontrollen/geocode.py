# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kontrollen über Straßennamen, Hausnummern und Querstraßen im OSM-Netz verorten.

Muster: vizsim/berlin-traffic-counts_schulwege (`geocode.py`) – Namen normalisieren, gestuft
in Gebieten suchen, Treffpunkte von Straßen bündeln, bei Zweifel lieber keine Antwort als eine
falsche. Neu hier sind Hausnummern und Abschnitte. Je Kontrolle, von genau nach grob:

1. **hausnummer** – die OSM-Adresse (Hausnummer an der Hauptstraße) auf die Straßenachse
   gelegt. Liegen auch die Querstraßen vor, wird geprüft, ob der Punkt im Abschnitt liegt;
   mehr als `WIDERSPRUCH` m daneben -> es gilt der Abschnitt, mit Hinweis.
2. **abschnitt** – Mitte des Stücks der Hauptstraße zwischen den Kreuzungen mit A und B,
   entlang der Straße gemessen (das Stück selbst geht als Linie in die Karte).
3. **kreuzung** – Kreuzung mit der einen genannten Straße ("/C"), mit einer Autobahn, der
   Stadtgrenze oder einem benannten Ort (Platz, Brücke, Bahnhof) nah an der Straße.
4. **anschlussstelle** – Autobahn: Anschlussstelle, Tunnel oder Brücke auf der A-Nummer.
5. **strasse** – nur die Straße ist bekannt: Mitte ihres längsten Stücks im Suchgebiet (in der
   Karte blass, ≈, mit der ganzen Straße als Linie).

Gesucht wird gestuft (`Gebiete.stufen`): in den genannten Bezirken (+`PUFFER_GEBIET` m), in
deren Umgebung (+`NACHSUCHE` m), dann in der ganzen Stadt. Die erste genaue Antwort (Stufen
1–4) gewinnt; „nur die Straße“ gilt erst, wenn keine Stufe mehr findet – und stadtweit nur,
wenn die Straße nicht an mehreren Orten liegt.

Ortsnamen der Polizei, die so nicht in OSM stehen ("TRH" = Tunnel Rudower Höhe), übersetzt
config/orte.yaml – die Verortung bekommt dann einen Hinweis.

Metrisch im `crs_m` der Stadt (Berlin EPSG:25833, Aachen EPSG:25832), Ausgabe EPSG:4326.
"""

from __future__ import annotations

import difflib
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

import geopandas as gpd
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, substring

from kontrollen import namen
from kontrollen.osm import KFZ, Auszug

PUFFER_GEBIET = 300  # m um Bezirke/Stadt (Grenzen laufen oft auf Straßen)
NACHSUCHE = 2000  # m: zweite Stufe – Umgebung der genannten Bezirke
QUER_PUFFER = 1000  # m: Querstraßen und Orte dürfen so weit über das Suchgebiet reichen
NAH = 20  # m: Straßen, die sich knapp verfehlen (Mittelstreifen, Plätze), treffen sich
BUENDEL = 40  # m: Treffpunkte näher als das sind dieselbe Kreuzung (Richtungsfahrbahnen)
KNOTEN_BUENDEL = 1600  # m: Punkte einer Anschlussstelle (je Fahrtrichtung) liegen so weit
MAX_ABSCHNITT = 3000  # m: A und B weiter auseinander -> kein Abschnitt
ADRESSE_MAX = 200  # m: Adresse weiter von der Straße weg -> andere Straße gleichen Namens
WIDERSPRUCH = 250  # m: Hausnummer so weit außerhalb des Abschnitts -> Abschnitt gilt
MEHRDEUTIG = 400  # m: zwei gleich gute Kandidaten weiter auseinander -> keine Antwort
ORT_MAX = 500  # m: Ort (Platz, Anschlussstelle, Brücke) so weit von der Straße -> passt nicht
FREMD_MAX = 100  # m: Ort auf einer anderen Autobahn als genannt – nur so nah
LUECKE = 250  # m: Teile einer Straße mit größerer Lücke liegen an verschiedenen Orten
PRAEFIX_MIN = 12  # Zeichen: kürzere abgeschnittene Namen nicht über den Anfang suchen
FUZZY = 0.9  # Mindestähnlichkeit für Tippfehler, nur innerhalb des Suchgebiets

METHODEN = ("hausnummer", "abschnitt", "kreuzung", "anschlussstelle", "strasse")
HINWEIS_AUSSERHALB = "Hausnummer liegt außerhalb des Abschnitts"
HINWEIS_EINE = "nur eine der Querstraßen gefunden"
HINWEIS_ORT = "Ortsangabe statt Querstraße"
HINWEIS_ZUORDNUNG = "Ortsangabe von Hand zugeordnet (config/orte.yaml)"


# --- Straßennetz ---------------------------------------------------------------------------


@dataclass
class Netz:
    """Straßen, Adressen und benannte Orte einer Stadt in metrischen Koordinaten."""

    crs_m: str
    geom: dict[str, shapely.Geometry]  # Schlüssel -> alle Wege dieses Namens
    kfz: dict[str, shapely.Geometry]  # Schlüssel -> nur Wege für Kfz (Hauptstraße)
    anzeige: dict[str, str]  # Schlüssel -> Name wie in OSM
    maxspeed: dict[str, str]  # Schlüssel -> häufigstes maxspeed (Kontext fürs Popup)
    alias: dict[str, str]  # alter/anderer Name -> Schlüssel des heutigen Namens
    alias_geom: dict[str, shapely.Geometry]  # alter/anderer Name -> die Wege, die ihn tragen
    autobahn: dict[str, shapely.Geometry]  # "A 100" -> Autobahn-Wege mit dieser Nummer
    adressen: dict[str, dict[str, list[Point]]]  # Straßenschlüssel -> Hausnummer -> Punkte
    orte: list[tuple[str, str, str, Point]]  # (Schlüssel, Name, Art, Punkt)
    ortsnamen: dict[str, str] = field(default_factory=dict)  # Schlüssel Polizei -> OSM-Name
    _baum: tuple | None = field(default=None, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    # -- Aufbau --
    @classmethod
    def aus_auszug(cls, a: Auszug, crs_m: str, ortsnamen: dict[str, str] | None = None) -> Netz:
        s = a.strassen.to_crs(crs_m)
        s = s[s.geometry.notna() & ~s.geometry.is_empty]
        geom: dict[str, list] = defaultdict(list)
        kfz: dict[str, list] = defaultdict(list)
        anzeige: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        speeds: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        alias_ziel: dict[str, str] = {}
        alias_geom: dict[str, list] = defaultdict(list)
        autobahn: dict[str, list] = defaultdict(list)
        for row in s.itertuples(index=False):
            g = row.geometry
            name = row.name if isinstance(row.name, str) else None
            if name:
                k = namen.schluessel(name)
                if k:
                    geom[k].append(g)
                    anzeige[k][name] += 1
                    if row.highway in KFZ:
                        kfz[k].append(g)
                        if isinstance(row.maxspeed, str):
                            speeds[k][row.maxspeed] += 1
            for spalte in ("old_name", "alt_name", "official_name", "bridge_name", "tunnel_name"):
                wert = getattr(row, spalte, None)
                if not isinstance(wert, str):
                    continue
                for teil in wert.split(";"):
                    ak = namen.schluessel(teil)
                    if not ak:
                        continue
                    alias_geom[ak].append(g)
                    if name:
                        alias_ziel.setdefault(ak, namen.schluessel(name))
            if row.highway in ("motorway", "trunk") and isinstance(row.ref, str):
                for r in row.ref.split(";"):
                    nr = namen.autobahn(r.strip())
                    if nr:
                        autobahn[nr[0]].append(g)
        einig = {k: shapely.union_all(v) for k, v in geom.items()}
        netz = cls(
            crs_m=crs_m,
            geom=einig,
            kfz={k: shapely.union_all(v) for k, v in kfz.items()},
            anzeige={k: max(v, key=v.get) for k, v in anzeige.items()},
            maxspeed={k: max(v, key=v.get) for k, v in speeds.items()},
            alias={k: z for k, z in alias_ziel.items() if k not in einig},
            alias_geom={k: shapely.union_all(v) for k, v in alias_geom.items() if k not in einig},
            autobahn={k: shapely.union_all(v) for k, v in autobahn.items()},
            adressen={},
            orte=[],
            ortsnamen={namen.schluessel(k): v for k, v in (ortsnamen or {}).items()},
        )
        netz._lade_adressen(a.adressen.to_crs(crs_m))
        kn = a.knoten.to_crs(crs_m)
        arten = kn["art"] if "art" in kn else pd.Series(["anschlussstelle"] * len(kn))
        for row, art in zip(kn.itertuples(index=False), arten, strict=True):
            if isinstance(row.name, str):
                netz.orte.append((namen.schluessel(row.name), row.name, art, row.geometry))
        return netz

    def _lade_adressen(self, adr: gpd.GeoDataFrame) -> None:
        idx: dict[str, dict[str, list[Point]]] = defaultdict(lambda: defaultdict(list))
        for row in adr.itertuples(index=False):
            if not isinstance(row.strasse, str) or not isinstance(row.hausnummer, str):
                continue
            k = namen.schluessel(row.strasse)
            for h in namen.hausnummer_schluessel(row.hausnummer):
                idx[k][h].append(row.geometry)
        self.adressen = {k: dict(v) for k, v in idx.items()}

    # -- Suche --
    def im_gebiet(self, gebiet: shapely.Geometry) -> list[str]:
        """Schlüssel aller Straßen (und alten/anderen Namen), die das Gebiet berühren."""
        if self._baum is None:
            keys = list(self.geom) + list(self.alias_geom)
            geoms = [self.geom[k] for k in self.geom] + [
                self.alias_geom[k] for k in self.alias_geom
            ]
            self._baum = (keys, shapely.STRtree(geoms))
        keys, baum = self._baum
        return [keys[i] for i in baum.query(gebiet, predicate="intersects")]

    def finde(self, name: str | None, gebiet: shapely.Geometry | None) -> str | None:
        """Schlüssel zu einem Namen: exakt/gebeugt, alter Name, Anfang (abgeschnittene Namen),
        Tippfehler – die letzten beiden nur im Gebiet und nur eindeutig."""
        if not name:
            return None
        for v in namen.schluessel_varianten(name):
            if v in self.geom or v in self.alias_geom:
                return v
        k = namen.schluessel(name)
        if gebiet is None or len(k) < 6:
            return None
        ck = ("f", k, id(gebiet))
        if ck in self._cache:
            return self._cache[ck]
        nah = self.im_gebiet(gebiet)
        treffer = None
        if len(k) >= PRAEFIX_MIN:
            anfang = sorted({n for n in nah if n.startswith(k)})
            if len(anfang) == 1:
                treffer = anfang[0]
        if treffer is None and len(k) >= 8:
            nahe = difflib.get_close_matches(k, sorted(set(nah)), n=2, cutoff=FUZZY)
            if len(nahe) == 1:
                treffer = nahe[0]
        self._cache[ck] = treffer
        return treffer

    def strasse(self, k: str, gebiet: shapely.Geometry | None, nur_kfz: bool) -> shapely.Geometry:
        """Geometrie einer Straße (oder eines alten Namens), auf das Gebiet beschnitten."""
        ck = ("s", k, id(gebiet), nur_kfz)
        if ck in self._cache:
            return self._cache[ck]
        if k in self.geom:
            g = self.kfz.get(k) if nur_kfz else None
            g = g if g is not None and not g.is_empty else self.geom[k]
        else:
            g = self.alias_geom.get(k, shapely.GeometryCollection())
        if gebiet is not None:
            g = g.intersection(gebiet)
        self._cache[ck] = g
        return g

    def name(self, k: str) -> str:
        if k in self.anzeige:
            return self.anzeige[k]
        ziel = self.alias.get(k)
        return self.anzeige.get(ziel, k) if ziel else k

    def adress_punkte(self, k: str, hnr: str) -> list[Point]:
        out = list(self.adressen.get(k, {}).get(hnr, []))
        ziel = self.alias.get(k)
        if ziel and ziel != k:
            out += self.adressen.get(ziel, {}).get(hnr, [])
        return out

    def ortsname(self, text: str) -> str | None:
        """Übersetzung aus config/orte.yaml: ganzer Text oder Kürzel am Anfang ("TAG Gerosteig")."""
        k = namen.schluessel(text)
        if k in self.ortsnamen:
            return self.ortsnamen[k]
        erstes = re.match(r"^([A-ZÄÖÜ]{2,5})\b", text.strip())
        if erstes and namen.schluessel(erstes.group(1)) in self.ortsnamen:
            return self.ortsnamen[namen.schluessel(erstes.group(1))]
        return None


# --- Geometrie-Helfer ----------------------------------------------------------------------


def _punkte(geom: shapely.Geometry) -> list[Point]:
    if geom.is_empty:
        return []
    if isinstance(geom, Point):
        return [geom]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _punkte(g)]
    # gemeinsames Teilstück zweier Linien -> dessen Mitte
    return [geom.interpolate(0.5, normalized=True)] if geom.length else [geom.centroid]


def treffpunkte(a: shapely.Geometry, b: shapely.Geometry) -> list[Point]:
    """Schnittpunkte zweier Straßen, gebündelt (`BUENDEL` m); knapp verfehlt (< NAH m) zählt."""
    if a.is_empty or b.is_empty:
        return []
    pts = _punkte(a.intersection(b))
    if not pts and a.distance(b) < NAH:
        p, q = nearest_points(a, b)
        pts = [Point((p.x + q.x) / 2, (p.y + q.y) / 2)]
    return buendel(pts)


def buendel(pts: list[Point], radius: float = BUENDEL) -> list[Point]:
    gruppen: list[list[Point]] = []
    for p in pts:
        for g in gruppen:
            mx = sum(q.x for q in g) / len(g)
            my = sum(q.y for q in g) / len(g)
            if math.hypot(p.x - mx, p.y - my) <= radius:
                g.append(p)
                break
        else:
            gruppen.append([p])
    return [Point(sum(q.x for q in g) / len(g), sum(q.y for q in g) / len(g)) for g in gruppen]


def _linien(g: shapely.Geometry) -> list[LineString]:
    if g.is_empty:
        return []
    merged = shapely.line_merge(g) if not isinstance(g, LineString) else g
    if isinstance(merged, LineString):
        return [merged]
    if hasattr(merged, "geoms"):
        return [x for x in merged.geoms if isinstance(x, LineString)]
    return []


def abschnitt(strasse: shapely.Geometry, pa: Point, pb: Point) -> LineString:
    """Stück der Straße zwischen zwei Punkten; liegt keins durchgehend dazwischen, die Gerade."""
    beste: LineString | None = None
    for linie in _linien(strasse):
        if linie.distance(pa) > BUENDEL or linie.distance(pb) > BUENDEL:
            continue
        da, db = linie.project(pa), linie.project(pb)
        teil = substring(linie, min(da, db), max(da, db))
        if not isinstance(teil, LineString) or teil.length == 0:
            continue
        # das direkteste Stück (Richtungsfahrbahn statt Umweg über eine Schleife)
        if beste is None or teil.length < beste.length:
            beste = teil
    if beste is not None and beste.length <= 2.5 * pa.distance(pb) + 50:
        return beste
    return LineString([nearest_points(strasse, pa)[0], nearest_points(strasse, pb)[0]])


def mitte(linie: LineString) -> Point:
    return linie.interpolate(0.5, normalized=True)


def repraesentant(g: shapely.Geometry) -> Point:
    """Mitte des längsten zusammenhängenden Stücks einer Straße."""
    linien = _linien(g)
    if not linien:
        return g.representative_point()
    return mitte(max(linien, key=lambda x: x.length))


def mehrfach(g: shapely.Geometry) -> bool:
    """Liegt eine Straße an mehreren, getrennten Orten (gleicher Name in zwei Ortsteilen)?
    Lücken bis `2 * LUECKE` m (ein Platz, eine Brücke mit eigenem Namen) gelten als eine."""
    teile = g.buffer(LUECKE)
    return hasattr(teile, "geoms") and len(teile.geoms) > 1


# --- Gebiete -------------------------------------------------------------------------------


class Stufe:
    """Ein Suchgebiet: `flaeche` für die Hauptstraße, `weit` für Querstraßen und Orte."""

    def __init__(self, flaeche: shapely.Geometry, art: str):
        self.flaeche = flaeche
        self.art = art
        self.weit = flaeche.buffer(QUER_PUFFER)
        shapely.prepare(self.flaeche)
        shapely.prepare(self.weit)


@dataclass
class Gebiete:
    stadt: shapely.Geometry  # Stadtgrenze + PUFFER_GEBIET
    grenze: shapely.Geometry  # die Stadtgrenze als Linie ("… u. Stadtgrenze")
    bezirke: dict[str, shapely.Geometry]  # Name -> Fläche (ohne Puffer)
    _stufen: dict = field(default_factory=dict, repr=False)

    @classmethod
    def aus_auszug(cls, a: Auszug, crs_m: str, cfg: dict, bezirk_ebene: str | None) -> Gebiete:
        g = a.gebiete.to_crs(crs_m)
        sg = cfg["stadtgrenze"]
        ebenen = [str(x) for x in sg["admin_level"]]
        kand = g[(g["name"] == sg["name"]) & g["admin_level"].astype(str).isin(ebenen)]
        if kand.empty:
            stadt = shapely.union_all(g.geometry.values) if len(g) else shapely.box(*cfg["bbox"])
        else:
            stadt = min(kand.geometry, key=lambda x: x.area)
        bezirke = {}
        if bezirk_ebene:
            for row in g[g["admin_level"].astype(str) == bezirk_ebene].itertuples(index=False):
                bezirke[row.name] = row.geometry
        return cls(stadt=stadt.buffer(PUFFER_GEBIET), grenze=stadt.boundary, bezirke=bezirke)

    def bezirke_aus(self, teile: list[str]) -> list[str]:
        """Abgeschnittene Bezirksnamen über den Anfang: "Charlottenburg-Wilmersd" -> ganzer Name."""
        out = []
        for t in teile:
            k = namen.schluessel(t)
            if len(k) < 3:
                continue
            treffer = [n for n in self.bezirke if namen.schluessel(n).startswith(k)]
            if len(treffer) == 1 and treffer[0] not in out:
                out.append(treffer[0])
        return out

    def stufen(self, teile: tuple[str, ...]) -> list[Stufe]:
        """Suchgebiete von eng nach weit: genannte Bezirke, deren Umgebung, die Stadt."""
        if teile in self._stufen:
            return self._stufen[teile]
        out: list[Stufe] = []
        bez = self.bezirke_aus(list(teile))
        if bez:
            flaeche = shapely.union_all([self.bezirke[b] for b in bez])
            out.append(Stufe(flaeche.buffer(PUFFER_GEBIET), "bezirk"))
            out.append(Stufe(flaeche.buffer(NACHSUCHE), "umgebung"))
        out.append(Stufe(self.stadt, "stadt"))
        self._stufen[teile] = out
        return out


# --- Verortung -----------------------------------------------------------------------------


@dataclass
class Ergebnis:
    punkt: Point  # metrisch
    methode: str
    gebiet: str
    strasse: str | None  # Name der Hauptstraße in OSM
    abschnitt: shapely.Geometry | None = None  # metrisch; bei „strasse“ die ganze Straße
    abstand_adresse_m: float | None = None  # Adresse -> Straßenachse
    abstand_abschnitt_m: float | None = None  # Hausnummer-Punkt -> Abschnitt A–B
    hinweis: str | None = None
    maxspeed: str | None = None

    @property
    def rang(self) -> int:
        """0 = genau; 1 = Kreuzung/Anschlussstelle; 2 = nur eine Querstraße; 3 = nur Straße."""
        if self.methode in ("hausnummer", "abschnitt"):
            return 0
        if self.methode == "strasse":
            return 3
        return 2 if self.hinweis == HINWEIS_EINE else 1


@dataclass(frozen=True)
class Anfrage:
    strasse: str | None
    hausnummer: str | None
    lage_art: str | None
    quer1: str | None
    quer2: str | None
    ort: str | None
    autobahn: str | None
    bezirke: tuple[str, ...]


def anfrage(row) -> Anfrage:
    def t(v):
        return v if isinstance(v, str) and v.strip() else None

    bez = tuple(x.strip() for x in str(t(row.bezirk_roh) or "").split(",") if x.strip())
    return Anfrage(
        strasse=t(row.strasse),
        hausnummer=t(row.hausnummer),
        lage_art=t(row.lage_art),
        quer1=t(row.quer1),
        quer2=t(row.quer2),
        ort=t(row.ort),
        autobahn=t(row.autobahn),
        bezirke=bez,
    )


def verorte(a: Anfrage, netz: Netz, gebiete: Gebiete) -> Ergebnis | None:
    """Stufe für Stufe; die erste genaue Antwort gewinnt, sonst die beste gefundene."""
    beste: Ergebnis | None = None
    for st in gebiete.stufen(a.bezirke):
        if a.autobahn:
            e = _autobahn(a, netz, st, gebiete.grenze)
        else:
            e = _strasse(a, netz, st, gebiete.grenze)
        if e is None:
            continue
        if e.rang <= 1:
            return e
        if beste is None or e.rang < beste.rang:
            beste = e
    return beste


def _strasse(a: Anfrage, netz: Netz, st: Stufe, grenze) -> Ergebnis | None:
    flaeche, art, weit = st.flaeche, st.art, st.weit
    k = netz.finde(a.strasse, flaeche)
    if not k:
        return None
    gx = netz.strasse(k, flaeche, nur_kfz=True)
    if gx.is_empty:
        return None
    name, vmax = netz.name(k), netz.maxspeed.get(netz.alias.get(k, k))

    pa = pb = None
    seg: LineString | None = None
    kreuz: list[Point] = []
    hinweis = None
    if a.lage_art == "zwischen":
        (ka, ha), (kb, hb) = (
            _quer(a.quer1, k, gx, netz, weit, grenze),
            _quer(a.quer2, k, gx, netz, weit, grenze),
        )
        paare = sorted(((p.distance(q), p, q) for p in ka for q in kb), key=lambda t: t[0])
        if paare and paare[0][0] <= MAX_ABSCHNITT:
            _, pa, pb = paare[0]
            seg = abschnitt(gx, pa, pb)
            hinweis = ha or hb
        elif ka or kb:
            kreuz, hinweis = (ka, ha) if ka else (kb, hb)
            hinweis = HINWEIS_EINE
    elif a.lage_art == "kreuzung":
        kreuz, hinweis = _quer(a.quer1, k, gx, netz, weit, grenze)
    if a.ort and not kreuz and seg is None:
        kreuz, hinweis = _ort(a.ort, gx, netz, weit)

    # 1. Hausnummer
    hn = _hausnummer(a, k, gx, netz, flaeche, seg, kreuz)
    if hn is not None:
        p_str, d_adr = hn
        if seg is not None:
            d_seg = p_str.distance(seg)
            if d_seg > WIDERSPRUCH:
                return Ergebnis(
                    mitte(seg), "abschnitt", art, name, seg, d_adr, d_seg, HINWEIS_AUSSERHALB, vmax
                )
            return Ergebnis(p_str, "hausnummer", art, name, seg, d_adr, d_seg, None, vmax)
        return Ergebnis(p_str, "hausnummer", art, name, None, d_adr, None, None, vmax)
    # 2. Abschnitt
    if seg is not None:
        return Ergebnis(mitte(seg), "abschnitt", art, name, seg, hinweis=hinweis, maxspeed=vmax)
    # 3. Kreuzung
    if kreuz and (len(kreuz) == 1 or max(p.distance(kreuz[0]) for p in kreuz) <= MEHRDEUTIG):
        return Ergebnis(kreuz[0], "kreuzung", art, name, hinweis=hinweis, maxspeed=vmax)
    # 5. nur die Straße – stadtweit nur, wenn sie nicht an mehreren Orten liegt
    if art == "stadt" and mehrfach(gx):
        return None
    return Ergebnis(repraesentant(gx), "strasse", art, name, gx, maxspeed=vmax)


def _quer(
    n: str | None, k: str | None, gx, netz: Netz, weit, grenze
) -> tuple[list[Point], str | None]:
    """Punkte auf der Hauptstraße für eine Querangabe: Straße, Autobahn ("BAB A 111"),
    Stadtgrenze, sonst ein benannter Ort nah an der Straße. -> (Punkte, Hinweis)"""
    if not n:
        return [], None
    zu = netz.ortsname(n)  # config/orte.yaml
    hinweis = HINWEIS_ZUORDNUNG if zu else None
    n = zu or n
    q = netz.finde(n, weit)
    if q and q != k:
        pts = treffpunkte(gx, netz.strasse(q, weit, nur_kfz=False))
        if pts:
            return pts, hinweis
    ab = namen.autobahn(n)
    if ab and ab[0] in netz.autobahn:
        pts = treffpunkte(gx, netz.autobahn[ab[0]].intersection(weit))
        if pts:
            return pts, hinweis
    if namen.schluessel(n) == "stadtgrenze":
        pts = treffpunkte(gx, grenze.intersection(weit))
        if pts:
            return pts, hinweis
    pts, h = _ort(n, gx, netz, weit)
    return pts, (hinweis or h or HINWEIS_ORT) if pts else None


_VORSATZ = re.compile(r"^(?:Höhe|Hoehe|vor|hinter|nach|ehem\.?|Brücke|Tunnel|Zollamt)\s+", re.I)


def _ort_namen(text: str, netz: Netz) -> list[tuple[str, str | None]]:
    """Suchnamen für eine Ortsangabe, genaue zuerst -> [(Name, Hinweis)]."""
    out: list[tuple[str, str | None]] = []
    zu = netz.ortsname(text)
    if zu:
        out.append((zu, HINWEIS_ZUORDNUNG))
    _, name = namen.autobahn_ort(text)  # AS/AD/AK/Ausf./Einf. weg
    out.append((name, None))
    ohne = _VORSATZ.sub("", name)
    if ohne != name:
        out.append((ohne, None))
    if namen.schluessel(ohne).endswith("bruecke"):  # "Knobelsdorffbrücke" ~ Knobelsdorffstraße
        out.append((re.sub(r"(?i)brücke$", "straße", ohne), None))
    gesehen, eindeutig = set(), []
    for n, h in out:
        if n and n not in gesehen:
            gesehen.add(n)
            eindeutig.append((n, h))
    return eindeutig


def _ort(text: str, gx, netz: Netz, gebiet) -> tuple[list[Point], str | None]:
    """Ort statt Querstraße ("Knobelsdorffbrücke", "AS Kaiserdamm", "/Innsbrucker Platz") ->
    Punkte auf der Straße (höchstens `ORT_MAX` m daneben), mit Hinweis bei Zuordnung von Hand."""
    for name, hinweis in _ort_namen(text, netz):
        q = netz.finde(name, gebiet)
        if q:
            g = netz.strasse(q, gebiet, nur_kfz=False)
            pts = treffpunkte(gx, g)
            if not pts and not g.is_empty and g.distance(gx) <= ORT_MAX:
                pts = [nearest_points(gx, g)[0]]
            if pts:
                return pts, hinweis
        pts = _orte(name, netz, gebiet)
        if pts:
            nahe = [nearest_points(gx, p)[0] for p in pts if p.distance(gx) <= ORT_MAX]
            if nahe:
                return buendel(nahe), hinweis
    return [], None


def _orte(name: str, netz: Netz, gebiet) -> list[Point]:
    """Benannte Orte (Anschlussstellen, Plätze …): "Kaiserdamm", "Dreieck Funkturm" ~ "Funkturm".
    Punkte desselben Namens (eine Anschlussstelle je Fahrtrichtung) -> ihre Mitte."""
    k = namen.schluessel(name)
    if len(k) < 4:
        return []
    exakt = [p for kk, _, _, p in netz.orte if kk == k and gebiet.contains(p)]
    pts = exakt or [
        p
        for kk, _, _, p in netz.orte
        if (kk.endswith(k) or k.endswith(kk)) and len(kk) >= 4 and gebiet.contains(p)
    ]
    return buendel(pts, KNOTEN_BUENDEL)


def _hausnummer(
    a: Anfrage, k: str, gx, netz: Netz, flaeche, seg, kreuz
) -> tuple[Point, float] | None:
    """Adresse an der Hauptstraße -> (Punkt auf der Straßenachse, Abstand Adresse–Achse)."""
    if not a.hausnummer:
        return None
    pts = [p for p in netz.adress_punkte(k, a.hausnummer) if flaeche.contains(p)]
    pts = [p for p in pts if p.distance(gx) <= ADRESSE_MAX]
    if not pts:
        return None
    anker = seg if seg is not None else (kreuz[0] if kreuz else None)
    if anker is not None:
        p = min(pts, key=lambda q: q.distance(anker))
    elif max(q.distance(pts[0]) for q in pts) <= MEHRDEUTIG:
        p = pts[0]
    else:
        return None  # dieselbe Hausnummer an weit getrennten Stellen, nichts entscheidet
    return nearest_points(gx, p)[0], p.distance(gx)


def _autobahn(a: Anfrage, netz: Netz, st: Stufe, grenze) -> Ergebnis | None:
    """Autobahn: Orte (Anschlussstellen, Tunnel, Brücken) auf der genannten A-Nummer; findet sich
    dort nichts, auf einer anderen Autobahn, wenn alle Orte höchstens `FREMD_MAX` m daneben
    liegen (die Daten nennen die A 103 in Steglitz „A 100“)."""
    if st.art != "stadt":
        return None  # Autobahnen laufen über Bezirksgrenzen: gleich in der ganzen Stadt suchen
    orte = [o for o in (a.quer1, a.quer2, a.ort) if o]
    if not orte:
        return None  # nur die Nummer: eine Autobahn quer durch die Stadt ist kein Ort
    refs = [a.autobahn] + sorted(r for r in netz.autobahn if r != a.autobahn)
    for ref in refs:
        g = netz.autobahn.get(ref)
        if g is None:
            continue
        gx = g.intersection(st.flaeche)
        if gx.is_empty:
            continue
        punkte, hinweise = [], []
        for o in orte:
            p, h = _quer(o, None, gx, netz, st.weit, grenze)
            if h == HINWEIS_ORT:
                h = None  # an der Autobahn ist ein Ort die normale Angabe
            if len(p) > 1 and max(x.distance(p[0]) for x in p) > MEHRDEUTIG:
                p = []
            if ref != a.autobahn and p and min(_abstand_ort(o, gx, netz, st.weit)) > FREMD_MAX:
                p = []
            punkte.append(p[0] if p else None)
            if h:
                hinweise.append(h)
        gefunden = [p for p in punkte if p is not None]
        if ref != a.autobahn and len(gefunden) < len(orte):
            continue
        hinweis = hinweise[0] if hinweise else None
        if ref != a.autobahn:
            hinweis = f"auf der {ref} gefunden (Quelle: {a.autobahn})"
        if len(gefunden) >= 2 and gefunden[0].distance(gefunden[1]) <= MAX_ABSCHNITT:
            seg = abschnitt(gx, gefunden[0], gefunden[1])
            return Ergebnis(mitte(seg), "abschnitt", st.art, ref, seg, hinweis=hinweis)
        if gefunden:
            return Ergebnis(gefunden[0], "anschlussstelle", st.art, ref, hinweis=hinweis)
    return None


def _abstand_ort(text: str, gx, netz: Netz, gebiet) -> list[float]:
    """Abstand eines Orts zur Autobahn (für die Probe auf einer anderen A-Nummer)."""
    out = []
    for name, _ in _ort_namen(text, netz):
        q = netz.finde(name, gebiet)
        if q:
            out.append(netz.strasse(q, gebiet, nur_kfz=False).distance(gx))
        out += [p.distance(gx) for p in _orte(name, netz, gebiet)]
    return out or [math.inf]


# --- Tabelle -------------------------------------------------------------------------------


def verorte_tabelle(df: pd.DataFrame, netz: Netz, gebiete: Gebiete) -> pd.DataFrame:
    """Für jede Kontrolle -> lon/lat, Methode, Suchgebiet, Straße, Abschnitt (WKT), Abstände.

    Dieselbe Anfrage (Straße, Nr., Lage, Bezirke) wird nur einmal gerechnet."""
    nach_wgs = Transformer.from_crs(netz.crs_m, "EPSG:4326", always_xy=True)
    gerechnet: dict[Anfrage, dict] = {}
    zeilen = []
    for row in df.itertuples(index=False):
        q = anfrage(row)
        if q not in gerechnet:
            gerechnet[q] = _als_zeile(verorte(q, netz, gebiete), nach_wgs)
        zeilen.append({"id": row.id, **gerechnet[q]})
    return pd.DataFrame(zeilen)


def _als_zeile(e: Ergebnis | None, nach_wgs: Transformer) -> dict:
    if e is None:
        return {k: None for k in _FELDER}
    lon, lat = nach_wgs.transform(e.punkt.x, e.punkt.y)
    seg = None
    if e.abschnitt is not None and not e.abschnitt.is_empty and e.abschnitt.length > 0:
        # bei „nur Straße“ die ganze Straße, gröber vereinfacht (sie ist nur Kontext)
        vereinfacht = e.abschnitt.simplify(1.0 if e.methode != "strasse" else 8.0)
        seg = shapely.to_wkt(
            shapely.transform(vereinfacht, lambda xy: _wgs(xy, nach_wgs)), rounding_precision=6
        )
    return {
        "geo_lon": round(lon, 6),
        "geo_lat": round(lat, 6),
        "geo_methode": e.methode,
        "geo_gebiet": e.gebiet,
        "geo_strasse": e.strasse,
        "geo_abschnitt": seg,
        "geo_abschnitt_m": round(e.abschnitt.length)
        if e.abschnitt is not None and e.methode != "strasse"
        else None,
        "geo_abstand_adresse_m": _r(e.abstand_adresse_m),
        "geo_abstand_abschnitt_m": _r(e.abstand_abschnitt_m),
        "geo_hinweis": e.hinweis,
        "osm_maxspeed": e.maxspeed,
    }


def _wgs(xy, nach_wgs: Transformer):
    import numpy as np

    x, y = nach_wgs.transform(xy[:, 0], xy[:, 1])
    return np.column_stack([x, y])


_FELDER = (
    "geo_lon", "geo_lat", "geo_methode", "geo_gebiet", "geo_strasse", "geo_abschnitt",
    "geo_abschnitt_m", "geo_abstand_adresse_m", "geo_abstand_abschnitt_m", "geo_hinweis",
    "osm_maxspeed",
)  # fmt: skip


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


# --- Prüfung -------------------------------------------------------------------------------


def validiere(df: pd.DataFrame, geo: pd.DataFrame) -> dict:
    """Wie gut die Verortung ist – ohne GPS-Wahrheit, darum zwei Gegenproben:

    - **Hausnummer gegen Abschnitt**: Wo beides vorliegt, sollte der Hausnummer-Punkt im
      Abschnitt zwischen A und B liegen (Abstand 0). Misst, wie oft Hausnummer, Querstraßen
      und OSM zusammenpassen.
    - **Anteile je Methode** und Kontrollen ohne Lage, je Stadt.
    """
    m = df[["id", "stadt"]].merge(geo, on="id", how="left")
    out: dict = {}
    for stadt, t in m.groupby("stadt"):
        n = len(t)
        je = t["geo_methode"].value_counts().to_dict()
        d = t["geo_abstand_abschnitt_m"].dropna().astype(float)
        eintrag = {
            "kontrollen": int(n),
            "verortet": int(t["geo_methode"].notna().sum()),
            "je_methode": {k: int(je.get(k, 0)) for k in METHODEN},
            "ohne_lage": int(t["geo_methode"].isna().sum()),
            "je_gebiet": {str(k): int(v) for k, v in t["geo_gebiet"].value_counts().items()},
            "hinweise": {str(k): int(v) for k, v in t["geo_hinweis"].value_counts().items()},
        }
        if len(d):
            eintrag["hausnummer_gegen_abschnitt"] = {
                "n": int(len(d)),
                "im_abschnitt": round(float((d <= 1).mean()), 3),
                "unter_50m": round(float((d <= 50).mean()), 3),
                "ueber_widerspruch": round(float((d > WIDERSPRUCH).mean()), 3),
                "median_m": round(float(d.median()), 1),
                "p90_m": round(float(d.quantile(0.9)), 1),
            }
        a = t["geo_abstand_adresse_m"].dropna().astype(float)
        if len(a):
            eintrag["adresse_zur_achse_m"] = {
                "median": round(float(a.median()), 1),
                "p90": round(float(a.quantile(0.9)), 1),
            }
        out[str(stadt)] = eintrag
    return out
