// SPDX-License-Identifier: AGPL-3.0-or-later
// methode.js — REIN: Inhalt von „Methode & Quellen“ aus dem Manifest (Quellen, Lizenzen,
// Verortung samt Gegenprobe). Quellenangaben nie hier eintragen – sie kommen aus
// pipeline/config/sources.yaml über manifest.json.

import * as D from "./daten.js";
import { esc } from "./popup.js";

const MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

function monat(iso) {
  return iso ? `${MONATE[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}` : "";
}

/** Städte mit eigenem Text (Berlin, Aachen); alle anderen beschreibt `stadtAbschnitt` aus dem
 * Manifest (Text in sources.yaml: `kontrollen.hinweis`). */
const EIGEN = ["berlin", "aachen"];

/** Abschnitt einer Stadt aus dem Manifest: Quelle, Lizenz, Hinweis – und bei Städten, die nur
 * Verstöße nennen (Köln, Bonn), was dort eine „Kontrolle“ ist. */
function stadtAbschnitt(s) {
  if (!s?.kontrollen) return "";
  const q = s.quelle;
  const nurVerstoesse = s.anteil_alle_gezaehlt === 0;
  const lizenz = q.lizenz || q.lizenz_hinweis;
  return `
    <h3>${esc(s.label)} ${esc(monat(s.zeitraum?.[0]))} bis ${esc(monat(s.zeitraum?.[1]))}</h3>
    <p>${D.zahl(s.kontrollen)} Kontrollen ${nurVerstoesse ? "aus den einzelnen Verstößen der" : "der"} ${esc(q.bereitsteller)}
    (<a href="${esc(q.herkunft_url)}" target="_blank" rel="noopener">${esc(q.titel || "Quelle")}</a>${lizenz ? `, ${esc(lizenz)}` : ""}).
    ${q.hinweis ? esc(q.hinweis) : ""}</p>
    ${
      nurVerstoesse
        ? `<ul>
      <li>Eine <b>Kontrolle</b> ist hier: alle Verstöße eines Standorts an einem Tag. Wann und wie
      lange gemessen wurde, steht nicht in den Daten.</li>
      <li>Gezählt sind nur die <b>Verstöße</b>, nicht alle gemessenen Fahrzeuge – einen Anteil gibt
      es darum nicht; „je Kontrolle“ geht.</li>
    </ul>`
        : ""
    }`;
}

export function methodeHtml(m) {
  const b = m.staedte.berlin;
  const a = m.staedte.aachen;
  const zeile = (s) => {
    const v = s.verortung;
    if (!v) return "";
    const je = v.je_methode;
    const n = v.kontrollen;
    const pz = (x) => `${D.zahl((100 * x) / n, 1)} %`;
    return `<table>${m.methoden
      .filter((k) => je[k] > 0)
      .map((k) => `<tr><td>${esc(D.METHODEN_TEXT[k])}</td><td>${D.zahl(je[k])}</td><td>${pz(je[k])}</td></tr>`)
      .join("")}${v.ohne_lage ? `<tr><td>ohne Lage (nicht auf der Karte)</td><td>${D.zahl(v.ohne_lage)}</td><td>${pz(v.ohne_lage)}</td></tr>` : ""}</table>`;
  };
  const probe = b.verortung?.hausnummer_gegen_abschnitt;
  return `
    <p>Jeder Kreis ist eine <b>Messstelle</b>: Kontrollen, die an derselben Stelle derselben Straße
    liegen. Farbe und Größe rechnet die Karte aus den Kontrollen, die zum Filter passen.</p>

    <h3>Berlin ${esc(monat(b.zeitraum?.[0]))} bis ${esc(monat(b.zeitraum?.[1]))}</h3>
    <p>${D.zahl(b.kontrollen)} temporäre Kontrollen der ${esc(b.quelle.bereitsteller)}
    (${esc(b.quelle.titel)}, <a href="${esc(b.quelle.herkunft_url)}" target="_blank" rel="noopener">FragDenStaat</a>;
    ${esc(b.quelle.lizenz || b.quelle.lizenz_hinweis || "ohne Lizenzangabe")}). Je Kontrolle: Straße,
    Hausnummer, „zwischen A u. B“ oder Kreuzung, Bezirk, Fahrtrichtung, Tempolimit, Beginn und
    Ende, gemessene Fahrzeuge, Überschreitungen (bis/über 20 km/h), Fahrverbote.</p>
    <ul>
      <li>Geliefert hat die Polizei je Jahr eine Tabelle als PDF; die Karte liest sie Zeile für
      Zeile. „-“ heißt dort keine Angabe und bleibt leer; ein wechselndes Tempolimit („50/30“)
      steht ohne Tempo.</li>
      <li>Bei ${D.zahl(100 - 100 * b.anteil_alle_gezaehlt, 0)} % der Kontrollen sind <b>Messungen und
      Überschreitungen gleich</b> – erfasst wurden dort nur die zu schnellen Fahrzeuge (vor allem
      Autobahn). Einen Anteil gibt es für diese Kontrollen nicht; „je Stunde“ geht immer.</li>
      <li>„bis 20“ und „über 20 km/h“ ergeben zusammen oft weniger als alle Überschreitungen; die
      Polizei erklärt die Spalten nicht. Die Karte zeigt sie, wie geliefert.</li>
    </ul>

    <h3>Aachen ${esc(monat(a.zeitraum?.[0]))} bis ${esc(monat(a.zeitraum?.[1]))}</h3>
    <p>${D.zahl(a.kontrollen)} Kontrollen der Stadt Aachen (Open Data, ${esc(a.quelle.lizenz || "")}).
    Das Portal hält je Jahr nur die <b>letzten drei Monate</b> bereit; darum fehlen Januar bis
    September der Jahre bis 2025. Der Juni 2020 stammt aus der früheren Karte. Aachen nennt je
    Kontrolle Tag, Straße, Fahrtrichtung, Fahrzeuge und Verstöße – keine Uhrzeit, keine Dauer,
    kein Tempolimit und keine Stelle auf der Straße.</p>

    ${Object.entries(m.staedte)
      .filter(([code]) => !EIGEN.includes(code))
      .map(([, s]) => stadtAbschnitt(s))
      .join("")}

    <h3>Verortung</h3>
    <p>Gesucht wird im Straßennetz von OpenStreetMap (Geofabrik-Abzug), für Berlin im genannten
    Bezirk, für Köln im genannten Stadtteil, für Butzbach im genannten Ortsteil und seiner Kommune
    (Bundes-, Landes- und Kreisstraßen auch über ihre Nummer): zuerst die <b>Hausnummer</b> an der Straße, sonst die Mitte des <b>Abschnitts</b>
    zwischen den beiden Querstraßen, sonst die <b>Kreuzung</b> oder <b>Anschlussstelle</b>.
    Bleibt nur der Straßenname, steht der Kreis blass (≈) in der Mitte der Straße, und die
    gestrichelte Linie zeigt die ganze Straße.</p>
    <p><b>Berlin</b></p>${zeile(b)}
    ${probe ? `<p>Gegenprobe: Wo Hausnummer und Querstraßen vorliegen (${D.zahl(probe.n)} Kontrollen), liegt der
    Hausnummer-Punkt bei ${D.zahl(100 * probe.unter_50m, 1)} % höchstens 50 m neben dem Abschnitt
    (Median ${D.zahl(probe.median_m, 0)} m).</p>` : ""}
    <p><b>Aachen</b> – nur der Straßenname ist bekannt:</p>${zeile(a)}
    ${Object.entries(m.staedte)
      .filter(([c, s]) => !EIGEN.includes(c) && s.kontrollen)
      .map(([, s]) => `<p><b>${esc(s.label)}</b></p>${zeile(s)}`)
      .join("")}
    ${m.staedte.koeln?.kontrollen ? `<p>Nennt Köln statt einer Hausnummer eine Laterne („Laterne 85-77“), bleibt es bei der
    Straße – Laternennummern stehen nicht in OpenStreetMap.</p>` : ""}

    <h3>Daten</h3>
    <p><a href="pipeline/data/karte/${esc(m.dateien.csv)}" download>Alle Kontrollen als CSV</a> (mit
    Koordinaten und Verortung) · Stand ${esc(m.stand)} ·
    <a href="https://github.com/vizsim-lab/geschwindigkeitskontrollen" target="_blank" rel="noopener">Quellcode und Methode</a></p>
    <p>Straßennetz und Adressen: ${esc(m.osm.bereitsteller)}, ${esc(m.osm.lizenz)}. Hintergrund:
    ${esc(m.karte.hintergrund)}. Suche: ${esc(m.karte.suche)}.</p>`;
}
