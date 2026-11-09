# SPDX-License-Identifier: AGPL-3.0-or-later
"""CSV der Portale: Kodierung, Trenner, Spaltennamen, gzip, Stücke."""

import gzip

import pytest

from kontrollen import tabellen


def test_cp1252_semikolon_und_namen(tmp_path):
    p = tmp_path / "a.csv"
    p.write_bytes(
        "Stadtteil;Tatstraße mit Hausnummer;Erlaubte Geschw. PKW\nSülz;Berrenrather Str. 179;30\n".encode(
            "cp1252"
        )
    )
    assert tabellen.kodierung(p) == "cp1252"
    assert tabellen.trenner(p) == ";"
    df = tabellen.lies(p)
    assert list(df.columns) == ["stadtteil", "tatstrassemithausnummer", "erlaubtegeschwpkw"]
    assert df.iloc[0].tolist() == ["Sülz", "Berrenrather Str. 179", "30"]


def test_gzip_und_stuecke(tmp_path):
    p = tmp_path / "v.csv.gz"
    zeilen = ["Jahr;vorfallsdatum;vorfallsuhrzeit;dienststelle"] + [
        f"2019;10119; 335;S-0{i % 3}" for i in range(7)
    ]
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")
    teile = list(tabellen.stuecke(p, ["vorfallsuhrzeit", "dienststelle"], groesse=3))
    assert [len(t) for t in teile] == [3, 3, 1]
    assert list(teile[0].columns) == ["vorfallsuhrzeit", "dienststelle"]
    assert teile[0].iloc[0, 0] == " 335"  # Text bleibt Text


def test_fehlende_spalte(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Spalten fehlen"):
        list(tabellen.stuecke(p, ["c"]))


def test_zeilen_ohne_kopf_und_ungleich_lang(tmp_path):
    f = tmp_path / "s02.csv"
    f.write_bytes(
        "0101;0;050;AA   Riehl ;Amsterdamer Str. 80-86;\r\n\r\n0102;6;010;Brück\r\n".encode(
            "cp1252"
        )
    )
    assert tabellen.zeilen(f) == [
        ["0101", "0", "050", "AA   Riehl ", "Amsterdamer Str. 80-86", ""],
        ["0102", "6", "010", "Brück"],
    ]
