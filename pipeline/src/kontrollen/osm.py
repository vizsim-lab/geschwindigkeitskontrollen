# SPDX-License-Identifier: AGPL-3.0-or-later
"""OSM-Abzug (Geofabrik-PBF) -> kompakte Tabellen für die Verortung.

Ein Durchlauf mit pyosmium liest, was die Verortung braucht, und schreibt je Stadt vier
GeoParquet-Dateien nach data/interim/osm/ (EPSG:4326):

- `strassen_<stadt>`: benannte Wege mit highway-Tag – Name, alte/andere Namen, Brücken- und
  Tunnelnamen, ref (Autobahn-Nummer), highway, maxspeed (nur als Kontext)
- `adressen_<stadt>`: Hausnummern (Knoten und Gebäude, Gebäude als Mittelpunkt)
- `knoten_<stadt>`: Anschlussstellen (highway=motorway_junction) mit Name und Nummer
- `gebiete_<stadt>`: Verwaltungsgrenzen (Berlin: Land, Bezirke, Ortsteile)

Zugeschnitten wird auf die `bbox` der Stadt (Aachen kommt aus dem Regierungsbezirk Köln). Die
Dateien sind klein genug, um sie zum Entwickeln ohne Netz weiterzugeben (Workflow
„Entwicklungsauszug“).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import osmium
import shapely
from shapely.geometry import LineString, Point

# highway-Werte ohne Straßencharakter
KEINE_STRASSE = {
    "proposed",
    "abandoned",
    "razed",
    "construction",
    "elevator",
    "platform",
    "disused",
}
# Straßen, auf denen Kfz fahren (für die Hauptstraße einer Kontrolle); Querstraßen dürfen alles
KFZ = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "service", "road", "busway",
}  # fmt: skip
NAMEN_TAGS = ("name", "old_name", "alt_name", "official_name", "bridge:name", "tunnel:name")


@dataclass
class Auszug:
    strassen: gpd.GeoDataFrame
    adressen: gpd.GeoDataFrame
    knoten: gpd.GeoDataFrame
    gebiete: gpd.GeoDataFrame


def _in_bbox(lon: float, lat: float, bbox: tuple[float, float, float, float] | None) -> bool:
    return bbox is None or (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3])


def _coords(way) -> list[tuple[float, float]]:
    out = []
    for n in way.nodes:
        if n.location.valid():
            out.append((n.lon, n.lat))
    return out


def lies(
    pbf: Path,
    bbox: Iterable[float] | None = None,
    admin_level: Iterable[str] = ("4", "9", "10"),
) -> Auszug:
    """PBF (oder .osm-XML) lesen und auf `bbox` (lon_min, lat_min, lon_max, lat_max) zuschneiden."""
    box = tuple(bbox) if bbox is not None else None
    strassen, adressen, knoten = [], [], []

    filt = osmium.filter.KeyFilter("highway", "addr:housenumber", *ORT_TAGS)
    fp = osmium.FileProcessor(str(pbf)).with_locations().with_filter(filt)
    for obj in fp:
        tags = obj.tags
        if obj.is_node():
            lon, lat = obj.location.lon, obj.location.lat
            if not _in_bbox(lon, lat, box):
                continue
            art = _ort_art(tags)
            if art:
                knoten.append(_ort(f"n{obj.id}", art, tags, Point(lon, lat)))
            if "addr:housenumber" in tags:
                adressen.append(_adresse(f"n{obj.id}", tags, Point(lon, lat)))
        elif obj.is_way():
            pts = _coords(obj)
            if len(pts) < 2 or not any(_in_bbox(x, y, box) for x, y in pts):
                continue
            art = _ort_art(tags)
            if art and pts[0] == pts[-1] and len(pts) >= 4:  # Platz als Fläche -> Mitte
                knoten.append(_ort(f"w{obj.id}", art, tags, shapely.Polygon(pts).centroid))
            hw = tags.get("highway")
            if hw and hw not in KEINE_STRASSE and any(t in tags for t in (*NAMEN_TAGS, "ref")):
                eintrag = {
                    "osm_id": f"w{obj.id}",
                    "highway": hw,
                    "ref": tags.get("ref"),
                    "maxspeed": tags.get("maxspeed"),
                    "geometry": LineString(pts),
                }
                for t in NAMEN_TAGS:
                    eintrag[t.replace(":", "_")] = tags.get(t)
                strassen.append(eintrag)
            if "addr:housenumber" in tags and pts[0] == pts[-1] and len(pts) >= 4:
                ring = shapely.Polygon(pts)
                p = ring.representative_point() if not ring.is_valid else ring.centroid
                adressen.append(_adresse(f"w{obj.id}", tags, p))

    gebiete = _gebiete(pbf, box, set(admin_level))
    return Auszug(
        strassen=_gdf(
            strassen,
            ["osm_id", "highway", "ref", "maxspeed", *[t.replace(":", "_") for t in NAMEN_TAGS]],
        ),
        adressen=_gdf(adressen, ["osm_id", "strasse", "hausnummer", "plz", "ortsteil"]),
        knoten=_gdf(knoten, ["osm_id", "art", "name", "ref"]),
        gebiete=gebiete,
    )


# Benannte Orte, die die Polizei statt einer Querstraße nennt ("/Innsbrucker Platz",
# "Brandenburger Tor", "AS Kaiserdamm"): Anschlussstellen, Plätze, Knotenpunkte, Bahnhöfe,
# Denkmäler. Nur mit Namen; die Verortung nimmt sie nur nah an der Straße (ORT_MAX).
ORT_TAGS = ("place", "junction", "railway", "historic", "tourism")


def _ort_art(tags) -> str | None:
    if not tags.get("name"):
        return None
    if tags.get("highway") == "motorway_junction":
        return "anschlussstelle"
    if tags.get("place") == "square":
        return "platz"
    if "junction" in tags and tags.get("highway") is None:
        return "knoten"
    if tags.get("railway") in ("station", "halt"):
        return "bahnhof"
    if tags.get("historic") == "monument" or tags.get("tourism") == "attraction":
        return "sehenswuerdigkeit"
    return None


def _ort(osm_id: str, art: str, tags, p: Point) -> dict:
    return {
        "osm_id": osm_id,
        "art": art,
        "name": tags.get("name"),
        "ref": tags.get("ref"),
        "geometry": p,
    }


def _adresse(osm_id: str, tags, p: Point) -> dict:
    return {
        "osm_id": osm_id,
        "strasse": tags.get("addr:street") or tags.get("addr:place"),
        "hausnummer": tags.get("addr:housenumber"),
        "plz": tags.get("addr:postcode"),
        "ortsteil": tags.get("addr:suburb"),
        "geometry": p,
    }


def _gebiete(pbf: Path, box, ebenen: set[str]) -> gpd.GeoDataFrame:
    """Verwaltungsflächen (Relationen und geschlossene Wege) der gewünschten admin_level."""
    wkb = osmium.geom.WKBFactory()
    zeilen = []
    filt = osmium.filter.TagFilter(("boundary", "administrative"))
    fp = osmium.FileProcessor(str(pbf)).with_areas(filt).with_filter(filt)
    for obj in fp:
        if not obj.is_area():
            continue
        lvl = obj.tags.get("admin_level")
        if lvl not in ebenen or not obj.tags.get("name"):
            continue
        try:
            geom = shapely.from_wkb(wkb.create_multipolygon(obj))
        except RuntimeError:
            continue
        if box is not None and not geom.intersects(shapely.box(*box)):
            continue
        zeilen.append(
            {
                "osm_id": ("r" if obj.from_way() is False else "w") + str(obj.orig_id()),
                "name": obj.tags.get("name"),
                "admin_level": lvl,
                "geometry": geom,
            }
        )
    return _gdf(zeilen, ["osm_id", "name", "admin_level"])


def _gdf(zeilen: list[dict], spalten: list[str]) -> gpd.GeoDataFrame:
    if not zeilen:
        return gpd.GeoDataFrame({s: [] for s in spalten}, geometry=[], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame(zeilen, geometry="geometry", crs="EPSG:4326")
    return gdf[[*spalten, "geometry"]]


def schreibe(a: Auszug, ordner: Path, stadt: str) -> list[Path]:
    ordner.mkdir(parents=True, exist_ok=True)
    out = []
    for name in ("strassen", "adressen", "knoten", "gebiete"):
        pfad = ordner / f"{name}_{stadt}.parquet"
        getattr(a, name).to_parquet(pfad, index=False, compression="zstd")
        out.append(pfad)
    return out


def lade(ordner: Path, stadt: str) -> Auszug:
    teile = {}
    for name in ("strassen", "adressen", "knoten", "gebiete"):
        teile[name] = gpd.read_parquet(ordner / f"{name}_{stadt}.parquet")
    return Auszug(**teile)
