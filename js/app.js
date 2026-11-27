// OutdoorMap – kaart met wandelingen per gebied
// Data: data/gebieden.json, data/routes.json (de route + bron), data/walks.json (elke keer gelopen)

// Decodeert een Google encoded polyline naar [[lat, lng], ...]
function decodePolyline(str) {
  let index = 0, lat = 0, lng = 0;
  const coords = [];
  while (index < str.length) {
    for (const axis of [0, 1]) {
      let result = 0, shift = 0, b;
      do {
        b = str.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      const delta = (result & 1) ? ~(result >> 1) : (result >> 1);
      if (axis === 0) lat += delta; else lng += delta;
    }
    coords.push([lat / 1e5, lng / 1e5]);
  }
  return coords;
}

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtKm = km => km == null ? '?' : (Math.round(km * 10) / 10).toString().replace('.', ',');

const map = L.map('map');

const baseLayers = {
  'OSM': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '© OpenStreetMap'
  }),
  'Topo (OpenTopoMap)': L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    maxZoom: 17, attribution: '© OpenStreetMap, © OpenTopoMap'
  }),
  'Satelliet (Esri)': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19, attribution: 'Esri World Imagery'
  })
};
baseLayers['OSM'].addTo(map);

const hikingOverlay = L.tileLayer('https://tile.waymarkedtrails.org/hiking/{z}/{x}/{y}.png', {
  maxZoom: 18, opacity: 0.8, attribution: '© waymarkedtrails.org'
});

function routePopup(route, gebied, walks) {
  const bron = route.bron.url
    ? `<a href="${esc(route.bron.url)}" target="_blank" rel="noopener">${esc(route.bron.naam)}</a>`
    : esc(route.bron.naam || 'onbekend');
  const status = walks.length
    ? `Gelopen (${walks.length}x): ` + walks.map(w =>
        `<a href="https://www.strava.com/activities/${w.strava_id}" target="_blank" rel="noopener">${w.datum}</a>`).join(', ')
    : 'Nog niet gelopen';
  const extra = [];
  if (route.graad) extra.push(`graad ${route.graad} (${esc(route.graad_kleur)})`);
  if (route.hindernissen.length) extra.push('hindernissen: ' + route.hindernissen.map(esc).join(', '));
  return `<b>${esc(route.code)} – ${esc(route.naam)}</b><br>` +
         `${esc(gebied.naam)} (${esc(gebied.land)}) · ${fmtKm(route.km)} km${route.hm ? ` · ${route.hm} hm` : ''}<br>` +
         `Bron: ${bron}<br>${status}` +
         (route.samenvatting ? `<br><i>${esc(route.samenvatting)}</i>` : '') +
         (extra.length ? `<br><span class="muted">${extra.join(' · ')}</span>` : '');
}

Promise.all(['gebieden', 'routes', 'walks'].map(n => fetch(`data/${n}.json`).then(r => r.json())))
  .then(([{ gebieden, landen }, routes, walks]) => {
    const gebied = Object.fromEntries(gebieden.map(g => [g.id, g]));
    const route = Object.fromEntries(routes.map(r => [r.code, r]));
    const walksPerRoute = {};
    walks.forEach(w => (walksPerRoute[w.route] ??= []).push(w));

    const groups = {}, lines = {}, overlays = {};
    const todo = L.featureGroup();  // startpunten van nog niet gelopen routes

    // Land van een gebied: eerste land bij "Duitsland / België"
    const landVan = g => (g.land || 'Overig').split(' / ')[0];
    const landenCfg = landen || [];
    const uit = new Set(landenCfg.filter(l => l.standaard_uit).map(l => l.naam));

    // Alleen gebieden met gelopen wandelingen krijgen een eigen laag
    const actief = gebieden.filter(g => routes.some(r => r.gebied === g.id && walksPerRoute[r.code]));
    const nRoutes = {};
    actief.forEach(g => {
      groups[g.id] = L.featureGroup();
      if (!uit.has(landVan(g))) groups[g.id].addTo(map);
      nRoutes[g.id] = routes.filter(r => r.gebied === g.id && walksPerRoute[r.code]).length;
    });

    walks.forEach(w => {
      const r = route[w.route], g = gebied[r.gebied];
      const line = L.polyline(decodePolyline(w.polyline), { color: g.kleur, weight: 4, opacity: 0.9 })
        .bindPopup(routePopup(r, g, walksPerRoute[r.code]));
      line.addTo(groups[g.id]);
      lines[w.strava_id] = line;
    });

    routes.filter(r => !walksPerRoute[r.code] && r.start).forEach(r => {
      const g = gebied[r.gebied];
      L.circleMarker(r.start, { radius: 6, color: g.kleur, weight: 2, fillColor: '#fff', fillOpacity: 0.9 })
        .bindPopup(routePopup(r, g, []))
        .addTo(todo);
    });
    overlays['○ Nog niet gelopen (startpunten)'] = todo;
    overlays['🥾 Wandelroutes (Waymarked Trails)'] = hikingOverlay;

    L.control.layers(baseLayers, overlays, { collapsed: window.innerWidth < 700 }).addTo(map);

    // Paneel met gebieden per land: landschakelaar zet alle gebieden van dat land aan/uit
    const volgorde = landenCfg.map(l => l.naam);
    const perLand = {};
    actief.forEach(g => (perLand[landVan(g)] ??= []).push(g));
    const landNamen = Object.keys(perLand).sort((a, b) =>
      ((volgorde.indexOf(a) + 1) || 99) - ((volgorde.indexOf(b) + 1) || 99) || a.localeCompare(b));

    const zet = (g, aan) => aan ? groups[g.id].addTo(map) : map.removeLayer(groups[g.id]);
    const landBox = {}, gebiedBox = {};
    const syncLand = land => {
      const gs = perLand[land], n = gs.filter(g => map.hasLayer(groups[g.id])).length;
      landBox[land].checked = n === gs.length;
      landBox[land].indeterminate = n > 0 && n < gs.length;
    };
    const toonGebied = g => { zet(g, true); gebiedBox[g.id].checked = true; syncLand(landVan(g)); };

    const LandenControl = L.Control.extend({
      options: { position: 'topright' },
      onAdd() {
        const div = L.DomUtil.create('div', 'leaflet-control-layers landen-control');
        const det = L.DomUtil.create('details', '', div);
        det.open = window.innerWidth >= 700;
        L.DomUtil.create('summary', '', det).textContent = 'Gebieden per land';
        landNamen.forEach(land => {
          const gs = perLand[land];
          const blok = L.DomUtil.create('div', 'land', det);
          const kop = L.DomUtil.create('label', 'land-kop', blok);
          const cb = L.DomUtil.create('input', '', kop);
          cb.type = 'checkbox';
          landBox[land] = cb;
          kop.append(` ${land} (${gs.reduce((s, g) => s + nRoutes[g.id], 0)})`);
          cb.onchange = () => {
            gs.forEach(g => { zet(g, cb.checked); gebiedBox[g.id].checked = cb.checked; });
            syncLand(land);
          };
          gs.forEach(g => {
            const lab = L.DomUtil.create('label', 'gebied', blok);
            const gcb = L.DomUtil.create('input', '', lab);
            gcb.type = 'checkbox';
            gcb.checked = map.hasLayer(groups[g.id]);
            gebiedBox[g.id] = gcb;
            lab.insertAdjacentHTML('beforeend',
              ` <span class="swatch" style="background:${g.kleur}"></span> ${esc(g.naam)} (${nRoutes[g.id]})`);
            gcb.onchange = () => { zet(g, gcb.checked); syncLand(land); };
          });
          syncLand(land);
        });
        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);
        return div;
      }
    });
    new LandenControl().addTo(map);

    const zichtbaar = Object.values(lines).filter(l => actief.some(g => map.hasLayer(groups[g.id]) && groups[g.id].hasLayer(l)));
    map.fitBounds(L.featureGroup(zichtbaar.length ? zichtbaar : Object.values(lines)).getBounds());

    // Lijst per gebied: routes met alle datums, nieuwste eerst
    const list = document.getElementById('list');
    actief.forEach(g => {
      const rs = routes.filter(r => r.gebied === g.id && walksPerRoute[r.code])
        .sort((a, b) => walksPerRoute[b.code][0].datum.localeCompare(walksPerRoute[a.code][0].datum));
      const nWalks = rs.reduce((s, r) => s + walksPerRoute[r.code].length, 0);
      const h = document.createElement('h2');
      h.innerHTML = `<span class="swatch" style="background:${g.kleur}"></span>${esc(g.naam)} ` +
                    `<span class="muted">– ${esc(g.land)} · ${rs.length} routes · ${nWalks}× gelopen</span>`;
      h.onclick = () => { toonGebied(g); map.fitBounds(groups[g.id].getBounds(), { padding: [30, 30] }); };
      list.appendChild(h);
      rs.forEach(r => {
        const ws = walksPerRoute[r.code];
        const d = document.createElement('div');
        d.className = 'walk';
        d.innerHTML = `${esc(r.naam)} <span class="muted">(${fmtKm(r.km)} km · ${ws.map(w => w.datum).join(', ')})</span>`;
        d.onclick = () => {
          toonGebied(g);
          const ls = ws.map(w => lines[w.strava_id]);
          map.fitBounds(L.featureGroup(ls).getBounds(), { padding: [30, 30] });
          ls[0].openPopup();
        };
        list.appendChild(d);
      });
    });
  });
