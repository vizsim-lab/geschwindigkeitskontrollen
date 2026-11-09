# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kontrollen über Straßennamen, Hausnummern und Querstraßen im OSM-Netz verorten.

Muster: vizsim/berlin-traffic-counts_schulwege (`geocode.py`) – Namen normalisieren, gestuft
in Gebieten suchen, Treffpunkte von Straßen bündeln, bei Zweifel lieber keine Antwort als eine
falsche. Neu hier sind Hausnummern und Abschnitte. Je Kontrolle, gestuft von genau nach grob:

1. **hausnummer** – die OSM-Adresse (Hausnummer an der Hauptstraße) auf die Straßenachse
   gelegt. Liegen auch die Querstraßen vor, wird geprüft, ob der Punkt im Abschnitt liegt;
   mehr als `WIDERSPRUCH` m daneben -> es gilt der Abschnitt, mit Hinweis.
2. **abschnitt** – Mitte des Stücks der Hauptstraße zwischen den Kreuzungen mit A und B,
   entlang der Straße gemessen (das Stück selbst geht als Linie in die Karte).
3. **kreuzung** – Kreuzung mit der einen genannten Straße ("/C") oder mit dem genannten Ort
   (Brücke, Platz).
4. **anschlussstelle** – Autobahn: die Anschlussstelle auf der richtigen A-Nummer.
5. **strasse** – nur die Straße ist bekannt: Mitte ihres längsten Stücks im Suchgebiet (in der
   Karte blass, ≈).

Gesucht wird gestuft (`Gebiete.stufen`): in den genannten Bezirken (+`PUFFER_GEBIET` m), in
deren Umgebung (+`NACHSUCHE` m), dann in der ganzen Stadt – dort aber ohne die grobe Stufe 5,
wenn die Straße mehrfach vorkommt.

Metrisch im `crs_m` der Stadt (Berlin EPSG:25833, Aachen EPSG:25832), Ausgabe EPSG:4326.
"""

from __future__ import annotations

import difflib
import math
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
NAH = 20  # m: Straßen, die sich knapp verfehlen (Mittelstreifen, Plätze), treffen sich
BUENDEL = 40  # m: Treffpunkte näher als das sind dieselbe Kreuzung (Richtungsfahrbahnen)
MAX_ABSCHNITT = 3000  # m: A und B weiter auseinander -> kein Abschnitt
ADRESSE_MAX = 150  # m: Adresse weiter von der Straße weg -> andere Straße gleichen Namens
WIDERSPRUCH = 250  # m: Hausnummer so weit außerhalb des Abschnitts -> Abschnitt gilt
MEHRDEUTIG = 400  # m: zwei gleich gute Kandidaten weiter auseinander -> keine Antwort
ORT_MAX = 500  # m: Ort (Anschlussstelle, Brücke) so weit von der Straße -> passt nicht
LUECKE = 250  # m: Teile einer Straße mit größerer Lücke liegen an verschiedenen Orten
PRAEFIX_MIN = 12  # Zeichen: kürzere abgeschnittene Namen nicht über den Anfang suchen
FUZZY = 0.9  # Mindestähnlichkeit für Tippfehler, nur innerhalb des Suchgebiets

METHODEN = ("hausnummer", "abschnitt", "kreuzung", "anschlussstelle", "strasse")


# --- Straßennetz ---------------------------------------------------------------------------


@dataclass
class Netz:
    """Straßen, Adressen und Anschlussstellen einer Stadt in metrischen Koordinaten."""

    crs_m: str
    geom: dict[str, shapely.Geometry]  # Schlüssel -> alle Wege dieses Namens
    kfz: dict[str, shapely.Geometry]  # Schlüssel -> nur Wege für Kfz (Hauptstraße)
    anzeige: dict[str, str]  # Schlüssel -> Name wie in OSM
    maxspeed: dict[str, str]  # Schlüssel -> häufigstes maxspeed (Kontext fürs Popup)
    alias: dict[str, str]  # alter/anderer Name -> Schlüssel des heutigen Namens
    alias_geom: dict[str, shapely.Geometry]  # alter/anderer Name -> die Wege, die ihn tragen
    autobahn: dict[str, shapely.Geometry]  # "A 100" -> Autobahn-Wege mit dieser Nummer
    adressen: dict[str, dict[str, list[Point]]]  # Straßenschlüssel -> Hausnummer -> Punkte
    knoten: list[tuple[str, str, Point]]  # (Schlüssel des Namens, Name, Punkt)
    _baum: tuple | None = field(default=None, repr=False)
    _cache: dict = field(default_factory=dict, repr=False)

    # -- Aufbau --
    @classmethod
    def aus_auszug(cls, a: Auszug, crs_m: str) -> Netz:
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
        alias = {k: z for k, z in alias_ziel.items() if k not in einig}
        ag = {k: shapely.union_all(v) for k, v in alias_geom.items() if k not in einig}
        netz = cls(
            crs_m=crs_m,
            geom=einig,
            kfz={k: shapely.union_all(v) for k, v in kfz.items()},
            anzeige={k: max(v, key=v.get) for k, v in anzeige.items()},
            maxspeed={k: max(v, key=v.get) for k, v in speeds.items()},
            alias=alias,
            alias_geom=ag,
            autobahn={k: shapely.union_all(v) for k, v in autobahn.items()},
            adressen={},
            knoten=[],
        )
        netz._lade_adressen(a.adressen.to_crs(crs_m))
        kn = a.knoten.to_crs(crs_m)
        for row in kn.itertuples(index=False):
            if isinstance(row.name, str):
                netz.knoten.append((namen.schluessel(row.name), row.name, row.geometry))
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
        if self._baum is None:
            keys = list(self.geom)
            self._baum = (keys, shapely.STRtree([self.geom[k] for k in keys]))
        keys, baum = self._baum
        return [keys[i] for i in baum.query(gebiet, predicate="intersects")]

    def finde(self, name: str | None, gebiet: shapely.Geometry | None) -> str | None:
        """Schlüssel zu einem Namen: exakt/gebeugt, alter Name, Anfang (abgeschnittene Namen),
        Tippfehler – die letzten beiden nur im Gebiet und nur eindeutig."""
        if not name:
            return None
        for v in namen.schluessel_varianten(name):
            if v in self.geom:
                return v
            if v in self.alias_geom:
                return v
        k = namen.schluessel(name)
        if gebiet is None or len(k) < 6:
            return None
        nah = self.im_gebiet(gebiet)
        if len(k) >= PRAEFIX_MIN:
            anfang = sorted({n for n in nah if n.startswith(k)})
            if len(anfang) == 1:
                return anfang[0]
        if len(k) >= 8:
            treffer = difflib.get_close_matches(k, nah, n=2, cutoff=FUZZY)
            if len(treffer) == 1:
                return treffer[0]
        return None

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


@dataclass
class Gebiete:
    stadt: shapely.Geometry  # Stadtgrenze + PUFFER_GEBIET
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
        return cls(stadt=stadt.buffer(PUFFER_GEBIET), bezirke=bezirke)

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


class Stufe:
    """Ein Suchgebiet: `flaeche` für die Hauptstraße, `weit` (+1 km) für Querstraßen und Orte."""

    def __init__(self, flaeche: shapely.Geometry, art: str):
        self.flaeche = flaeche
        self.art = art
        self.weit = flaeche.buffer(1000)
        shapely.prepare(self.flaeche)
        shapely.prepare(self.weit)


# --- Verortung -----------------------------------------------------------------------------


@dataclass
class Ergebnis:
    punkt: Point  # metrisch
    methode: str
    gebiet: str
    strasse: str | None  # Name der Hauptstraße in OSM
    abschnitt: LineString | None = None  # metrisch
    abstand_adresse_m: float | None = None  # Adresse -> Straßenachse
    abstand_abschnitt_m: float | None = None  # Hausnummer-Punkt -> Abschnitt A–B
    hinweis: str | None = None
    maxspeed: str | None = None


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
    for st in gebiete.stufen(a.bezirke):
        e = _autobahn(a, netz, st) if a.autobahn else _strasse(a, netz, st)
        if e is not None:
            return e
    return None


def _strasse(a: Anfrage, netz: Netz, st: Stufe) -> Ergebnis | None:
    flaeche, art, weit = st.flaeche, st.art, st.weit  # weit: Querstraßen dürfen über die Grenze
    k = netz.finde(a.strasse, flaeche)
    if not k:
        return None
    gx = netz.strasse(k, flaeche, nur_kfz=True)
    if gx.is_empty:
        return None
    name, vmax = netz.name(k), netz.maxspeed.get(netz.alias.get(k, k))

    def kreuzungen(n: str | None) -> list[Point]:
        q = netz.finde(n, weit)
        if not q or q == k:
            return []
        return treffpunkte(gx, netz.strasse(q, weit, nur_kfz=False))

    pa = pb = None
    seg: LineString | None = None
    kreuz: list[Point] = []
    if a.lage_art == "zwischen":
        ka, kb = kreuzungen(a.quer1), kreuzungen(a.quer2)
        paare = sorted(((p.distance(q), p, q) for p in ka for q in kb), key=lambda t: t[0])
        if paare and paare[0][0] <= MAX_ABSCHNITT:
            _, pa, pb = paare[0]
            seg = abschnitt(gx, pa, pb)
        else:
            kreuz = ka or kb
    elif a.lage_art == "kreuzung":
        kreuz = kreuzungen(a.quer1)
    if a.ort and not kreuz and seg is None:
        kreuz = _ort(a.ort, gx, netz, weit)

    # 1. Hausnummer
    hn = _hausnummer(a, k, gx, netz, flaeche, seg, kreuz)
    if hn is not None:
        p_str, d_adr = hn
        if seg is not None:
            d_seg = p_str.distance(seg)
            if d_seg > WIDERSPRUCH:
                return Ergebnis(
                    mitte(seg), "abschnitt", art, name, seg, d_adr, d_seg,
                    f"Hausnummer liegt {d_seg:.0f} m außerhalb des Abschnitts", vmax,
                )  # fmt: skip
            return Ergebnis(p_str, "hausnummer", art, name, seg, d_adr, d_seg, None, vmax)
        return Ergebnis(p_str, "hausnummer", art, name, None, d_adr, None, None, vmax)
    # 2. Abschnitt
    if seg is not None:
        return Ergebnis(mitte(seg), "abschnitt", art, name, seg, maxspeed=vmax)
    # 3. Kreuzung
    if kreuz:
        if len(kreuz) > 1 and max(p.distance(kreuz[0]) for p in kreuz) > MEHRDEUTIG:
            kreuz = []  # mehrere Kreuzungen weit auseinander -> unklar, welche
        else:
            hinweis = "nur eine der Querstraßen gefunden" if a.lage_art == "zwischen" else None
            return Ergebnis(kreuz[0], "kreuzung", art, name, hinweis=hinweis, maxspeed=vmax)
    # 5. nur die Straße – stadtweit nur, wenn sie nicht an mehreren Orten liegt
    if art == "stadt" and mehrfach(gx):
        return None
    return Ergebnis(repraesentant(gx), "strasse", art, name, maxspeed=vmax)


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


def _ort(text: str, gx, netz: Netz, gebiet) -> list[Point]:
    """Ort statt Querstraße ("Knobelsdorffbrücke", "AS Kaiserdamm") -> Punkte auf der Straße."""
    _, name = namen.autobahn_ort(text)
    out: list[Point] = []
    q = netz.finde(name, gebiet)
    if q:
        g = netz.strasse(q, gebiet, nur_kfz=False)
        out = treffpunkte(gx, g)
        if not out and not g.is_empty and g.distance(gx) <= ORT_MAX:
            out = [nearest_points(gx, g)[0]]
    if not out:
        out = [
            nearest_points(gx, p)[0]
            for p in _knoten(name, netz, gebiet)
            if p.distance(gx) <= ORT_MAX
        ]
    return buendel(out)


def _knoten(name: str, netz: Netz, gebiet) -> list[Point]:
    """Anschlussstellen, deren Name passt: "Kaiserdamm", "Dreieck Funkturm" ~ "Funkturm"."""
    k = namen.schluessel(name)
    if len(k) < 4:
        return []
    exakt = [p for kk, _, p in netz.knoten if kk == k and gebiet.contains(p)]
    if exakt:
        return exakt
    return [
        p for kk, _, p in netz.knoten if (kk.endswith(k) or k.endswith(kk)) and gebiet.contains(p)
    ]


def _autobahn(a: Anfrage, netz: Netz, st: Stufe) -> Ergebnis | None:
    if st.art != "stadt":
        return None  # Autobahnen laufen über Bezirksgrenzen: gleich in der ganzen Stadt suchen
    flaeche, art = st.flaeche, st.art
    g = netz.autobahn.get(a.autobahn)
    if g is None:
        return None
    gx = g.intersection(flaeche)
    if gx.is_empty:
        return None
    orte = [o for o in (a.quer1, a.quer2, a.ort) if o]
    punkte = []
    for o in orte:
        p = _ort(o, gx, netz, st.weit)
        if len(p) > 1 and max(x.distance(p[0]) for x in p) > MEHRDEUTIG:
            p = []
        punkte.append(p[0] if p else None)
    gefunden = [p for p in punkte if p is not None]
    if len(gefunden) >= 2 and gefunden[0].distance(gefunden[1]) <= MAX_ABSCHNITT:
        seg = abschnitt(gx, gefunden[0], gefunden[1])
        return Ergebnis(mitte(seg), "abschnitt", art, a.autobahn, seg)
    if gefunden:
        return Ergebnis(gefunden[0], "anschlussstelle", art, a.autobahn)
    return None  # nur die Nummer: eine Autobahn quer durch die Stadt ist kein Ort


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
    if e.abschnitt is not None and e.abschnitt.length > 0:
        xs, ys = nach_wgs.transform(*e.abschnitt.xy)
        seg = shapely.to_wkt(
            LineString(zip(xs, ys, strict=True)).simplify(0.000005), rounding_precision=6
        )
    return {
        "geo_lon": round(lon, 6),
        "geo_lat": round(lat, 6),
        "geo_methode": e.methode,
        "geo_gebiet": e.gebiet,
        "geo_strasse": e.strasse,
        "geo_abschnitt": seg,
        "geo_abschnitt_m": round(e.abschnitt.length) if e.abschnitt is not None else None,
        "geo_abstand_adresse_m": _r(e.abstand_adresse_m),
        "geo_abstand_abschnitt_m": _r(e.abstand_abschnitt_m),
        "geo_hinweis": e.hinweis,
        "osm_maxspeed": e.maxspeed,
    }


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
