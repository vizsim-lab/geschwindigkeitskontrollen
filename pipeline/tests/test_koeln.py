# SPDX-License-Identifier: AGPL-3.0-or-later
"""Köln: Datum, Adresse, Stadtteil, Standorttyp – und die Zusammenfassung zu Kontrollen an
kleinen Dateien im Aufbau der echten (tests/fixtures/koeln: 2017–2022 mit Kopf und ohne
Dienststelle für 2017, 2023 ohne Kürzel in der Standorttabelle, 2024 ohne Kopfzeile)."""

from pathlib import Path

import pandas as pd
import pytest

from kontrollen import koeln

FIX = Path(__file__).parent / "fixtures" / "koeln"


def test_datum_ohne_fuehrende_null():
    s = pd.Series(["10119", "311219", " 50320", "010124        ", "kaputt"])
    d = koeln.datum(s)
    assert d.iloc[:4].tolist() == ["2019-01-01", "2019-12-31", "2020-03-05", "2024-01-01"]
    assert pd.isna(d.iloc[4])


@pytest.mark.parametrize(
    "text, strasse, nr, ggue, quer",
    [
        ("Amsterdamer Str. 80-86", "Amsterdamer Str.", "80", False, None),
        ("Kieskaulerweg ggü. Haus Nr.65", "Kieskaulerweg", "65", True, None),
        ("Mengenicher Str Höhe Haus 20", "Mengenicher Str", "20", False, None),
        ("Berrenrather Str. Höhe 179", "Berrenrather Str.", "179", False, None),
        ("Nettesheimerstr.Hs.Nr.76a-173", "Nettesheimerstr.", "76a", False, None),
        ("Berg. Gladbacher Str.829-791", "Berg. Gladbacher Str.", "829", False, None),
        ("Kaiserstraße Hausnr.51-39", "Kaiserstraße", "51", False, None),
        ("Siegburger Straße ggü.161-147", "Siegburger Straße", "161", True, None),
        ("Hohensyburgstraße ggüb. 104", "Hohensyburgstraße", "104", True, None),
        ("Venloer Str:ggü.Hausnr.507-543", "Venloer Str", "507", True, None),
        ("Girlitzweg geg.Nr.24 v.Hs.22b", "Girlitzweg", "24", True, None),
        ("Neusser Str. HS NR.293-325a", "Neusser Str.", "293", False, None),
        ("Lat.139 - Neusser Landstr.379", "Neusser Landstr.", "379", False, None),
        ("Wahner Str. Laterne 33-Haus 73", "Wahner Str.", "73", False, None),
        ("Sternenburgstr. Nr.:23", "Sternenburgstr.", "23", False, None),  # Bonn
        ("Röckumstraße unterhalb der BAB-Unterführung", "Röckumstraße", None, False, None),
        # Laternen, Lichtmasten, Kilometer und Meter sind keine Hausnummern
        ("Melatengürtel, Laterne 85-77", "Melatengürtel", None, False, None),
        ("Etzelstr. Lat.Nr.106-150", "Etzelstr.", None, False, None),
        ("Widdersdorfer Landstr.Lat11-13", "Widdersdorfer Landstr.", None, False, None),
        ("Dellbrücker Mauspfad L.21-11", "Dellbrücker Mauspfad", None, False, None),
        ("Bensbergerstr.L 489 0,29-0,240", "Bensbergerstr.", None, False, None),
        ("Venloer Str. 20mtr.vor Lat.238", "Venloer Str.", None, False, None),
        ("Friedr.-Schmidt-Str.ggü.Lat.56", "Friedr.-Schmidt-Str.", None, True, None),
        # Kreuzungen und Orte an der Straße
        ("Butzweiler Str./Rochusstr.", "Butzweiler Str", None, False, "Rochusstr"),
        ("Militärring v.Bachemer Landstr", "Militärring", None, False, "Bachemer Landstr"),
        ("Holzmarkt unter Severinsbrücke", "Holzmarkt", None, False, "Severinsbrücke"),
        ("K.-Aden.-Ufer Höhe Servasgasse", "K.-Aden.-Ufer", None, False, "Servasgasse"),
        ("Kalscheurer Weg vor Kita", "Kalscheurer Weg", None, False, None),
        ("Frankfurter Str. S-Bahnbrücke", "Frankfurter Str.", None, False, None),
        ("LuxemburgerStr.Klettenbergpark", "LuxemburgerStr.", None, False, None),
        # Straßennamen, die wie Zusätze anfangen, bleiben ganz
        ("Vorgebirgstraße 12", "Vorgebirgstraße", "12", False, None),
        ("Unter Sachsenhausen 10", "Unter Sachsenhausen", "10", False, None),
        ("Mastweg 7", "Mastweg", "7", False, None),
        ("Militärringstraße", "Militärringstraße", None, False, None),
    ],
)
def test_adresse(text, strasse, nr, ggue, quer):
    assert koeln.adresse(text) == koeln.Adresse(strasse, nr, ggue, quer)


@pytest.mark.parametrize(
    "text, erwartet",
    [
        ("AA   Riehl                    ", ("Riehl", None)),
        ("1682 Riehl", ("Riehl", None)),
        ("A0   Höhenberg", ("Höhenberg", None)),
        ("Altstadt-Nord", ("Altstadt-Nord", None)),
        ("R118 BAB 4, km 66,320", (None, "A 4")),
        ("971  BAB 1, km 407,075", (None, "A 1")),
    ],
)
def test_stadtteil_feld(text, erwartet):
    assert koeln.stadtteil_feld(text) == erwartet


def test_richtung():
    assert koeln.richtung("in Fahrtrichtung stadtauswärts").ziel == "stadtauswärts"
    assert koeln.richtung("in Fahrtr. Bergisch-Gladbacher Str.").ziel == "Bergisch-Gladbacher Str."
    assert koeln.richtung("in Fahrtrichtung Süden").kompass == "S"


@pytest.mark.parametrize(
    "name, typ",
    [
        ("geschwindigkeitsueberwachung-koeln-2023__Standorttabelle_s01.csv", "S-01"),
        ("x__s-loc-02_2.csv", "S-02"),
        ("x__k-loc-03_0.csv", "K-03"),
        ("x__sloc-11_0.csv", "S-11"),
        ("x__Geschwindigkeitsueberwachung_Koeln_Gesamt_2024.csv", None),
        ("x__Geschwindigkeitsüberwachung_Köln_ab_2017_bis_2022.csv.gz", None),
    ],
)
def test_typ_aus_name(name, typ):
    assert koeln.typ_aus_name(name) == typ


def test_standorttabelle_ohne_kopf_und_ohne_kuerzel():
    tabs = {
        (ds, "S-02"): koeln.lies_standorte(FIX / f"{ds}__Standorttabelle_s02.csv", "S-02")
        for ds in ("koeln-2017-bis-2022", "koeln-2023", "koeln-2024")
    }
    t24 = tabs[("koeln-2024", "S-02")]
    assert t24["standort"].tolist() == [101, 102]
    assert t24["tempo"].tolist() == ["050", "010"]
    assert t24["ort2"].iloc[1] == "Astrid-Lindgen-Allee Nr.3-35"
    # 2023: vorn steht eine Kennziffer (0, 6) – sie weicht von den anderen Jahren ab, das Kürzel
    # kommt über den Text
    b = koeln.Bericht()
    koeln.pruefe_kuerzel(tabs, b)
    assert tabs[("koeln-2023", "S-02")]["standort"].isna().all()
    assert tabs[("koeln-2024", "S-02")]["standort"].notna().all()
    koeln.ergaenze_kuerzel(tabs, b)
    assert tabs[("koeln-2023", "S-02")]["standort"].tolist() == [101, 102]
    # sonst ist eine Kennziffer an doppelten Werten zu erkennen
    t = koeln.lies_standorte(FIX / "koeln-2023__Standorttabelle_s02.csv", "S-02")
    assert t["ort1"].iloc[0] == "AA   Riehl"


@pytest.fixture(scope="module")
def ergebnis():
    return koeln.lies_alle(sorted(FIX.iterdir()))


def test_nur_mobile_kontrollen(ergebnis):
    df, _ = ergebnis
    assert sorted(df["id"]) == [
        "K2017-01-02-0101",  # 2017 ohne Dienststelle, Kürzel nur in s02
        "K2018-03-15-0972",  # S-02 an 972 = Brühler Straße (in s01 ist 972 die Rheinbrücke)
        "K2019-05-01-0105",  # S-01 an einem Kürzel, das nur in s02 steht
        "K2019-05-02-0137",
        "K2019-05-02-0999",  # S-02 ohne Eintrag in der Standorttabelle
        "K2023-01-01-0101",
        "K2023-01-01-0102",
        "K2024-01-02-0102",
    ]
    assert (df["stadt"] == "koeln").all()
    assert df["messungen"].isna().all() and not df["alle_gezaehlt"].any()
    assert df["beginn"].isna().all() and df["dauer_min"].isna().all()


def test_verstoesse_und_stufen(ergebnis):
    df, _ = ergebnis
    k = df.set_index("id")
    assert k.loc["K2017-01-02-0101", ["ueberschreitungen", "stufe1", "stufe2"]].tolist() == [
        2,
        1,
        1,
    ]
    assert k.loc["K2024-01-02-0102", ["ueberschreitungen", "stufe1", "stufe2"]].tolist() == [
        3,
        2,
        1,
    ]
    assert (k["stufe_kmh"] == 20).all()


def test_orte_aus_dem_eigenen_datensatz(ergebnis):
    df, _ = ergebnis
    k = df.set_index("id")
    r = k.loc["K2018-03-15-0972"]
    assert (r["strasse"], r["hausnummer"], r["bezirk_roh"]) == (
        "Brühler Straße",
        "117",
        "Raderberg",
    )
    assert r["richtung_ziel"] == "stadteinwärts" and r["tempo"] == 50
    r = k.loc["K2019-05-02-0137"]
    assert (r["strasse"], r["lage_art"], r["quer1"]) == ("Butzweiler Str", "kreuzung", "Rochusstr")
    # 2023: Kürzel über den Text aus 2024 (und 2017–2022)
    r = k.loc["K2023-01-01-0102"]
    assert (r["strasse"], r["hausnummer"], r["bezirk_roh"], r["tempo"]) == (
        "Astrid-Lindgen-Allee",
        "3",
        "Brück",
        10,
    )
    assert pd.isna(k.loc["K2019-05-02-0999", "strasse"])


def test_bericht(ergebnis):
    _, b = ergebnis
    je = {d["datei"].split("__")[0]: d for d in b["dateien"]}
    a = je["koeln-2017-bis-2022"]
    assert (a["zeilen"], a["mobil"], a["fest"], a["kreuzung"], a["unlesbar"]) == (11, 7, 3, 1, 0)
    assert (je["koeln-2023"]["mobil"], je["koeln-2023"]["unlesbar"]) == (2, 1)
    assert (je["koeln-2024"]["mobil"], je["koeln-2024"]["fest"]) == (3, 1)
    assert any("ohne Kürzel – 2 von 2 Zeilen" in h for h in b["hinweise"])
    assert any("1 Kontrollen an 1 Standorten ohne Eintrag" in h for h in b["hinweise"])
