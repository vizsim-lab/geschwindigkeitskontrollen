// SPDX-License-Identifier: AGPL-3.0-or-later
// datenlage.js — REIN (kein DOM, kein window): Ebene „Datenlage je Stadt“ – Farbklassen,
// Legende und Fenster einer Stadt. Muster aus vizsim-lab/zaehlkarte (gleiche Klassen und
// Farben, damit beide Karten dieselbe Sprache sprechen).
//
// Daten: datenlage.json (GeoJSON, gebaut von `kontrollen site` aus `datenlage` in
// pipeline/config/sources.yaml), die Texte der Stände aus manifest.datenlage_stand.

import { esc } from "./popup.js";
import { zahl } from "./daten.js";

export const GRAU = "#9ca3af";
export const KLASSEN = [
  { id: "in_karte", name: "in der Karte", farbe: "#2a78d6", stand: ["in_karte"] },
  { id: "offen", name: "offen oder auf Anfrage herausgegeben", farbe: "#1baf7a", stand: ["offen", "geliefert"] },
  { id: "kandidat", name: "erhoben – Anfrage aussichtsreich", farbe: "#eb6834", stand: ["kandidat"] },
  { id: "sonst", name: "nur Summen, Standorte oder abgelehnt", farbe: GRAU, stand: ["teilweise", "abgelehnt"] },
];
export const MELDEN = "https://github.com/vizsim-lab/geschwindigkeitskontrollen/issues/new?template=daten-melden.yml";

/** Klasse eines Stands; Unbekanntes landet bei „sonst“. */
export function klasse(stand) {
  return KLASSEN.find((k) => k.stand.includes(stand)) ?? KLASSEN[KLASSEN.length - 1];
}

/** MapLibre-Ausdruck für die Kreisfarbe nach `stand`. */
export function farbAusdruck() {
  return ["match", ["get", "stand"], ...KLASSEN.flatMap((k) => k.stand.flatMap((s) => [s, k.farbe])), GRAU];
}

/** Städte je Klasse. */
export function zaehle(fc) {
  const n = Object.fromEntries(KLASSEN.map((k) => [k.id, 0]));
  for (const f of fc?.features ?? []) n[klasse(f.properties.stand).id] += 1;
  return n;
}

/** Legende: eine Zeile je Klasse, mit der Zahl der Städte. */
export function legendeHtml(fc) {
  const n = zaehle(fc);
  return KLASSEN.map(
    (k) =>
      `<li><span class="punkt" style="background:${k.farbe}"></span><span class="text">${esc(k.name)}</span><span class="count-badge">${zahl(n[k.id])}</span></li>`
  ).join("");
}

/** Fenster einer Stadt (Eigenschaften eines Features aus datenlage.json). */
export function detailHtml(p, standTexte = {}) {
  const k = p.kontakt;
  const a = p.anfrage;
  const links = (p.links ?? []).map((l) => `<li><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.titel)}</a></li>`).join("");
  const teile = [
    `<header class="detail-kopf">
      <div><div class="pop-eyebrow">Datenlage${p.land ? ` · ${esc(p.land)}` : ""}</div>
      <h2 class="detail-titel">${esc(p.kommune)}</h2>
      <div class="pop-meta"><span class="dl-punkt" style="background:${klasse(p.stand).farbe}"></span>${esc(standTexte[p.stand] ?? p.stand)}</div></div>
      <button class="detail-zu" type="button" data-schliessen aria-label="Schließen">×</button>
    </header>`,
  ];
  if (p.kontrollen) {
    teile.push(`<p class="detail-text">${esc(p.was ?? "")}</p>
      <p class="detail-text"><button type="button" class="link-knopf" data-hinzoomen>${zahl(p.kontrollen)} Kontrollen in der Karte – hinzoomen</button></p>`);
  }
  if (p.situation) teile.push(`<div class="detail-abschnitt">Lage</div><p class="detail-text">${esc(p.situation)}</p>`);
  else if (!p.kontrollen) teile.push(`<p class="detail-text">${esc(p.was ?? "")}</p>`);
  if (p.empfehlung) teile.push(`<div class="detail-abschnitt">Empfehlung</div><p class="detail-text">${esc(p.empfehlung)}</p>`);
  if (p.weg) teile.push(`<p class="detail-text"><span class="pop-chip">${esc(p.weg)}</span></p>`);
  if (k?.fds) {
    teile.push(`<div class="detail-abschnitt">Kontakt</div><p class="detail-text">${k.name ? `${esc(k.name)}<br>` : ""}<a href="${esc(k.fds)}" target="_blank" rel="noopener">${k.fds_suche ? "Behörde auf FragDenStaat suchen" : "Behörde auf FragDenStaat"} →</a></p>`);
  }
  if (a) {
    teile.push(`<div class="detail-abschnitt">Anfragetext</div>
      <p class="pop-meta">Für das Feld „Anfrage“ auf FragDenStaat – Anrede, Rechtsgrundlage und Gebührenhinweis ergänzt FragDenStaat. Betreff: ${esc(a.betreff)}</p>
      <textarea class="anfrage-text" readonly rows="9" aria-label="Anfragetext">${esc(a.text)}</textarea>
      <p class="detail-links"><button type="button" class="link-knopf" data-kopieren>Text kopieren</button>
      ${k?.fds ? `<a href="${esc(k.fds)}" target="_blank" rel="noopener">Auf FragDenStaat stellen →</a>` : ""}</p>`);
  }
  if (p.recht) teile.push(`<div class="detail-abschnitt">Rechtslage im Land</div><p class="detail-text">${esc(p.recht)}. Keine Rechtsberatung.</p>`);
  if (links) teile.push(`<div class="detail-abschnitt">Belege</div><ul class="detail-hinweise">${links}</ul>`);
  teile.push(`<div class="pop-foot"><a href="${MELDEN}" target="_blank" rel="noopener">Neues zu ${esc(p.kommune)} melden →</a></div>`);
  return teile.join("\n");
}
