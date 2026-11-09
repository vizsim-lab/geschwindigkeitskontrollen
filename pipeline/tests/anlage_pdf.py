# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ausgedachte Anlagen im Format der Polizei-PDFs – für die Tests von berlin_pdf und berlin.

Nachgebaut ist, worauf der Leser sich stützt: Spaltenlinien als dünne gefüllte Rechtecke nur
im Kopf der ersten Seite, gedrehte Spaltenköpfe, Text links- bzw. rechtsbündig in den Zellen,
Folgeseiten ohne Linien, leere Seiten am Ende. Raster und Schrift wie Anlage 3 (2019).
"""

from __future__ import annotations

from pathlib import Path

from pdfminer.fontmetrics import FONT_METRICS

from kontrollen.berlin_pdf import KOPF

GRENZEN = [51.0, 63.96, 77.76, 122.16, 135.12, 223.32, 299.76, 363.72, 378.48, 401.88,
           425.28, 448.68, 470.76, 487.2, 503.64, 527.76, 540.72]  # fmt: skip
LINKS = {"Straßenname", "zwischen", "Verwaltungsbezirk", "Richtung"}  # sonst rechtsbündig
GROESSE = 3.12
ABSTAND = 4.08
HOEHE = 842.0
KOPF_OBEN, KOPF_UNTEN = 40.0, 90.96
ROT = (1, 0, 0)
_BREITEN = FONT_METRICS["Helvetica"][1]


def zeile(*zellen: str) -> list[str]:
    """16 Zellen; fehlende am Ende sind leer."""
    z = list(zellen) + [""] * (len(KOPF) - len(zellen))
    assert len(z) == len(KOPF)
    return z


def _breite(text: str, groesse: float) -> float:
    return sum(_BREITEN.get(c, 556) for c in text) * groesse / 1000


def _str(text: str) -> str:
    out = []
    for b in text.encode("cp1252"):
        ch = chr(b)
        if ch in "\\()":
            out.append("\\" + ch)
        elif 32 <= b < 127:
            out.append(ch)
        else:
            out.append(f"\\{b:03o}")
    return "(" + "".join(out) + ")"


def _text(x, y, text, groesse=GROESSE, farbe=None, gedreht=False) -> str:
    m = f"0 1 -1 0 {x:.2f} {y:.2f}" if gedreht else f"1 0 0 1 {x:.2f} {y:.2f}"
    r, g, b = farbe or (0, 0, 0)
    return f"BT {r} {g} {b} rg /F1 {groesse} Tf {m} Tm {_str(text)} Tj ET"


def _zelle(spalte: int, text: str, y: float, groesse=GROESSE, farbe=None) -> str:
    links, rechts = GRENZEN[spalte], GRENZEN[spalte + 1]
    x = links + 0.36 if KOPF[spalte] in LINKS else rechts - 0.36 - _breite(text, groesse)
    return _text(x, y, text, groesse, farbe)


def seite(zeilen: list[list[str]], *, kopf: bool, nachtraege=(), fuss: str | None = None) -> str:
    """Inhaltsstrom einer Seite.

    nachtraege: (Zeile, Spalte, Text, Schriftgröße, Farbe, dy) – etwa eine rote Korrektur in
    größerer Schrift, um dy nach oben versetzt. fuss: roter Text unter der letzten Zeile."""
    ops = []
    if kopf:
        h = KOPF_UNTEN - KOPF_OBEN
        for x in GRENZEN:
            ops.append(f"0 0 0 rg {x - 0.12:.2f} {HOEHE - KOPF_UNTEN:.2f} 0.24 {h:.2f} re f")
        for t in (KOPF_OBEN, KOPF_UNTEN):
            ops.append(f"{GRENZEN[0]:.2f} {HOEHE - t:.2f} {GRENZEN[-1] - GRENZEN[0]:.2f} 0.24 re f")
        for i, name in enumerate(KOPF):
            mitte = (GRENZEN[i] + GRENZEN[i + 1]) / 2
            ops.append(_text(mitte + GROESSE / 2, HOEHE - KOPF_UNTEN + 2, name, gedreht=True))
        y0 = HOEHE - KOPF_UNTEN - 4
    else:
        y0 = HOEHE - 60
    for i, z in enumerate(zeilen):
        for s, text in enumerate(z):
            if text:
                ops.append(_zelle(s, text, y0 - i * ABSTAND))
    for i, s, text, groesse, farbe, dy in nachtraege:
        ops.append(_zelle(s, text, y0 - i * ABSTAND + dy, groesse, farbe))
    if fuss:
        ops.append(_text(GRENZEN[2] + 0.36, y0 - len(zeilen) * ABSTAND, fuss, farbe=ROT))
    return "\n".join(ops)


def schreibe(pfad: Path, seiten: list[str]) -> Path:
    """Minimales PDF (Helvetica, WinAnsi) aus fertigen Inhaltsströmen; "" = leere Seite."""
    n = len(seiten)
    objekte: list = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(n))}] /Count {n} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i, inhalt in enumerate(seiten):
        objekte.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>"
        )
        objekte.append(inhalt.encode("latin-1"))
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for nr, obj in enumerate(objekte, start=1):
        offsets.append(len(out))
        if isinstance(obj, bytes):
            out += f"{nr} 0 obj\n<< /Length {len(obj)} >>\nstream\n".encode()
            out += obj + b"\nendstream\nendobj\n"
        else:
            out += f"{nr} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objekte) + 1}\n0000000000 65535 f \n".encode()
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objekte) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(bytes(out))
    return pfad


def anlage(
    pfad: Path, zeilen: list[list[str]], *, pro_seite: int = 40, nachtraege=(), fuss=None
) -> Path:
    """Anlage mit Kopf auf Seite 1, Folgeseiten ohne Linien und einer leeren Seite am Ende.
    Nachträge stehen auf Seite 1, der Fuß unter der letzten Zeile."""
    starts = list(range(0, max(len(zeilen), 1), pro_seite))
    seiten = [
        seite(
            zeilen[i : i + pro_seite],
            kopf=(i == 0),
            nachtraege=nachtraege if i == 0 else (),
            fuss=fuss if i == starts[-1] else None,
        )
        for i in starts
    ]
    seiten.append("")
    return schreibe(pfad, seiten)
