# SPDX-License-Identifier: AGPL-3.0-or-later
"""Text und Tabellen aus Berichten der Gemeinden: PDF (pdfplumber) und Word (.docx, ohne
zusätzliche Bibliothek – das XML im Archiv).

Ein Word-Absatz wird eine Zeile, wie `extract_text` eine PDF-Zeile liefert; Zeilenumbrüche
mitten im Absatz (`<w:br/>`) ebenso.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pdfplumber

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def text(pfad: Path) -> str:
    """Der ganze Text eines PDF- oder Word-Dokuments, Zeile für Zeile."""
    if pfad.suffix.lower() == ".docx":
        return docx_text(pfad)
    with pdfplumber.open(pfad) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def docx_text(pfad: Path) -> str:
    with zipfile.ZipFile(pfad) as z:
        wurzel = ElementTree.fromstring(z.read("word/document.xml"))
    zeilen = []
    for absatz in wurzel.iter(W + "p"):
        teile = []
        for el in absatz.iter():
            if el.tag == W + "t" and el.text:
                teile.append(el.text)
            elif el.tag in (W + "br", W + "cr"):
                teile.append("\n")
            elif el.tag == W + "tab":
                teile.append(" ")
        zeilen.append("".join(teile))
    return "\n".join(zeilen)


def tabellen(pfad: Path) -> list[list[str | None]]:
    """Alle Tabellenzeilen eines PDF (Seite für Seite)."""
    with pdfplumber.open(pfad) as pdf:
        return [z for p in pdf.pages for t in p.extract_tables() for z in t]


def glaette(s: str | None) -> str:
    """Leerraum und Zeilenumbrüche einer Zelle zu einzelnen Leerzeichen; Trennstriche am
    Zeilenende („Geschwindig-\\nkeit“) zusammen."""
    t = re.sub(r"(?<=[a-zäöüß])-\n(?=[a-zäöüß])", "", str(s or ""))
    return " ".join(t.split())
