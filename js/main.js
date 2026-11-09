// SPDX-License-Identifier: AGPL-3.0-or-later
// main.js — Start: Daten laden, Karte und Legende aufbauen, Filter, Fenster und Link verdrahten.
//
// Daten: pipeline/data/karte/ (manifest.json nennt die Dateien). Die Karte rechnet die
// Messstellen aus den Kontrollen selbst (js/daten.js), damit Filter ohne Server gehen.

import * as D from "./daten.js";
import * as P from "./permalink.js";
import { esc, stelleHtml } from "./popup.js";
import { erzeugeKarte, ersterSymbolLayer, hintergruendeAnlegen, kartenPanel } from "./karte.js";
import { sucheAnlegen } from "./suche.js";
import { methodeHtml } from "./methode.js";

const PFAD = "pipeline/data/karte/";
const zustand = { metrik: "anteil", jahre: null, tempo: null, methoden: null, stelle: null };
let daten;
let manifest;
let map;
let agg = new Map();
let stadtImBild = "berlin";
let hoverId = null;
const vorschau = () => (vorschau.p ??= new maplibregl.Popup({ closeButton: false, closeOnClick: false, maxWidth: "340px", className: "pop-vorschau", offset: 10 }));
const fest = () => (fest.p ??= new maplibregl.Popup({ closeButton: true, closeOnClick: false, maxWidth: "440px", offset: 10 }));

start().catch(zeigeFehler);

async function json(datei) {
  const r = await fetch(PFAD + datei);
  if (!r.ok) throw new Error(`${datei}: HTTP ${r.status}`);
  return r.json();
}

async function start() {
  manifest = await json("manifest.json");
  const anker = P.lies(location.hash);
  for (const k of ["metrik", "jahre", "tempo", "methoden", "stelle"]) if (anker[k] !== undefined) zustand[k] = anker[k];
  for (const k of ["jahre", "tempo", "methoden"]) if (zustand[k] && !zustand[k].size) zustand[k] = null;
  const b = manifest.staedte.berlin.start;
  const ansicht = anker.zoom != null ? { lon: anker.lon, lat: anker.lat, zoom: anker.zoom } : b;
  map = erzeugeKarte({ center: [ansicht.lon, ansicht.lat], zoom: ansicht.zoom, quellenText: quellenText() });
  window.map = map; // Test-Hook (tests/web)

  const datenLaden = Promise.all([
    json(manifest.dateien.messstellen),
    json(manifest.dateien.kontrollen),
    json(manifest.dateien.abschnitte),
  ]);
  const kartenLaden = new Promise((fertig) => (map.loaded() ? fertig() : map.once("load", fertig)));
  const [[stellenJson, kontrollenJson, abschnitte]] = await Promise.all([datenLaden, kartenLaden]);
  daten = D.entpacke(stellenJson, kontrollenJson);
  window.__app = { daten, zustand, manifest, zeichne };

  legendeAufbauen();
  sucheAnlegen(map);
  kartenPanel(map);
  tooltips();
  hintergruendeAnlegen(map);
  ebenenAnlegen(abschnitte);
  interaktion();
  stadtBestimmen();
  zeichne();
  if (zustand.stelle) {
    const s = daten.stellen.find((x) => x.id === zustand.stelle);
    if (s && agg.has(s.i)) zeigeStelle(s.i, true);
  }
  map.on("moveend", () => {
    stadtBestimmen();
    schreibeLink();
  });
  // Link von Hand geändert oder eingefügt (die Karte selbst schreibt per replaceState, das
  // löst kein hashchange aus): Zustand neu lesen
  addEventListener("hashchange", () => location.reload());
  map.once("idle", () => (document.body.dataset.bereit = "1"));
}

// --- Karte ---------------------------------------------------------------------------------

function farbe(ausdruck) {
  return ["match", ausdruck, 0, D.FARBEN[0], 1, D.FARBEN[1], 2, D.FARBEN[2], 3, D.FARBEN[3], 4, D.FARBEN[4], D.GRAU];
}

function ebenenAnlegen(abschnitte) {
  const unter = ersterSymbolLayer(map);
  map.addSource("abschnitte", { type: "geojson", data: abschnitte, promoteId: "s" });
  map.addSource("messstellen", { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "i" });
  const an = ["boolean", ["feature-state", "an"], false];
  const k = ["coalesce", ["feature-state", "k"], -1];
  map.addLayer(
    {
      id: "abschnitte",
      type: "line",
      source: "abschnitte",
      minzoom: 12,
      filter: ["!=", ["get", "m"], 4],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": farbe(k),
        "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2, 16, 6],
        "line-opacity": ["case", an, 0.7, 0],
      },
    },
    unter
  );
  map.addLayer(
    {
      id: "strassen-grob",
      type: "line",
      source: "abschnitte",
      minzoom: 12,
      filter: ["==", ["get", "m"], 4],
      layout: { "line-cap": "butt", "line-join": "round" },
      paint: {
        "line-color": farbe(k),
        "line-width": ["interpolate", ["linear"], ["zoom"], 12, 1.5, 16, 4],
        "line-dasharray": [2, 1.5],
        "line-opacity": ["case", an, 0.55, 0],
      },
    },
    unter
  );
  const r = (f) => ["+", 1.3, ["*", f, ["sqrt", ["min", ["get", "n"], 80]]]];
  map.addLayer({
    id: "punkte",
    type: "circle",
    source: "messstellen",
    layout: { "circle-sort-key": ["get", "k"] },
    paint: {
      "circle-color": farbe(["get", "k"]),
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 9, r(0.55), 12, r(1.15), 15, r(1.9), 18, r(2.6)],
      "circle-opacity": ["case", ["==", ["get", "g"], 1], 0.92, 0.4],
      "circle-stroke-color": ["case", ["boolean", ["feature-state", "hover"], false], "#111827", ["==", ["get", "g"], 1], "#ffffff", "#6b7280"],
      // „zoom“ darf nur ganz oben stehen -> der Hover-Fall steckt in jeder Stufe
      "circle-stroke-width": [
        "interpolate", ["linear"], ["zoom"],
        9, ["case", ["boolean", ["feature-state", "hover"], false], 2.5, 0.3],
        13, ["case", ["boolean", ["feature-state", "hover"], false], 2.5, 1.2],
      ],
    },
  });
}

/** Filter anwenden, Messstellen neu rechnen und zeichnen, Legende und Link nachziehen. */
function zeichne() {
  agg = D.verdichte(daten, zustand);
  map.getSource("messstellen").setData(D.punkte(daten, agg, zustand.metrik));
  for (const s of daten.stellen) {
    const a = agg.get(s.i);
    map.setFeatureState({ source: "abschnitte", id: s.i }, a ? { an: true, k: D.klasse(D.wert(a, zustand.metrik), zustand.metrik) } : { an: false });
  }
  legendeAktualisieren();
  if (fest.p?.isOpen() && fest.p._stelle != null) {
    if (agg.has(fest.p._stelle)) zeigeStelle(fest.p._stelle, true);
    else fest.p.remove();
  }
  schreibeLink();
}

function interaktion() {
  map.on("mousemove", "punkte", (e) => {
    const f = e.features[0];
    if (!f) return;
    map.getCanvas().style.cursor = "pointer";
    if (hoverId !== f.id) {
      if (hoverId != null) map.setFeatureState({ source: "messstellen", id: hoverId }, { hover: false });
      hoverId = f.id;
      map.setFeatureState({ source: "messstellen", id: hoverId }, { hover: true });
    }
    if (fest.p?.isOpen() && fest.p._stelle === f.id) return vorschau().remove();
    vorschau().setLngLat(f.geometry.coordinates).setHTML(html(f.id, false)).addTo(map);
  });
  map.on("mouseleave", "punkte", () => {
    map.getCanvas().style.cursor = "";
    if (hoverId != null) map.setFeatureState({ source: "messstellen", id: hoverId }, { hover: false });
    hoverId = null;
    vorschau().remove();
  });
  map.on("click", (e) => {
    const f = map.queryRenderedFeatures(e.point, { layers: ["punkte"] })[0];
    if (f) zeigeStelle(f.id, false);
    else if (fest.p?.isOpen()) fest.p.remove();
  });
}

function html(i, voll) {
  return stelleHtml({ daten, stelle: daten.stellen[i], agg: agg.get(i), metrik: zustand.metrik, filter: zustand, manifest, voll });
}

function zeigeStelle(i, ohneFlug) {
  vorschau().remove();
  const s = daten.stellen[i];
  const p = fest();
  p._stelle = i;
  p.setLngLat([s.lon, s.lat]).setHTML(html(i, true)).addTo(map);
  p.getElement().querySelector('[data-aktion="link"]')?.addEventListener("click", (ev) => {
    ev.preventDefault();
    navigator.clipboard?.writeText(location.href).then(() => (ev.target.textContent = "Link kopiert ✓"));
  });
  zustand.stelle = s.id;
  p.once("close", () => {
    if (zustand.stelle === s.id) zustand.stelle = null;
    schreibeLink();
  });
  if (!ohneFlug && map.getZoom() < 13) map.easeTo({ center: [s.lon, s.lat], zoom: 14 });
  schreibeLink();
}

function stadtBestimmen() {
  const c = map.getCenter();
  let beste = stadtImBild;
  let d0 = Infinity;
  for (const [code, s] of Object.entries(manifest.staedte)) {
    const d = Math.hypot((c.lng - s.start.lon) * 0.62, c.lat - s.start.lat);
    if (d < d0) [d0, beste] = [d, code];
  }
  if (beste !== stadtImBild) {
    stadtImBild = beste;
    legendeAktualisieren();
  }
  for (const b of document.querySelectorAll(".stadt-btn")) b.classList.toggle("is-active", b.dataset.stadt === stadtImBild);
}

function schreibeLink() {
  if (!map) return;
  const c = map.getCenter();
  const a = P.schreibe({ zoom: map.getZoom(), lat: c.lat, lon: c.lng, ...zustand });
  history.replaceState(null, "", "#" + a);
}

// --- Legende -------------------------------------------------------------------------------

function legendeAufbauen() {
  const st = manifest.staedte;
  document.getElementById("untertitel").textContent = Object.values(st)
    .map((s) => `${s.label} ${jahre(s.jahre)}`)
    .join(" · ");
  document.getElementById("quelle-tip").dataset.tip = `Quellen: ${Object.values(st).map((s) => s.quelle.bereitsteller).join(", ")} · Verortung: OpenStreetMap (ODbL) · Stand ${manifest.stand}`;
  for (const b of document.querySelectorAll(".stadt-btn")) {
    const s = st[b.dataset.stadt];
    b.querySelector(".stadt-jahre").textContent = `${jahre(s.jahre)} · ${D.zahl(s.kontrollen)} Kontrollen`;
    b.addEventListener("click", () => map.flyTo({ center: [s.start.lon, s.start.lat], zoom: s.start.zoom, essential: true }));
  }
  for (const r of document.querySelectorAll('input[name="metrik"]')) {
    r.checked = r.value === zustand.metrik;
    r.addEventListener("change", () => {
      zustand.metrik = r.value;
      zeichne();
    });
  }
  const alleJahre = [...new Set(Object.values(st).flatMap((s) => s.jahre))].sort();
  chips("f-jahre", alleJahre.map((j) => ({ wert: j, text: String(j) })), "jahre", Number);
  chips("f-tempo", D.TEMPO.map((t) => ({ wert: t.id, text: t.label })), "tempo", String);
  chips("f-verortung", daten.methoden.map((m) => ({ wert: m, text: D.METHODEN_TEXT[m].replace(" zwischen zwei Querstraßen", "") })), "methoden", String);
  document.getElementById("filter-zurueck").addEventListener("click", () => {
    zustand.jahre = zustand.tempo = zustand.methoden = null;
    for (const i of document.querySelectorAll(".chips input")) i.checked = true;
    zeichne();
  });
  const legende = document.getElementById("legende");
  const auf = document.getElementById("legende-auf");
  const setze = (zu) => {
    legende.classList.toggle("collapsed", zu);
    auf.classList.toggle("open", !zu);
    auf.setAttribute("aria-expanded", String(!zu));
  };
  setze(legende.classList.contains("collapsed"));
  auf.addEventListener("click", () => setze(!legende.classList.contains("collapsed")));
  const dlg = document.getElementById("methode");
  document.getElementById("methode-auf").addEventListener("click", () => {
    document.getElementById("methode-inhalt").innerHTML = methodeHtml(manifest);
    dlg.showModal();
  });
  dlg.querySelector(".info-zu").addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (e) => e.target === dlg && dlg.close());
  document.getElementById("csv-link").href = PFAD + manifest.dateien.csv;
}

function chips(id, eintraege, feld, typ) {
  const el = document.getElementById(id);
  el.innerHTML = eintraege
    .map(
      (e) => `<label class="legend-chip" data-wert="${esc(e.wert)}"><input type="checkbox" value="${esc(e.wert)}" ${!zustand[feld] || zustand[feld].has(e.wert) ? "checked" : ""}/><span>${esc(e.text)} <span class="zahl"></span></span></label>`
    )
    .join("");
  el.addEventListener("change", () => {
    const an = [...el.querySelectorAll("input:checked")].map((i) => typ(i.value));
    zustand[feld] = an.length === eintraege.length ? null : new Set(an);
    zeichne();
  });
}

function legendeAktualisieren() {
  const z = D.zusammenfassung(daten, agg, zustand.metrik, zustand, stadtImBild);
  const texte = D.klassenText(zustand.metrik);
  document.getElementById("klassen").innerHTML =
    texte.map((t, i) => `<li><span class="punkt" style="background:${D.FARBEN[i]}"></span><span class="text">${esc(t)}</span><span class="count-badge">${D.zahl(z.jeKlasse[i])}</span></li>`).join("") +
    (z.ohneWert ? `<li><span class="punkt" style="background:${D.GRAU}"></span><span class="text">kein Wert</span><span class="count-badge">${D.zahl(z.ohneWert)}</span></li>` : "");
  const st = manifest.staedte[stadtImBild];
  let hinweis = D.METRIKEN[zustand.metrik].hinweis;
  if (stadtImBild === "aachen" && (zustand.metrik === "stunde" || zustand.metrik === "fahrverbote")) hinweis += " Aachen nennt das nicht – hier grau.";
  if (stadtImBild === "berlin" && zustand.metrik === "anteil") hinweis += ` In Berlin zählte die Polizei bei ${D.zahl(100 - 100 * st.anteil_alle_gezaehlt)} % der Kontrollen nur die zu schnellen Fahrzeuge.`;
  document.getElementById("metrik-hinweis").textContent = hinweis;
  zahlenInChips("f-jahre", z.jeJahr);
  zahlenInChips("f-tempo", z.jeTempo);
  zahlenInChips("f-verortung", z.jeMethode);
  document.getElementById("fc-stellen").textContent = D.zahl(z.messstellen);
  document.getElementById("fc-kontrollen").textContent = D.zahl(z.kontrollen);
  document.getElementById("filter-zurueck").hidden = !(zustand.jahre || zustand.tempo || zustand.methoden);
}

function zahlenInChips(id, zahlen) {
  for (const l of document.getElementById(id).querySelectorAll(".legend-chip")) {
    const n = zahlen[l.dataset.wert] || 0;
    l.querySelector(".zahl").textContent = D.zahl(n);
    l.classList.toggle("is-leer", n === 0);
  }
}

function jahre(liste) {
  if (!liste?.length) return "";
  return liste.length === 1 ? String(liste[0]) : `${liste[0]}–${liste[liste.length - 1]}`;
}

function quellenText() {
  return Object.values(manifest.staedte)
    .map((s) => `<a href="${esc(s.quelle.herkunft_url)}" target="_blank" rel="noopener">${esc(s.quelle.kurz)}</a>`)
    .join(" · ");
}

// --- Kleinkram -----------------------------------------------------------------------------

function tooltips() {
  const tip = document.createElement("div");
  tip.className = "app-tooltip";
  document.body.appendChild(tip);
  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (!el || !el.dataset.tip) return;
    tip.textContent = el.dataset.tip;
    const r = el.getBoundingClientRect();
    tip.style.left = `${Math.max(8, Math.min(innerWidth - 270, r.left - 120))}px`;
    tip.style.top = `${r.bottom + 6}px`;
    tip.classList.add("is-visible");
  });
  document.addEventListener("mouseout", (e) => {
    if (e.target.closest?.("[data-tip]")) tip.classList.remove("is-visible");
  });
}

function zeigeFehler(e) {
  console.error(e);
  const el = document.getElementById("fehler");
  el.textContent = `Die Karte konnte nicht geladen werden: ${e.message}`;
  el.hidden = false;
}
