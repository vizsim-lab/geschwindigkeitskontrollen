// SPDX-License-Identifier: AGPL-3.0-or-later
// daten.js — REIN (kein DOM, kein window): Kartendaten entpacken, filtern, zu Messstellen
// verdichten, Kennzahl und Farbklasse rechnen. Browserlos getestet (tests/unit/daten.test.js).
//
// Vertrag mit der Pipeline (pipeline/src/kontrollen/site.py): Feldnamen in messstellen.json
// und kontrollen.json (`felder`). Wer sie ändert, zieht beide Seiten im selben Schritt mit.

export const FARBEN = ["#1a9850", "#a6d96a", "#fee08b", "#fc8d59", "#d73027"];
export const GRAU = "#9ca3af";

// Kennzahlen je Messstelle. `grenzen`: Klassengrenzen (Wert < grenzen[i] -> Klasse i).
export const METRIKEN = {
  anteil: {
    label: "Anteil zu schnell",
    kurz: "zu schnell",
    einheit: "%",
    grenzen: [2, 5, 10, 20],
    hinweis:
      "Überschreitungen je gemessenem Fahrzeug – nur aus Kontrollen, bei denen alle Fahrzeuge gezählt wurden.",
  },
  stunde: {
    label: "Überschreitungen je Stunde",
    kurz: "je Stunde",
    einheit: "/h",
    grenzen: [10, 30, 60, 120],
    hinweis: "Überschreitungen geteilt durch die Messdauer – nur, wo die Dauer bekannt ist.",
  },
  jekontrolle: {
    label: "Überschreitungen je Kontrolle",
    kurz: "je Kontrolle",
    einheit: "",
    grenzen: [5, 10, 25, 60],
    hinweis:
      "Überschreitungen geteilt durch die Zahl der Kontrollen – geht in jeder Stadt, aber Kontrollen sind verschieden lang.",
  },
  fahrverbote: {
    label: "Fahrverbote",
    kurz: "Fahrverbote",
    einheit: "",
    grenzen: [1, 2, 6, 21],
    hinweis: "Summe der Fahrverbote aller Kontrollen der Stelle.",
  },
  kontrollen: {
    label: "Kontrollen",
    kurz: "Kontrollen",
    einheit: "",
    grenzen: [2, 4, 10, 30],
    hinweis: "Wie oft an der Stelle kontrolliert wurde.",
  },
};

export const TEMPO = [
  { id: "30", label: "bis 30", passt: (t) => t != null && t <= 30 },
  { id: "50", label: "40–50", passt: (t) => t != null && t > 30 && t <= 50 },
  { id: "80", label: "60–80", passt: (t) => t != null && t > 50 && t <= 80 },
  { id: "100", label: "ab 100", passt: (t) => t != null && t > 80 },
  { id: "u", label: "unbekannt", passt: (t) => t == null },
];

export const METHODEN_TEXT = {
  hausnummer: "Hausnummer",
  abschnitt: "Abschnitt zwischen zwei Querstraßen",
  kreuzung: "Kreuzung",
  anschlussstelle: "Anschlussstelle",
  strasse: "nur Straße (≈)",
};

/** Kontroll-Zeilen und Messstellen als Objekte; Jahr und Tempoklasse vorgerechnet. */
export function entpacke(stellenJson, kontrollenJson) {
  const fs = stellenJson.felder;
  const stellen = stellenJson.zeilen.map((z, i) => {
    const o = Object.fromEntries(fs.map((f, j) => [f, z[j]]));
    o.i = i;
    o.stadtCode = stellenJson.staedte[o.stadt];
    o.methodeCode = stellenJson.methoden[o.methode];
    o.genau = o.methodeCode !== "strasse";
    return o;
  });
  const fk = kontrollenJson.felder;
  const tag0 = Date.parse(kontrollenJson.tag0 + "T00:00:00Z");
  const kontrollen = kontrollenJson.zeilen.map((z) => {
    const o = Object.fromEntries(fk.map((f, j) => [f, z[j]]));
    o.datum = o.tag == null ? null : new Date(tag0 + o.tag * 86400000);
    o.jahr = o.datum ? o.datum.getUTCFullYear() : null;
    o.tempoKlasse = (TEMPO.find((t) => t.passt(o.tempo)) || TEMPO[4]).id;
    o.stadt = o.stelle == null ? null : stellen[o.stelle].stadtCode;
    return o;
  });
  return {
    stellen,
    kontrollen,
    staedte: stellenJson.staedte,
    methoden: stellenJson.methoden,
    richtungen: kontrollenJson.richtungen,
    orte: kontrollenJson.orte,
    tag0: kontrollenJson.tag0,
  };
}

/** Passt eine Kontrolle zum Filter? `filter.jahre`/`tempo`/`methoden`: Set oder null (= alle). */
export function passt(k, filter, daten) {
  if (k.stelle == null) return false;
  if (filter.jahre && !filter.jahre.has(k.jahr)) return false;
  if (filter.tempo && !filter.tempo.has(k.tempoKlasse)) return false;
  if (filter.methoden && !filter.methoden.has(daten.stellen[k.stelle].methodeCode)) return false;
  return true;
}

function leer() {
  return { n: 0, mess: 0, messBekannt: 0, ueber: 0, messAlle: 0, ueberAlle: 0, s1: 0, s2: 0, fv: 0, fvBekannt: 0, minuten: 0, ueberMitDauer: 0, tagMin: Infinity, tagMax: -Infinity };
}

/** Kontrollen -> je Messstelle die Summen (Map: Index der Messstelle -> Summen). */
export function verdichte(daten, filter) {
  const agg = new Map();
  for (const k of daten.kontrollen) {
    if (!passt(k, filter, daten)) continue;
    let a = agg.get(k.stelle);
    if (!a) agg.set(k.stelle, (a = leer()));
    a.n += 1;
    a.mess += k.messungen ?? 0;
    if (k.messungen != null) a.messBekannt += 1;
    a.ueber += k.ueber ?? 0;
    if (k.alle === 1 && k.messungen > 0) {
      a.messAlle += k.messungen;
      a.ueberAlle += k.ueber ?? 0;
    }
    a.s1 += k.stufe1 ?? 0;
    a.s2 += k.stufe2 ?? 0;
    if (k.fahrverbote != null) {
      a.fv += k.fahrverbote;
      a.fvBekannt += 1;
    }
    if (k.dauer > 0) {
      a.minuten += k.dauer;
      a.ueberMitDauer += k.ueber ?? 0;
    }
    if (k.tag != null) {
      a.tagMin = Math.min(a.tagMin, k.tag);
      a.tagMax = Math.max(a.tagMax, k.tag);
    }
  }
  return agg;
}

/** Kennzahl einer Messstelle; null, wenn sie sich aus den Daten nicht ergibt. */
export function wert(a, metrik) {
  switch (metrik) {
    case "anteil":
      return a.messAlle > 0 ? (100 * a.ueberAlle) / a.messAlle : null;
    case "stunde":
      return a.minuten > 0 ? a.ueberMitDauer / (a.minuten / 60) : null;
    case "jekontrolle":
      return a.n > 0 ? a.ueber / a.n : null;
    case "fahrverbote":
      return a.fvBekannt > 0 ? a.fv : null;
    case "kontrollen":
      return a.n;
    default:
      return null;
  }
}

/**
 * Hinweis unter „Farbe nach“ für die Stadt im Bild: der Text der Kennzahl und, was die Stadt
 * dazu (nicht) liefert – aus den Angaben im Manifest (`hat_dauer`, `hat_fahrverbote`,
 * `anteil_alle_gezaehlt`).
 */
/** Gibt die Kennzahl in dieser Stadt gar keinen Wert (alles grau)? */
export function ohneWert(metrik, stadt) {
  if (!stadt) return false;
  return (
    (metrik === "stunde" && !stadt.hat_dauer) ||
    (metrik === "fahrverbote" && stadt.hat_fahrverbote === false) ||
    (metrik === "anteil" && stadt.anteil_alle_gezaehlt === 0)
  );
}

export function metrikHinweis(metrik, stadt) {
  let h = METRIKEN[metrik].hinweis;
  if (!stadt) return h;
  if (metrik !== "anteil" && ohneWert(metrik, stadt)) return `${h} ${stadt.label} nennt das nicht – hier grau.`;
  if (metrik === "anteil") {
    const a = stadt.anteil_alle_gezaehlt;
    if (a === 0) h += ` ${stadt.label} nennt nur die Verstöße, nicht alle gemessenen Fahrzeuge – hier grau; „je Kontrolle“ geht.`;
    else if (a != null && a < 1) h += ` In ${stadt.label} sind bei ${zahl(100 - 100 * a)} % der Kontrollen nur die zu schnellen Fahrzeuge gezählt.`;
  }
  return h;
}

/** „Berlin“, „Berlin und Köln“, „Berlin, Köln und Bonn“. */
function aufzaehlung(namen) {
  return namen.length < 2 ? namen.join("") : `${namen.slice(0, -1).join(", ")} und ${namen[namen.length - 1]}`;
}

/** Hinweis am Filter „Tempolimit“ aus dem Manifest: welche Städte es nennen, welche nicht. */
export function tempoHinweis(staedte) {
  const mit = Object.values(staedte || {}).filter((s) => s.kontrollen > 0);
  const ja = mit.filter((s) => s.hat_tempo).map((s) => s.label);
  const nein = mit.filter((s) => !s.hat_tempo).map((s) => s.label);
  if (!ja.length) return "Keine Stadt nennt das Tempolimit.";
  const vorn = `${nein.length && ja.length === 1 ? "Nur " : ""}${aufzaehlung(ja)} ${ja.length === 1 ? "nennt" : "nennen"} das Tempolimit`;
  if (!nein.length) return `${vorn}.`;
  return `${vorn}; ${aufzaehlung(nein)} ${nein.length === 1 ? "steht" : "stehen"} unter „unbekannt“.`;
}

/** Farbklasse 0..4 (FARBEN), -1 für „kein Wert“. */
export function klasse(w, metrik) {
  if (w == null || Number.isNaN(w)) return -1;
  const g = METRIKEN[metrik].grenzen;
  let i = 0;
  while (i < g.length && w >= g[i]) i++;
  return i;
}

/** Beschriftung der Klassen: ["unter 2 %", "2–5 %", …, "ab 20 %"] bzw. ganze Zahlen. */
export function klassenText(metrik) {
  const m = METRIKEN[metrik];
  const g = m.grenzen;
  const e = m.einheit ? (m.einheit === "%" ? " %" : ` ${m.einheit}`) : "";
  const ganz = metrik === "fahrverbote" || metrik === "kontrollen";
  const out = [];
  for (let i = 0; i <= g.length; i++) {
    if (ganz) {
      const von = i === 0 ? (metrik === "fahrverbote" ? 0 : 1) : g[i - 1];
      const bis = i < g.length ? g[i] - 1 : null;
      out.push(bis == null ? `ab ${zahl(von)}${e}` : von === bis ? `${zahl(von)}${e}` : `${zahl(von)}–${zahl(bis)}${e}`);
    } else if (i === 0) out.push(`unter ${zahl(g[0])}${e}`);
    else if (i === g.length) out.push(`ab ${zahl(g[i - 1])}${e}`);
    else out.push(`${zahl(g[i - 1])}–${zahl(g[i])}${e}`);
  }
  return out;
}

/** GeoJSON der Messstellen für die Karte (Eigenschaften knapp: MapLibre serialisiert alles). */
export function punkte(daten, agg, metrik) {
  const features = [];
  for (const [i, a] of agg) {
    const s = daten.stellen[i];
    const w = wert(a, metrik);
    features.push({
      type: "Feature",
      id: i,
      geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      properties: { i, n: a.n, k: klasse(w, metrik), g: s.genau ? 1 : 0 },
    });
  }
  return { type: "FeatureCollection", features };
}

/**
 * Zusammenfassung für die Legende: Messstellen je Klasse, Summen, Zählungen je Filterwert.
 * `stadt` (optional): nur diese Stadt zählen – die Legende spricht über die Stadt im Bild.
 */
export function zusammenfassung(daten, agg, metrik, filter, stadt = null) {
  const jeKlasse = [0, 0, 0, 0, 0];
  let ohneWert = 0;
  let kontrollen = 0;
  let messstellen = 0;
  for (const [i, a] of agg) {
    if (stadt && daten.stellen[i].stadtCode !== stadt) continue;
    messstellen++;
    kontrollen += a.n;
    const k = klasse(wert(a, metrik), metrik);
    if (k < 0) ohneWert++;
    else jeKlasse[k]++;
  }
  // Je Filterwert: Kontrollen, die unter den ÜBRIGEN Filtern dazukämen
  const jeJahr = {};
  const jeTempo = {};
  const jeMethode = {};
  const ohneJahr = { ...filter, jahre: null };
  const ohneTempo = { ...filter, tempo: null };
  const ohneMethode = { ...filter, methoden: null };
  for (const k of daten.kontrollen) {
    if (k.stelle == null || (stadt && k.stadt !== stadt)) continue;
    const m = daten.stellen[k.stelle].methodeCode;
    if (passt(k, ohneJahr, daten)) jeJahr[k.jahr] = (jeJahr[k.jahr] || 0) + 1;
    if (passt(k, ohneTempo, daten)) jeTempo[k.tempoKlasse] = (jeTempo[k.tempoKlasse] || 0) + 1;
    if (passt(k, ohneMethode, daten)) jeMethode[m] = (jeMethode[m] || 0) + 1;
  }
  return { messstellen, kontrollen, jeKlasse, ohneWert, jeJahr, jeTempo, jeMethode };
}

/** Die Kontrollen einer Messstelle (neueste zuerst), mit `imFilter`. */
export function kontrollenDerStelle(daten, i, filter) {
  return daten.kontrollen
    .filter((k) => k.stelle === i)
    .map((k) => ({ ...k, imFilter: passt(k, filter, daten) }))
    .sort((a, b) => (b.tag ?? 0) - (a.tag ?? 0) || (b.beginn ?? 0) - (a.beginn ?? 0));
}

// --- Formatieren (deutsch) ---------------------------------------------------------------

const NF0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
const NF1 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function zahl(v, nachkomma = 0) {
  if (v == null || Number.isNaN(v)) return "–";
  return nachkomma ? NF1.format(v) : NF0.format(v);
}

export function datumText(d) {
  if (!d) return "–";
  const t = String(d.getUTCDate()).padStart(2, "0");
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `${t}.${m}.${d.getUTCFullYear()}`;
}

export function uhrzeit(min) {
  if (min == null) return null;
  const h = Math.floor(min / 60) % 24;
  return `${String(h).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
}

export function dauerText(min) {
  if (min == null) return null;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`;
}

export function wertText(w, metrik) {
  if (w == null) return "–";
  if (metrik === "anteil") return `${zahl(w, 1)} %`;
  if (metrik === "stunde") return `${zahl(w, w < 10 ? 1 : 0)} je Stunde`;
  if (metrik === "jekontrolle") return `${zahl(w, w < 10 ? 1 : 0)} je Kontrolle`;
  return zahl(w);
}
