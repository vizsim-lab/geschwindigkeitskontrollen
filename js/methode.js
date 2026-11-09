// SPDX-License-Identifier: AGPL-3.0-or-later
// methode.js — REIN: Inhalt von „Methode & Quellen“ aus dem Manifest (Quellen, Lizenzen,
// Verortung samt Gegenprobe). Quellenangaben nie hier eintragen – sie kommen aus
// pipeline/config/sources.yaml über manifest.json.

import * as D from "./daten.js";
import { esc } from "./popup.js";

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
      .map((k) => `<tr><td>${esc(D.METHODEN_TEXT[k])}</td><td>${D.zahl(je[k])}</td><td>${pz(je[k])}</td></tr>`)
      .join("")}<tr><td>ohne Lage (nicht auf der Karte)</td><td>${D.zahl(v.ohne_lage)}</td><td>${pz(v.ohne_lage)}</td></tr></table>`;
  };
  const probe = b.verortung?.hausnummer_gegen_abschnitt;
  return `
    <p>Jeder Kreis ist eine <b>Messstelle</b>: Kontrollen, die an derselben Stelle derselben Straße
    liegen. Farbe und Größe rechnet die Karte aus den Kontrollen, die zum Filter passen.</p>

    <h3>Berlin ${esc(b.zeitraum?.[0]?.slice(0, 4) ?? "")}–${esc(b.zeitraum?.[1]?.slice(0, 4) ?? "")}</h3>
    <p>${D.zahl(b.kontrollen)} temporäre Kontrollen der ${esc(b.quelle.bereitsteller)}
    (${esc(b.quelle.titel)}, <a href="${esc(b.quelle.herkunft_url)}" target="_blank" rel="noopener">FragDenStaat</a>;
    ${esc(b.quelle.lizenz || b.quelle.lizenz_hinweis || "ohne Lizenzangabe")}). Je Kontrolle: Straße,
    Hausnummer, „zwischen A u. B“ oder Kreuzung, Bezirk, Fahrtrichtung, Tempolimit, Beginn und
    Ende, gemessene Fahrzeuge, Überschreitungen (bis/über 20 km/h), Fahrverbote.</p>
    <ul>
      <li>Bei ${D.zahl(100 - 100 * b.anteil_alle_gezaehlt, 0)} % der Kontrollen sind <b>Messungen und
      Überschreitungen gleich</b> – erfasst wurden dort nur die zu schnellen Fahrzeuge (vor allem
      Autobahn). Einen Anteil gibt es für diese Kontrollen nicht; „je Stunde“ geht immer.</li>
      <li>„bis 20“ und „über 20 km/h“ ergeben zusammen oft weniger als alle Überschreitungen; die
      Polizei erklärt die Spalten nicht. Die Karte zeigt sie, wie geliefert.</li>
    </ul>

    <h3>Aachen ${esc(a.zeitraum?.[0]?.slice(0, 7) ?? "")} bis ${esc(a.zeitraum?.[1]?.slice(0, 7) ?? "")}</h3>
    <p>${D.zahl(a.kontrollen)} Kontrollen der Stadt Aachen (Open Data, ${esc(a.quelle.lizenz || "")}).
    Das Portal hält je Jahr nur die <b>letzten drei Monate</b> bereit; darum fehlen Januar bis
    September der Jahre bis 2025. Der Juni 2020 stammt aus der früheren Karte. Aachen nennt je
    Kontrolle Tag, Straße, Fahrtrichtung, Fahrzeuge und Verstöße – keine Uhrzeit, keine Dauer,
    kein Tempolimit und keine Stelle auf der Straße.</p>

    <h3>Verortung</h3>
    <p>Gesucht wird im Straßennetz von OpenStreetMap (Geofabrik-Abzug), für Berlin im genannten
    Bezirk: zuerst die <b>Hausnummer</b> an der Straße, sonst die Mitte des <b>Abschnitts</b>
    zwischen den beiden Querstraßen, sonst die <b>Kreuzung</b> oder <b>Anschlussstelle</b>.
    Bleibt nur der Straßenname, steht der Kreis blass (≈) in der Mitte der Straße, und die
    gestrichelte Linie zeigt die ganze Straße.</p>
    <p><b>Berlin</b></p>${zeile(b)}
    ${probe ? `<p>Gegenprobe: Wo Hausnummer und Querstraßen vorliegen (${D.zahl(probe.n)} Kontrollen), liegt der
    Hausnummer-Punkt bei ${D.zahl(100 * probe.unter_50m, 0)} % höchstens 50 m neben dem Abschnitt
    (Median ${D.zahl(probe.median_m, 0)} m).</p>` : ""}
    <p><b>Aachen</b> – nur der Straßenname ist bekannt:</p>${zeile(a)}

    <h3>Daten</h3>
    <p><a href="pipeline/data/karte/${esc(m.dateien.csv)}" download>Alle Kontrollen als CSV</a> (mit
    Koordinaten und Verortung) · Stand ${esc(m.stand)} ·
    <a href="https://github.com/vizsim-lab/geschwindigkeitskontrollen" target="_blank" rel="noopener">Quellcode und Methode</a></p>
    <p>Straßennetz und Adressen: ${esc(m.osm.bereitsteller)}, ${esc(m.osm.lizenz)}. Hintergrund:
    ${esc(m.karte.hintergrund)}. Suche: ${esc(m.karte.suche)}.</p>`;
}
