"""Berlin: PDF-Anlagen lesen (berlin_pdf) und in das gemeinsame Schema bringen (berlin)."""

import pandas as pd
import pytest
from anlage_pdf import ROT, anlage, zeile

from kontrollen import berlin, berlin_pdf

ZEILEN = [
    zeile("6", "66", "Adlergestell", "423", "Am Seegraben u. Grauammerpfad", "Treptow-Köpenick",
          "Nordwesten/Michael-Brüc", "50", "01.01.2019", "11:13", "16:15", "5.114", "693", "355",
          "41", "5"),
    # keine Angaben zu Stufen und Fahrverboten
    zeile("6", "64", "Landsberger Allee", "174", "Karl-Lade-Str. u. Franz-Jacob-Str.",
          "Pankow, Friedrichshain-Kreuzberg", "Osten/Landsberger Chaus", "50", "01.01.2019",
          "11:22", "16:22", "2.639", "99", "-", "-", "-"),
    # Bezirk läuft in die leere Spalte „Richtung“; über Mitternacht; wechselndes Tempolimit
    zeile("2", "26", "BAB A 100", "L4566", "Einf. Tunnel Schlangenbader Str.",
          "Charlottenburg-Wilmersdorf, Steglitz-Zehlendorf", "", "50/30", "02.01.2019", "22:30",
          "1:50", "165", "165", "120", "45", "11"),
    # „über 20 km/h“ leer – der Nachtrag steht rot und größer darüber (Anlage 3, S. 1)
    zeile("4", "46", "Berliner Str.", "42", "Sundgauer Str. u. Winfriedstr.",
          "Steglitz-Zehlendorf", "Nordosten/Unter den Eic", "50", "02.01.2019", "11:18", "16:23",
          "3.242", "64", "62", "", "0"),
    # mehrtägig: Datum und Uhrzeit in Beginn und Ende
    zeile("4", "43", "Teltower Damm", "30", "Gartenstr. u. Martin-Buber-Str.",
          "Steglitz-Zehlendorf", "Südosten/Stadtgrenze", "10", "21.05.19   11:57",
          "21.05.19   11:57", "23.05.19   08:54", "35", "10", "-", "-", "-"),
]  # fmt: skip


@pytest.fixture()
def pdf(tmp_path):
    weitere = [
        zeile("1", "12", f"Teststr. {i}", str(i), "/Querweg", "Mitte", "Norden/X", "30",
              "03.01.2019", "8:00", "9:00", "10", "1", "1", "0", "0")
        for i in range(1, 46)
    ]  # fmt: skip
    return anlage(
        tmp_path / "anlage3_2019.pdf",
        ZEILEN + weitere,
        nachtraege=[(3, 14, "1", 3.96, ROT, 1.0)],
        fuss="Stand: 05.10.2020",
    )


def test_zeilen(pdf):
    b = berlin_pdf.Bericht(pdf.name)
    z = berlin_pdf.zeilen(pdf, b)
    assert len(z) == 50  # zwei Seiten (40 + 10), die leere dritte zählt nicht
    assert b.seiten == 2
    assert z[0] == {**dict(zip(berlin_pdf.KOPF, ZEILEN[0], strict=True)), "seite": 1, "zeile": 1}
    assert z[2]["Verwaltungsbezirk"] == "Charlottenburg-Wilmersdorf, Steglitz-Zehlendorf"
    assert z[2]["Richtung"] == ""
    assert z[3]["über 20 km/h"] == "1"  # der Nachtrag gehört zur Zeile
    assert z[4]["Ende"] == "23.05.19   08:54"
    assert z[49]["Straßenname"] == "Teststr. 45" and z[49]["seite"] == 2
    assert b.uebersprungen == ["S. 2: Stand: 05.10.2020"]
    assert b.farbig == ["S. 1, über 20 km/h: 1", "S. 2, Straßenname: Stand: 05.10.2020"]
    assert b.geteilte_zellen == 0 and b.fehler == []


def test_unerwarteter_kopf(tmp_path, monkeypatch):
    pfad = anlage(tmp_path / "a.pdf", ZEILEN)
    monkeypatch.setattr(berlin_pdf, "KOPF", [*berlin_pdf.KOPF[:-1], "Bußgeld"])
    with pytest.raises(ValueError, match="Tabellenkopf"):
        berlin_pdf.zeilen(pfad)


@pytest.mark.parametrize(
    ("text", "wert"), [("5.114", 5114), ("123.456", 123456), ("7", 7), ("-", None), ("", None)]
)
def test_zahl(text, wert):
    assert berlin_pdf.zahl(text) == wert


def test_zahl_fehler():
    with pytest.raises(ValueError):
        berlin_pdf.zahl("5,1")


@pytest.mark.parametrize(
    ("datum", "beginn", "ende", "erwartet"),
    [
        ("01.01.2020", "9:30", "11:30", ("2020-01-01 09:30", "2020-01-01 11:30")),
        ("02.01.2019", "22:30", "1:50", ("2019-01-02 22:30", "2019-01-03 01:50")),
        ("21.05.19   11:57", "21.05.19   11:57", "23.05.19   08:54",
         ("2019-05-21 11:57", "2019-05-23 08:54")),
        ("03.02.2020 10:00", "03.02.2020 10:00", "05.02.2020 07:30",
         ("2020-02-03 10:00", "2020-02-05 07:30")),
        ("01.01.2020", "9:30", "", ("2020-01-01 09:30", None)),
    ],
)  # fmt: skip
def test_zeitraum(datum, beginn, ende, erwartet):
    b, e = berlin_pdf.zeitraum(datum, beginn, ende)
    f = "%Y-%m-%d %H:%M"
    assert (b.strftime(f), e.strftime(f) if e else None) == erwartet


def test_zeitraum_fehler():
    with pytest.raises(ValueError):
        berlin_pdf.zeitraum("2019-01-01", "9:00", "10:00")


@pytest.mark.parametrize(("roh", "wert"), [("50", 50), ("50/30", None), ("30/50", None),
                                           ("0", None), ("", None)])  # fmt: skip
def test_tempo(roh, wert):
    assert berlin.tempo(roh) == wert


def test_lies(pdf):
    df, berichte = berlin.lies([({"jahr": 2019}, pdf)])
    assert len(df) == 50
    assert berichte[0]["zeilen"] == 50 and berichte[0]["andere_jahre"] == 0
    r = df.set_index("id")
    a = r.loc["B2019-00001"]
    assert (a["quelle"], a["datum"], a["beginn"], a["dauer_min"]) == (
        "anlage3_2019",
        "2019-01-01",
        "11:13",
        302,
    )
    assert (a["messungen"], a["ueberschreitungen"], a["stufe1"], a["stufe2"]) == (
        5114,
        693,
        355,
        41,
    )
    assert a["hausnummer"] == "423" and a["quer1"] == "Am Seegraben" and bool(a["alle_gezaehlt"])
    b = r.loc["B2019-00002"]
    assert b["stufe1"] is pd.NA and b["fahrverbote"] is pd.NA  # "-" heißt keine Angabe
    c = r.loc["B2019-00003"]
    assert c["tempo"] is pd.NA  # 50/30
    assert (c["dauer_min"], c["autobahn"], c["mast"]) == (200, "A 100", "L4566")
    assert not bool(c["alle_gezaehlt"])  # Messungen = Überschreitungen
    assert r.loc["B2019-00004", "stufe2"] == 1
    e = r.loc["B2019-00005"]
    assert (e["datum"], e["dauer_min"]) == ("2019-05-21", 2697)  # 1 Tag 20:57


def test_lies_meldet_andere_jahre(pdf):
    _, berichte = berlin.lies([({"jahr": 2018}, pdf)])
    assert berichte[0]["andere_jahre"] == 50


def test_zeile_ueberlauf_und_fehler():
    r = dict(zip(berlin_pdf.KOPF, ZEILEN[0], strict=True))
    r |= {"Straßenname": "Charlottenburger Chauss", "Nr.": "ee 43", "Messungen": "5,1"}
    b = berlin_pdf.Bericht("x.pdf")
    z = berlin.zeile(r, "B2018-00001", "anlage2_2018", b)
    assert (z["strasse"], z["hausnummer"], z["strasse_roh"]) == (
        "Charlottenburger Chaussee",
        "43",
        "Charlottenburger Chauss",
    )
    assert z["messungen"] is None and b.fehler == ["B2018-00001 Messungen: keine Zahl: '5,1'"]
    assert z["datum"] == "2019-01-01"
