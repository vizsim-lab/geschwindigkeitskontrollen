# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bonn: Kodierung, feste Anlagen, Tatort lesen, Kontrollen je Tatort und Tag
(tests/fixtures/bonn: 2016 als Mac-Roman, 2023 als cp1252)."""

from pathlib import Path

import pytest

from kontrollen import bonn

FIX = Path(__file__).parent / "fixtures" / "bonn"
FEST = "Bonn, B9 Mainzer Straße Bahnüberführung FR Mehlem"


@pytest.mark.parametrize(
    "text, strasse, nr, quer, autobahn, ort, richtung, ortsteil",
    [
        ("Bonn, Gotenstraße Höhe Hausnummer 51 Fahrtrichtung Mittelstraße",
         "Gotenstraße", "51", None, None, None, "Mittelstraße", None),
        ("Bonn Spreestraße geg. Haus-Nr. 10  Fahrtrichtung Haager Weg",
         "Spreestraße", "10", None, None, None, "Haager Weg", None),
        ("Bonn, Konrad-Adenauer-Damm Höhe Lichtmast Nr. 86  Fahrtrichtung Derlestraße",
         "Konrad-Adenauer-Damm", None, None, None, None, "Derlestraße", None),
        ("Bonn - Mehlem, Remagener Straße, FR. Bad Godesberg",
         "Remagener Straße", None, None, None, None, "Bad Godesberg", "Mehlem"),
        ("Bonn, Oberkasseler Straße, Königswinterer Straße",
         "Oberkasseler Straße", None, "Königswinterer Straße", None, None, None, None),
        ("Bonn, Oberkasseler Straße Höhe Weidenweg 1 Fahrtrichtung Niederholtorf",
         "Oberkasseler Straße", None, "Weidenweg", None, None, "Niederholtorf", None),
        ("Bonn, Endenicher Straße, / Höhe BAB 565",
         "Endenicher Straße", None, "A 565", None, None, None, None),
        ("Bonn, Willy-Brandt-Allee, Aus Rtg. Adenauerallee",
         "Willy-Brandt-Allee", None, None, None, None, "Adenauerallee", None),
        ("Bonn, Marienstraße,  / Höhe Nr. 27 aus Fr. Agnesstraße",
         "Marienstraße", "27", None, None, None, "Agnesstraße", None),
        # Autobahn: nur Kilometer -> kein Ort; Anschlussstelle -> Ort
        ("Bonn, A59; km 029,500-028,500; RF Bonn", None, None, None, "A 59", None, "Bonn", None),
        ("Bonn, BAB 555; KM 018,000; Bonn", None, None, None, "A 555", None, "Bonn", None),
        ("Bonn, BAB565 / AS Poppelsdorf, Fahrtrichtung Reuterstraße",
         None, None, None, "A 565", "AS Poppelsdorf", "Reuterstraße", None),
        ("Bonn, BAB A 562 / August-Bebel-Allee",
         None, None, None, "A 562", "August-Bebel-Allee", None, None),
        ("Bonn, August-Bebel-Allee / A562",
         "August-Bebel-Allee", None, "A 562", None, None, None, None),
        # Postleitzahl vorn, Ortsteil ohne Bindestrich, „Nr.:“, „unterhalb“, Klammern
        ("53179, Bonn, Mainzer Straße, gegenüber Nr. 336",
         "Mainzer Straße", "336", None, None, None, None, None),
        ("Bonn Beuel, Maarstr. gegenüber Nr.: 100", "Maarstr.", "100", None, None, None, None,
         "Beuel"),
        ("Bonn Bad Godesberg, Koblenzer Str. Höhe, Aral Tankstelle",
         "Koblenzer Str.", None, None, None, None, None, "Bad Godesberg"),
        ("Bonn, Röckumstraße unterhalb der BAB-Unterführung, FR An der Ohligsmühle",
         "Röckumstraße", None, None, None, None, "An der Ohligsmühle", None),
        ("Bonn, Niederkasseler Straße (L 16) Höhe Vilicher Straße,",
         "Niederkasseler Straße", None, "Vilicher Straße", None, None, None, None),
        ("Bonn, Kennedybrücke, (Höhe Brückenforum, FR Beuel)",
         "Kennedybrücke", None, "Brückenforum", None, None, "Beuel", None),
        ("Bonn, Willy-Brandt-Allee / Adenauerallee / Unterführung",
         "Willy-Brandt-Allee", None, "Adenauerallee", None, None, None, None),
        # Straßennummer vor dem Namen weg; ohne Namen bleibt sie (nicht verortbar)
        ("Bonn, L261 Reichsstraße Höhe Hubertusstraße FR Röttgen",
         "Reichsstraße", None, "Hubertusstraße", None, None, "Röttgen", None),
        ("Bonn, L 16 Höhe Auf der Rötschen", "L 16", None, "Auf der Rötschen", None, None, None,
         None),
        # kein Querstraßen-Paar: „oberhalb …“ ist keine Straße
        ("Bonn, Fußweg, oberhalb BAB / Zufahrt Reuterstraße", "Fußweg", None, None, None, None,
         None, None),
    ],
)  # fmt: skip
def test_tatort(text, strasse, nr, quer, autobahn, ort, richtung, ortsteil):
    o = bonn.tatort(text)
    got = (o["strasse"], o["hausnummer"], o["quer1"], o["autobahn"], o["ort"])
    assert got == (strasse, nr, quer, autobahn, ort)
    assert (o["richtung_roh"], o["bezirk_roh"]) == (richtung, ortsteil)


def test_mac_roman_und_feste_anlagen():
    v = bonn.lies_datei(
        FIX / "bussgelder-fliessender-verkehr-2016__Bußgelder_fließender_Verkehr_2016.csv.gz"
    )
    assert FEST in set(v["tatort"])  # Mac-Roman richtig gelesen
    assert bonn.feste_anlagen(v, grenze=2) == {FEST}
    assert bonn.feste_anlagen(v, grenze=3) == set()


def test_kontrollen_je_tatort_und_tag(monkeypatch):
    monkeypatch.setattr(bonn, "FEST_TAGE", 2)
    df, b = bonn.lies_alle(sorted(FIX.glob("*.csv.gz")))
    # die feste Anlage bleibt in allen Jahren draußen, auch 2023 mit nur einem Tag
    assert FEST not in set(df["strasse_roh"])
    assert b["feste_anlagen"] == [FEST] and b["verstoesse_fest"] == 4
    assert len(df) == 5 and (df["stadt"] == "bonn").all()
    goten = df[df["strasse"] == "Gotenstraße"].iloc[0]
    assert (goten["datum"], goten["ueberschreitungen"], goten["hausnummer"]) == (
        "2016-01-05",
        2,
        "51",
    )
    assert df["messungen"].isna().all() and df["tempo"].isna().all() and df["stufe2"].isna().all()
    assert not df["alle_gezaehlt"].any()
    assert df["id"].is_unique and df["id"].str.match(r"^N\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$").all()
