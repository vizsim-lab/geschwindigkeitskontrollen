// SPDX-License-Identifier: AGPL-3.0-or-later
// suche.js — Adresssuche über Photon (Komoot), keyless; Stil und Bedienung wie in
// vizsim/unfallkarte (js/utils/geocoder.js): Pfeiltasten, Enter, Escape, Löschen-Knopf.

import { esc } from "./popup.js";

export function sucheAnlegen(map) {
  const box = document.createElement("div");
  box.className = "geocoder";
  box.innerHTML = `
    <div class="geocoder-input-wrapper">
      <svg class="geocoder-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.35-4.35"></path></svg>
      <input type="search" id="suche" placeholder="Adresse suchen …" autocomplete="off" aria-label="Adresse suchen" />
      <button class="geocoder-clear" type="button" title="Löschen" aria-label="Suche löschen" hidden>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </button>
    </div>
    <div class="geocoder-results" role="listbox" hidden></div>`;
  document.body.appendChild(box);
  const input = box.querySelector("input");
  const liste = box.querySelector(".geocoder-results");
  const loeschen = box.querySelector(".geocoder-clear");
  let marker = null;
  let treffer = [];
  let gewaehlt = -1;
  let timer = null;

  const text = (f) => {
    const p = f.properties || {};
    const haupt = p.street && p.housenumber ? `${p.street} ${p.housenumber}` : p.name || p.street || "Ort";
    return { haupt, neben: [p.postcode, p.city || p.county, p.state].filter(Boolean).join(" ") };
  };
  const zu = () => {
    liste.hidden = true;
    liste.innerHTML = "";
    treffer = [];
    gewaehlt = -1;
  };
  const waehle = (f) => {
    const [lon, lat] = f.geometry.coordinates;
    marker?.remove();
    marker = new maplibregl.Marker({ color: "#2563eb" }).setLngLat([lon, lat]).addTo(map);
    map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 15.5), essential: true });
    const t = text(f);
    input.value = t.neben ? `${t.haupt}, ${t.neben}` : t.haupt;
    loeschen.hidden = false;
    zu();
  };
  const zeige = (fs) => {
    treffer = fs;
    gewaehlt = -1;
    liste.innerHTML = fs.length
      ? fs
          .map((f, i) => {
            const t = text(f);
            return `<div class="geocoder-result-item" role="option" data-i="${i}"><div class="geocoder-result-primary">${esc(t.haupt)}</div>${t.neben ? `<div class="geocoder-result-secondary">${esc(t.neben)}</div>` : ""}</div>`;
          })
          .join("")
      : '<div class="geocoder-no-results">Nichts gefunden</div>';
    liste.hidden = false;
  };
  liste.addEventListener("click", (e) => {
    const el = e.target.closest("[data-i]");
    if (el) waehle(treffer[Number(el.dataset.i)]);
  });
  input.addEventListener("input", () => {
    const q = input.value.trim();
    loeschen.hidden = !input.value;
    clearTimeout(timer);
    if (q.length < 3) return zu();
    timer = setTimeout(async () => {
      try {
        // nahe der aktuellen Kartenmitte zuerst (Berlin oder Aachen)
        const c = map.getCenter();
        const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(q)}&lang=de&limit=7&lat=${c.lat.toFixed(4)}&lon=${c.lng.toFixed(4)}&bbox=5.8,47.2,15.1,55.1`;
        const r = await fetch(url);
        zeige((await r.json()).features || []);
      } catch {
        zeige([]);
      }
    }, 250);
  });
  input.addEventListener("keydown", (e) => {
    const items = liste.querySelectorAll(".geocoder-result-item");
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      gewaehlt = (gewaehlt + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      items.forEach((it, i) => it.classList.toggle("selected", i === gewaehlt));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const f = treffer[gewaehlt >= 0 ? gewaehlt : 0];
      if (f) waehle(f);
    } else if (e.key === "Escape") zu();
  });
  loeschen.addEventListener("click", () => {
    input.value = "";
    loeschen.hidden = true;
    marker?.remove();
    marker = null;
    zu();
    input.focus();
  });
  document.addEventListener("click", (e) => {
    if (!box.contains(e.target)) zu();
  });
}
