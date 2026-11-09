# SPDX-License-Identifier: AGPL-3.0-or-later
"""Köln: Datum, Adresse, Stadtteil, Standorttyp – und die Zusammenfassung zu Kontrollen."""

import pandas as pd
import pytest

from kontrollen import koeln


def test_datum_ohne_fuehrende_null():
    s = pd.Series(["10119", "311219", " 50320", "kaputt"])
    d = koeln.datum(s)
    assert d.iloc[:3].tolist() == ["2019-01-01", "2019-12-31", "2020-03-05"]
    assert pd.isna(d.iloc[3])


@pytest.mark.parametrize(
    "text, erwartet",
    [
        ("Amsterdamer Str. 80-86", ("Amsterdamer Str.", "80", False)),
        ("Kieskaulerweg, ggü. Haus 65", ("Kieskaulerweg", "65", True)),
        ("Berrenrather Str., Höhe 179", ("Berrenrather Str.", "179", False)),
        ("Mengenicher Str, Höhe Haus 20", ("Mengenicher Str", "20", False)),
        ("Thuleweg ggü. Haus 42", ("Thuleweg", "42", True)),
        ("Militärringstraße", ("Militärringstraße", None, False)),
    ],
)
def test_adresse(text, erwartet):
    assert koeln.adresse(text) == erwartet


def test_stadtteil_ohne_code_davor():
    assert koeln.stadtteil("RO Rodenkirchen") == "Rodenkirchen"
    assert koeln.stadtteil("Sülz") == "Sülz"
    assert koeln.stadtteil("Altstadt-Nord") == "Altstadt-Nord"


@pytest.mark.parametrize(
    "name, typ",
    [
        ("geschwindigkeitsueberwachung-koeln-2023__Standorttabelle_s01.csv", "S-01"),
        ("x__s-loc-02_2.csv", "S-02"),
        ("x__k-loc-03_0.csv", "K-03"),
        ("x__sloc-11_0.csv", "S-11"),
        ("x__Geschwindigkeitsueberwachung_Koeln_Gesamt_2024.csv", None),
    ],
)
def test_typ_aus_name(name, typ):
    assert koeln.typ_aus_name(name) == typ
