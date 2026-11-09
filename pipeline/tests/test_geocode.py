"""Verortung am ausgedachten Ausschnitt tests/fixtures/mini.osm (Beschreibung dort)."""

import math

import pytest
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
