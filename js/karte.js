// SPDX-License-Identifier: AGPL-3.0-or-later
// karte.js — Karte, Hintergründe (Positron / OSM Carto / Esri) und Navigation unten links.
// Muster aus vizsim/unfallkarte (basemapTerrain.js, setupMapPanel.js): Raster-Hintergründe als
// Layer unter allem, beim Umschalten werden nur die Layer der Positron-Quelle versteckt.

const STIL = "https://tiles.openfreemap.org/styles/positron";
const RASTER = {
  osm: {
    tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
    attribution: "© OpenStreetMap-Mitwirkende",
  },
  satellite: {
    tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
    attribution: "Tiles © Esri",
  },
};

export function erzeugeKarte({ center, zoom, quellenText }) {
  const map = new maplibregl.Map({
    container: "map",
    style: STIL,
    center,
    zoom,
    attributionControl: false,
    dragRotate: false,
    pitchWithRotate: false,
  });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: quellenText }), "bottom-right");
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: "metric" }), "bottom-right");
  const nav = new maplibregl.NavigationControl({ showCompass: false });
  document.getElementById("custom-nav-control")?.appendChild(nav.onAdd(map));
  return map;
}

/** Raster-Hintergründe einhängen (unsichtbar) – einmal nach dem Laden des Stils. */
export function hintergruendeAnlegen(map) {
  const erster = map.getStyle().layers.find((l) => l.type !== "background")?.id;
  for (const [id, r] of Object.entries(RASTER)) {
    if (map.getSource(`bg-${id}`)) continue;
    map.addSource(`bg-${id}`, { type: "raster", tiles: r.tiles, tileSize: 256, attribution: r.attribution, maxzoom: 19 });
    map.addLayer({ id: `bg-${id}`, type: "raster", source: `bg-${id}`, layout: { visibility: "none" } }, erster);
  }
}

export function setzeHintergrund(map, art) {
  for (const id of Object.keys(RASTER)) {
    map.setLayoutProperty(`bg-${id}`, "visibility", id === art ? "visible" : "none");
  }
  const positron = art === "positron";
  for (const l of map.getStyle().layers) {
    if (l.source === "openmaptiles" || l.type === "background") {
      map.setLayoutProperty(l.id, "visibility", positron ? "visible" : "none");
    }
  }
}

export function kartenPanel(map) {
  const panel = document.getElementById("map-settings-panel");
  const knopf = document.getElementById("map-settings-toggle");
  knopf.addEventListener("click", () => {
    const zu = panel.classList.toggle("is-collapsed");
    knopf.setAttribute("aria-expanded", String(!zu));
  });
  for (const btn of document.querySelectorAll(".basemap-btn[data-basemap]")) {
    btn.addEventListener("click", () => {
      setzeHintergrund(map, btn.dataset.basemap);
      for (const b of document.querySelectorAll(".basemap-btn")) b.classList.toggle("selected", b === btn);
    });
  }
}

/** Erster Symbol-Layer des Stils: Linien darunter, damit Straßennamen lesbar bleiben. */
export function ersterSymbolLayer(map) {
  return map.getStyle().layers.find((l) => l.type === "symbol")?.id;
}
