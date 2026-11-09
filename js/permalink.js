// SPDX-License-Identifier: AGPL-3.0-or-later
// permalink.js — REIN (kein DOM, kein window): Kartenzustand <-> Link-Anker.
//
// Format: #<zoom>/<lat>/<lon>&m=<metrik>&j=<jahre>&t=<tempo>&v=<verortung>
//   m: anteil | stunde | fahrverbote | kontrollen (fehlt = anteil)
//   j: Jahre, Komma-getrennt (fehlt = alle)
//   t: Tempoklassen 30,50,80,100,u (fehlt = alle)
//   v: Verortung h,a,k,s,x = hausnummer, abschnitt, kreuzung, anschlussstelle, strasse
//      (fehlt = alle)
//   s: Messstelle mit offenem Fenster (ihre id, z. B. B01234)
//   d: Ebene „Datenlage je Stadt“ an (d=1; fehlt = aus)
// Die Kürzel sind ein Vertrag mit geteilten Links: nie umdeuten, nur ergänzen.

export const VERORTUNG_KUERZEL = {
  h: "hausnummer",
  a: "abschnitt",
  k: "kreuzung",
  s: "anschlussstelle",
  x: "strasse",
};
const KUERZEL_VON = Object.fromEntries(Object.entries(VERORTUNG_KUERZEL).map(([k, v]) => [v, k]));
const METRIKEN = ["anteil", "stunde", "fahrverbote", "kontrollen"];
const TEMPO = ["30", "50", "80", "100", "u"];

/** Zustand -> Anker (ohne „#“). Mengen als Set oder null (= alle). */
export function schreibe(z) {
  const teile = [`${z.zoom.toFixed(2)}/${z.lat.toFixed(5)}/${z.lon.toFixed(5)}`];
  if (z.metrik && z.metrik !== "anteil") teile.push(`m=${z.metrik}`);
  if (z.jahre) teile.push(`j=${[...z.jahre].sort((a, b) => a - b).join(",")}`);
  if (z.tempo) teile.push(`t=${TEMPO.filter((t) => z.tempo.has(t)).join(",")}`);
  if (z.methoden) teile.push(`v=${[...z.methoden].map((m) => KUERZEL_VON[m]).filter(Boolean).sort().join(",")}`);
  if (z.stelle) teile.push(`s=${encodeURIComponent(z.stelle)}`);
  if (z.datenlage) teile.push("d=1");
  return teile.join("&");
}

/** Anker -> Zustand; Unbekanntes wird ignoriert, fehlende Teile bleiben undefined. */
export function lies(anker) {
  const s = String(anker || "").replace(/^#/, "");
  const out = {};
  const [ansicht, ...rest] = s.split("&");
  const z = ansicht.split("/").map(Number);
  if (z.length === 3 && z.every(Number.isFinite) && Math.abs(z[1]) <= 90 && Math.abs(z[2]) <= 180) {
    [out.zoom, out.lat, out.lon] = z;
  }
  for (const teil of rest) {
    const [k, v = ""] = teil.split("=");
    const werte = v.split(",").filter(Boolean);
    if (k === "m" && METRIKEN.includes(v)) out.metrik = v;
    if (k === "j") out.jahre = new Set(werte.map(Number).filter(Number.isInteger));
    if (k === "t") out.tempo = new Set(werte.filter((t) => TEMPO.includes(t)));
    if (k === "v") out.methoden = new Set(werte.map((w) => VERORTUNG_KUERZEL[w]).filter(Boolean));
    if (k === "s" && v) out.stelle = decodeURIComponent(v);
    if (k === "d") out.datenlage = v === "1";
  }
  return out;
}
