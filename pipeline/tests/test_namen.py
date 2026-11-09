import pytest

from kontrollen import namen


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Köpenicker Str.", "Koepenicker Strasse"),
        ("Potsdamer Str", "Potsdamer Straße"),
        ("Ollenhauerstr", "Ollenhauerstraße"),
        ("Straße des 17.Juni", "Straße des 17. Juni"),
        ("Allee d.Kosmonauten", "Allee der Kosmonauten"),
        ("Manfred-von-Richthofen-Str", "Manfred-von-Richthofen-Straße"),
    ],
)
def test_schluessel_gleich(a, b):
    assert namen.schluessel(a) == namen.schluessel(b)


def test_beugung():
    assert namen.schluessel("Indische Straße") in namen.schluessel_varianten("Indischen Straße")


@pytest.mark.parametrize(
    ("roh", "hnr", "geg", "mast", "sonst"),
    [
        ("423", "423", False, None, None),
        ("12 a", "12a", False, None, None),
        ("12-14", "12", False, None, None),
        ("g232", "232", True, None, None),
        ("L2980", None, False, "L2980", None),
        ("gL20", None, True, "L20", None),
        ("k5,5", None, False, None, "k5,5"),
        ("", None, False, None, None),
    ],
)
def test_nummer(roh, hnr, geg, mast, sonst):
    n = namen.nummer(roh)
    assert (n.hausnummer, n.gegenueber, n.mast, n.sonst) == (hnr, geg, mast, sonst)


def test_hausnummer_schluessel():
    assert namen.hausnummer_schluessel("20 a") == ["20a", "20"]
    assert namen.hausnummer_schluessel("12-14") == ["12-14", "12", "14"]
    assert namen.hausnummer_schluessel("3;5") == ["3", "5"]


@pytest.mark.parametrize(
    ("roh", "art", "teile"),
    [
        ("Am Seegraben u. Grauammerpfad", "zwischen", ("Am Seegraben", "Grauammerpfad")),
        ("/Firlstr.", "kreuzung", ("Firlstr.",)),
        ("AS Kaiserdamm", "ort", ("AS Kaiserdamm",)),
        ("", "keine", ()),
    ],
)
def test_lage(roh, art, teile):
    lg = namen.lage(roh)
    assert (lg.art, lg.namen) == (art, teile)


def test_richtung():
    r = namen.richtung("Nordwesten/Michael-Brüc")
    assert (r.kompass, r.ziel) == ("NW", "Michael-Brüc")
    assert namen.richtung("Südosten/Stadtgrenze").kompass == "SO"
    assert namen.richtung("Stadtmitte").kompass is None


def test_autobahn():
    assert namen.autobahn("BAB A 100") == ("A 100", "")
    assert namen.autobahn("BAB A 100 AS Messedamm") == ("A 100", "AS Messedamm")
    assert namen.autobahn("Adlergestell") is None
    assert namen.autobahn_ort("AD Funkturm") == ("AD", "Dreieck Funkturm")
    assert namen.autobahn_ort("AS Kaiserdamm") == ("AS", "Kaiserdamm")
    assert (
        namen.autobahn_ort("Ausf. Tunnel Schlangenbader Str.")[1] == "Tunnel Schlangenbader Straße"
    )
