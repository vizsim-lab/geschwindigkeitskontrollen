"""Verortung am ausgedachten Ausschnitt tests/fixtures/mini.osm (Beschreibung dort)."""

import math
from types import SimpleNamespace

import geopandas as gpd
import pytest
import shapely
from pyproj import Transformer

from kontrollen import geocode
from kontrollen.geocode import Anfrage

NACH_WGS = Transformer.from_crs("EPSG:25833", "EPSG:4326", always_xy=True)


def frage(strasse, hnr=None, quer=(), ort=None, bezirk="Mitte", autobahn=None):
    art = {0: "ort" if ort else "keine", 1: "kreuzung", 2: "zwischen"}[len(quer)]
    q = list(quer) + [None, None]
    return Anfrage(strasse, hnr, art, q[0], q[1], ort, autobahn, (bezirk,) if bezirk else ())


def lonlat(e):
    return NACH_WGS.transform(e.punkt.x, e.punkt.y)


def nah(e, lon, lat, m=8):
    x, y = lonlat(e)
    d = math.hypot((x - lon) * 67800, (y - lat) * 111300)
    assert d < m, f"{d:.0f} m daneben: {x:.5f}, {y:.5f}"


def test_hausnummer_im_abschnitt(netz, gebiete):
    e = geocode.verorte(frage("Hauptstr.", "10", ("Querweg", "Nebenstr.")), netz, gebiete)
    assert e.methode == "hausnummer"
    nah(e, 13.405, 52.520)
    assert e.abstand_abschnitt_m == pytest.approx(0, abs=1)
    assert e.abschnitt.length == pytest.approx(271, abs=5)
    assert e.abstand_adresse_m == pytest.approx(33, abs=3)
    assert e.maxspeed == "50"


def test_gebaeude_mit_buchstabe(netz, gebiete):
    e = geocode.verorte(frage("Hauptstraße", "20a", ("Querweg", "Nebenstraße")), netz, gebiete)
    assert e.methode == "hausnummer"
    nah(e, 13.406, 52.520)


def test_hausnummer_ausserhalb_abschnitt(netz, gebiete):
    e = geocode.verorte(frage("Hauptstraße", "99", ("Querweg", "Nebenstraße")), netz, gebiete)
    assert e.methode == "abschnitt"
    assert "außerhalb" in e.hinweis
    nah(e, 13.405, 52.520)


def test_abschnitt_mitte(netz, gebiete):
    e = geocode.verorte(frage("Hauptstraße", quer=("Querweg", "Nebenstraße")), netz, gebiete)
    assert e.methode == "abschnitt"
    nah(e, 13.405, 52.520)


def test_kreuzung_und_alter_name(netz, gebiete):
    e = geocode.verorte(frage("Hauptstraße", quer=("Eckallee",)), netz, gebiete)
    assert e.methode == "kreuzung"
    nah(e, 13.415, 52.520)
    e = geocode.verorte(frage("Hauptstraße", quer=("Alte Str.",)), netz, gebiete)
    assert e.methode == "kreuzung"
    nah(e, 13.410, 52.520)


def test_bezirk_entscheidet(netz, gebiete):
    e = geocode.verorte(frage("Hauptstraße", "10", ("Querweg",), bezirk="Pankow"), netz, gebiete)
    assert e.methode == "hausnummer"
    nah(e, 13.405, 52.538)


def test_ohne_bezirk_mehrdeutig(netz, gebiete):
    assert geocode.verorte(frage("Hauptstraße", "10", bezirk=None), netz, gebiete) is None


def test_abgeschnittener_name(netz, gebiete):
    e = geocode.verorte(
        frage("Charlottenburger Chauss", "43", ("Am Rain", "Wiesendamm")), netz, gebiete
    )
    assert e.methode == "hausnummer"
    assert e.strasse == "Charlottenburger Chaussee"
    nah(e, 13.408, 52.524)


def test_tippfehler(netz, gebiete):
    e = geocode.verorte(frage("Hauptstraße", quer=("Querweg", "Nebenstrase")), netz, gebiete)
    assert e.methode == "abschnitt"


def test_nur_strasse(netz, gebiete):
    e = geocode.verorte(frage("Eckallee"), netz, gebiete)
    assert e.methode == "strasse"
    nah(e, 13.415, 52.520)


def test_unbekannt(netz, gebiete):
    assert geocode.verorte(frage("Gibtsnichtweg", "1"), netz, gebiete) is None


def test_autobahn(netz, gebiete):
    e = geocode.verorte(frage("BAB A 100", ort="AS Kaiserdamm", autobahn="A 100"), netz, gebiete)
    assert e.methode == "anschlussstelle"
    nah(e, 13.410, 52.527)
    e = geocode.verorte(
        frage("BAB A 100", quer=("AD Funkturm", "AS Kaiserdamm"), autobahn="A 100"), netz, gebiete
    )
    assert e.methode == "abschnitt"
    nah(e, 13.405, 52.527)


def test_bezirke_abgeschnitten(gebiete):
    assert gebiete.bezirke_aus(["Mit", "Pank"]) == ["Mitte", "Pankow"]
    assert gebiete.bezirke_aus(["X"]) == []


def test_bezirk_vollstaendiger_name_vor_anfang():
    # Köln: „Lind“ und „Weiden“ sind Stadtteile – und der Anfang von „Lindenthal“, „Weidenpesch“
    f = shapely.box(0, 0, 1, 1)
    g = geocode.Gebiete(
        stadt=f, grenze=f.boundary, bezirke={n: f for n in ("Lind", "Lindenthal", "Lindweiler")}
    )
    assert g.bezirke_aus(["Lind"]) == ["Lind"]
    assert g.bezirke_aus(["Linde"]) == ["Lindenthal"]
    assert g.bezirke_aus(["Lin"]) == []  # mehrdeutig


def test_bezirk_falsch_genannt_umgebung_hilft(netz, gebiete):
    # genannt ist Pankow, Querweg UND Nebenstraße treffen sich aber nur mit der Hauptstraße in
    # Mitte: erst die Umgebung (+2 km) findet den Abschnitt – statt „nur Straße“ in Pankow
    e = geocode.verorte(
        frage("Hauptstraße", quer=("Querweg", "Nebenstraße"), bezirk="Pankow"), netz, gebiete
    )
    assert (e.methode, e.gebiet) == ("abschnitt", "umgebung")
    nah(e, 13.405, 52.520)


def test_stadtgrenze_als_querstrasse(netz, gebiete):
    e = geocode.verorte(frage("Grenzweg", quer=("Stadtgrenze",)), netz, gebiete)
    assert e.methode == "kreuzung"
    nah(e, 13.430, 52.512)


def test_autobahn_als_querstrasse(netz, gebiete):
    e = geocode.verorte(frage("Brückenweg", quer=("BAB A 100",)), netz, gebiete)
    assert e.methode == "kreuzung"
    nah(e, 13.418, 52.527)


@pytest.mark.parametrize(
    ("text", "ref"),
    [
        ("Überleitung zur BAB 115", "A 115"),
        ("Überleitung von BAB 115", "A 115"),
        ("Überleitungsfahrbahn zur A115", "A 115"),
        ("BAB A 115 Überleitung", "A 115"),
        ("vor Überl. A 115", "A 115"),
        ("Vollsperrung Überleitung A103 Nachtbaustell", "A 103"),
        ("Überleitungsstraße", None),
        ("AS Kaiserdamm", None),
    ],
)
def test_ueberleitung_erkennen(text, ref):
    assert geocode.ueberleitung(text) == ref


@pytest.mark.parametrize(
    "ort", ["Überleitung zur A 115", "BAB A 115 Überleitung", "vor Überl. A 115"]
)
def test_ueberleitung_zur_anderen_autobahn(netz, gebiete, ort):
    # die A 115 berührt die A 100 nicht (dazwischen nur Rampen): wo sie sich am nächsten kommen
    e = geocode.verorte(frage("BAB A 100", ort=ort, autobahn="A 100"), netz, gebiete)
    assert e.methode == "anschlussstelle"
    nah(e, 13.3995, 52.527)


def test_platz_statt_querstrasse(netz, gebiete):
    e = geocode.verorte(frage("Hauptstraße", quer=("Testplatz",)), netz, gebiete)
    assert e.methode == "kreuzung"
    assert e.hinweis == geocode.HINWEIS_ORT
    nah(e, 13.4125, 52.520)


def test_ortsname_von_hand(auszug, gebiete):
    netz = geocode.Netz.aus_auszug(auszug, "EPSG:25833", {"ICC": "Kaiserdamm"})
    e = geocode.verorte(frage("BAB A 100", ort="ICC", autobahn="A 100"), netz, gebiete)
    assert e.methode == "anschlussstelle"
    assert e.hinweis == geocode.HINWEIS_ZUORDNUNG
    nah(e, 13.410, 52.527)


def test_nur_strasse_bringt_die_strasse_mit(netz, gebiete):
    e = geocode.verorte(frage("Eckallee"), netz, gebiete)
    assert e.abschnitt is not None and e.abschnitt.length == pytest.approx(445, abs=10)


def test_strassennummer_statt_name(netz, gebiete):
    """Bundes-, Landes- und Kreisstraßen auch über ihre Nummer – mit Namen (B 2 = Charlottenburger
    Chaussee) und ohne (K 7)."""
    e = geocode.verorte(frage("B2", quer=("Am Rain",)), netz, gebiete)
    assert e.methode == "kreuzung"
    nah(e, 13.405, 52.524)
    e = geocode.verorte(frage("K 7", quer=("Hauptstraße",)), netz, gebiete)
    assert (e.methode, e.strasse) == ("kreuzung", "K 7")
    nah(e, 13.418, 52.520)
    # das Stück mit name=„K 7“ in Pankow verdrängt die Nummer nicht, beide gehören zusammen
    assert "k7" in netz.nummern
    assert netz.strasse("k7", None, nur_kfz=True).length > 1000
    assert netz.finde("A 100", None) is None  # Autobahnen bleiben bei der Autobahn-Suche


def test_stadt_aus_mehreren_gemeinden(auszug):
    """Ein Ordnungsbehördenbezirk aus mehreren Kommunen: die Flächen aller Namen zusammen."""
    eine = {
        "stadtgrenze": {"name": "Mitte", "admin_level": ["9"]},
        "bbox": [13.38, 52.50, 13.44, 52.56],
    }
    beide = {**eine, "stadtgrenze": {"name": ["Mitte", "Pankow"], "admin_level": ["9"]}}
    g1 = geocode.Gebiete.aus_auszug(auszug, "EPSG:25833", eine, None)
    g2 = geocode.Gebiete.aus_auszug(auszug, "EPSG:25833", beide, None)
    hin = Transformer.from_crs("EPSG:4326", "EPSG:25833", always_xy=True)
    pankow = shapely.Point(*hin.transform(13.41, 52.54))
    assert not g1.stadt.contains(pankow) and g2.stadt.contains(pankow)
    assert g2.stadt.area > 1.5 * g1.stadt.area


def test_bezirke_auf_mehreren_ebenen():
    """Butzbach: Stadtteile auf Ebene 9, die Ortsteile zweier Nachbarkommunen auf 10. Derselbe
    Name auf zwei Ebenen -> die kleinere Fläche; andere Ebenen zählen nicht."""
    flaechen = gpd.GeoDataFrame(
        {
            "name": ["Kommune", "Altdorf", "Altdorf", "Neudorf", "Weiler"],
            "admin_level": ["8", "9", "10", "10", "11"],
        },
        geometry=[
            shapely.box(0, 0, 9000, 9000),
            shapely.box(0, 0, 4000, 4000),
            shapely.box(0, 0, 2000, 2000),
            shapely.box(5000, 5000, 9000, 9000),
            shapely.box(100, 100, 200, 200),
        ],
        crs="EPSG:25832",
    )
    cfg = {"stadtgrenze": {"name": "Kommune", "admin_level": ["8"]}, "bbox": [0, 0, 1, 1]}
    g = geocode.Gebiete.aus_auszug(
        SimpleNamespace(gebiete=flaechen), "EPSG:25832", cfg, ["9", "10"]
    )
    assert sorted(g.bezirke) == ["Altdorf", "Neudorf"]
    assert g.bezirke["Altdorf"].area == pytest.approx(2000 * 2000)
    assert [s.art for s in g.stufen(("Neudorf",))] == ["bezirk", "umgebung", "stadt"]
    eine = geocode.Gebiete.aus_auszug(SimpleNamespace(gebiete=flaechen), "EPSG:25832", cfg, "9")
    assert eine.bezirke["Altdorf"].area == pytest.approx(4000 * 4000)


@pytest.fixture(scope="module")
def streng(auszug):
    """Wie Butzbach: Ortsteile (Mitte, Pankow) einer Kommune (Berlin), strenge Suche."""
    cfg = {
        "stadtgrenze": {"name": "Berlin", "admin_level": ["4"]},
        "bbox": [13.38, 52.50, 13.44, 52.56],
    }
    return geocode.Gebiete.aus_auszug(auszug, "EPSG:25833", cfg, "9", streng=True)


def test_streng_die_strasse_im_ortsteil_gilt(netz, gebiete, streng):
    """Die Hausnummer 99 hat nur die gleichnamige Hauptstraße im Nachbarort: sonst zieht sie die
    Kontrolle dorthin, streng gilt die Straße im genannten Ortsteil."""
    q = frage("Hauptstraße", "99", bezirk="Pankow")
    e = geocode.verorte(q, netz, gebiete)
    assert (e.methode, e.gebiet) == ("hausnummer", "umgebung")
    nah(e, 13.418, 52.520)
    e = geocode.verorte(q, netz, streng)
    assert (e.methode, e.gebiet) == ("strasse", "bezirk")
    nah(e, 13.410, 52.538)
    assert [s.art for s in streng.stufen(("Pankow",))] == ["bezirk", "kommune"]
    assert [s.art for s in streng.stufen(())] == ["stadt"]


def test_streng_nur_in_der_eigenen_kommune(auszug, netz, streng):
    """Nicht im Ortsteil: in seiner Kommune, nicht darüber hinaus; passt dort die genannte
    Querstraße nicht, ist es wohl eine andere Straße gleichen Namens."""
    e = geocode.verorte(frage("Charlottenburger Chaussee", bezirk="Pankow"), netz, streng)
    assert (e.methode, e.gebiet) == ("strasse", "kommune")
    q = frage("Charlottenburger Chaussee", quer=("Querweg",), bezirk="Pankow")
    assert geocode.verorte(q, netz, streng) is None
    # Mitte und Pankow als zwei Kommunen: die Straße in Mitte liegt außerhalb
    cfg = {
        "stadtgrenze": {"name": ["Mitte", "Pankow"], "admin_level": ["9"]},
        "bbox": [13.38, 52.50, 13.44, 52.56],
    }
    zwei = geocode.Gebiete.aus_auszug(auszug, "EPSG:25833", cfg, "9", streng=True)
    assert geocode.verorte(frage("Charlottenburger Chaussee", bezirk="Pankow"), netz, zwei) is None


def test_strassennummer_der_hauptstrasse_ist_keine_kreuzung(netz, gebiete):
    """„Kirchhainer Damm zw. B96 u. …“: die Nummer ist die Hauptstraße selbst – kein Punkt in der
    Mitte des gemeinsamen Stücks, sondern wie ohne diese Angabe."""
    for strasse, quer in (
        ("Charlottenburger Chaussee", "B 2"),
        ("B 2", "Charlottenburger Chaussee"),
    ):
        e = geocode.verorte(frage(strasse, quer=(quer,)), netz, gebiete)
        assert e.methode == "strasse", (strasse, quer)
    e = geocode.verorte(frage("Charlottenburger Chaussee", quer=("B 2", "Am Rain")), netz, gebiete)
    assert (e.methode, e.hinweis) == ("kreuzung", geocode.HINWEIS_EINE)
    nah(e, 13.405, 52.524)
