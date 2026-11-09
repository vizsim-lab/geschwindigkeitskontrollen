// SPDX-License-Identifier: AGPL-3.0-or-later
// popup.js — REIN (liefert HTML-Text, kein DOM): Fenster einer Messstelle.
// Alles aus den Daten geht durch esc() – Straßennamen kommen aus Polizeidaten und OSM.

import * as D from "./daten.js";

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

const MAX_ZEILEN = 60;

/**
 * Fenster einer Messstelle. `voll`: mit Liste der Kontrollen (angeheftetes Fenster), sonst die
 * kurze Vorschau beim Überfahren.
 */
export function stelleHtml({ daten, stelle, agg, metrik, filter, manifest, voll }) {
  const stadt = manifest.staedte[stelle.stadtCode];
  const w = D.wert(agg, metrik);
  const k = D.klasse(w, metrik);
  const farbe = k < 0 ? D.GRAU : D.FARBEN[k];
  const m = D.METRIKEN[metrik];
  const zeitraum = agg.tagMin <= agg.tagMax ? jahreText(daten, agg) : "";
  const zeilen = [
    ["Kontrollen", `${D.zahl(agg.n)}${zeitraum ? ` <span class="pop-meta">(${zeitraum})</span>` : ""}`],
    ["Gemessen", `${D.zahl(agg.mess)} Fahrzeuge`],
    ["Zu schnell", D.zahl(agg.ueber)],
  ];
  if (agg.s1 || agg.s2) {
    const grenzen = new Set(D.kontrollenDerStelle(daten, stelle.i, filter).filter((x) => x.imFilter && x.grenze).map((x) => x.grenze));
    const kmh = grenzen.size === 1 ? [...grenzen][0] : null;
    zeilen.push([kmh ? `bis/über ${kmh} km/h` : "bis/über Grenze", `${D.zahl(agg.s1)} / ${D.zahl(agg.s2)}`]);
  }
  if (agg.fvBekannt) zeilen.push(["Fahrverbote", D.zahl(agg.fv)]);
  if (agg.minuten) {
    zeilen.push(["Messdauer", D.dauerText(agg.minuten)]);
    zeilen.push(["Zu schnell je Stunde", D.zahl(agg.ueberMitDauer / (agg.minuten / 60), 0)]);
  }
  if (agg.messAlle !== agg.mess && agg.mess) {
    zeilen.push([
      "Anteil",
      agg.messAlle
        ? `${D.zahl((100 * agg.ueberAlle) / agg.messAlle, 1)} % <span class="pop-meta">(nur Kontrollen mit allen Fahrzeugen)</span>`
        : `– <span class="pop-meta">(nur zu schnelle erfasst)</span>`,
    ]);
  }

  const chips = [
    `<span class="pop-chip${stelle.genau ? "" : " is-grob"}" title="Wie die Stelle verortet ist">${esc(D.METHODEN_TEXT[stelle.methodeCode])}</span>`,
  ];
  if (stelle.osm_maxspeed) {
    chips.push(`<span class="pop-chip" title="Tempolimit laut OpenStreetMap heute – nicht unbedingt das zur Zeit der Kontrolle">OSM heute: ${esc(stelle.osm_maxspeed)}</span>`);
  }

  let html = `
    <div class="pop-eyebrow">Messstelle · ${esc(stadt.label)}</div>
    <div class="pop-title">${esc(stelle.strasse || "–")}</div>
    ${stelle.lage ? `<div class="pop-meta">${esc(stelle.lage)}</div>` : ""}
    <div class="pop-hero"><span class="pop-punkt" style="background:${farbe}"></span>${esc(D.wertText(w, metrik))}<span class="pop-unit">${metrik === "anteil" && w != null ? "zu schnell" : ""}${w == null ? esc(m.kurz) + " – kein Wert" : ""}</span></div>
    <table class="pop-table">${zeilen.map(([a, b]) => `<tr><td>${esc(a)}</td><td>${b}</td></tr>`).join("")}</table>
    <div class="pop-chips">${chips.join("")}</div>
    ${stelle.hinweis ? `<div class="pop-hinweis">${esc(stelle.hinweis)}</div>` : ""}`;

  if (!voll) return html + '<div class="pop-pinhint">Klick zeigt alle Kontrollen</div>';

  const liste = D.kontrollenDerStelle(daten, stelle.i, filter);
  const mitZeit = liste.some((x) => x.beginn != null);
  const mitTempo = liste.some((x) => x.tempo != null);
  const mitFv = liste.some((x) => x.fahrverbote != null);
  const kopf = [
    "<th>Datum</th>",
    mitZeit ? '<th class="zeit">Zeit</th>' : "",
    "<th>Richtung</th>",
    mitTempo ? '<th class="rechts">km/h</th>' : "",
    '<th class="rechts">Fzg.</th>',
    '<th class="rechts">zu schnell</th>',
    mitFv ? '<th class="rechts">FV</th>' : "",
  ].join("");
  const reihen = liste.slice(0, MAX_ZEILEN).map((x) => {
    const anteil = x.alle === 1 && x.messungen > 0 ? ` <span class="pop-meta">${D.zahl((100 * (x.ueber ?? 0)) / x.messungen, 0)} %</span>` : "";
    const zeit = x.beginn != null ? `${D.uhrzeit(x.beginn)}${x.dauer ? `–${D.uhrzeit(x.beginn + x.dauer)}` : ""}` : "";
    return `<tr class="${x.imFilter ? "" : "ausser-filter"}">
      <td>${D.datumText(x.datum)}</td>
      ${mitZeit ? `<td class="zeit">${zeit}</td>` : ""}
      <td class="richtung">${esc(daten.richtungen[x.richtung] || "–")}</td>
      ${mitTempo ? `<td class="rechts">${x.tempo ?? "–"}</td>` : ""}
      <td class="rechts">${D.zahl(x.messungen)}</td>
      <td class="rechts">${D.zahl(x.ueber)}${anteil}</td>
      ${mitFv ? `<td class="rechts">${x.fahrverbote ?? "–"}</td>` : ""}
    </tr>`;
  });
  const ausser = liste.filter((x) => !x.imFilter).length;
  html += `
    <div class="pop-liste">
      <h3>${liste.length === 1 ? "Die Kontrolle" : `Alle ${D.zahl(liste.length)} Kontrollen`}${ausser ? ` <span class="pop-meta">(${ausser} außerhalb des Filters, grau)</span>` : ""}</h3>
      <div class="pop-tabelle"><table><thead><tr>${kopf}</tr></thead><tbody>${reihen.join("")}</tbody></table></div>
      ${liste.length > MAX_ZEILEN ? `<div class="pop-mehr">… und ${D.zahl(liste.length - MAX_ZEILEN)} weitere (alle in der CSV)</div>` : ""}
    </div>
    <div class="pop-foot">
      <a href="https://www.openstreetmap.org/?mlat=${stelle.lat}&mlon=${stelle.lon}#map=18/${stelle.lat}/${stelle.lon}" target="_blank" rel="noopener">In OSM ansehen</a>
      <a href="#" data-aktion="link">Link zur Stelle kopieren</a>
    </div>`;
  return html;
}

function jahreText(daten, agg) {
  const t0 = Date.parse(daten.tag0 + "T00:00:00Z");
  const a = new Date(t0 + agg.tagMin * 86400000).getUTCFullYear();
  const b = new Date(t0 + agg.tagMax * 86400000).getUTCFullYear();
  return a === b ? String(a) : `${a}–${b}`;
}
