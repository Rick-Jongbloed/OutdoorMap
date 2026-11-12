// OutdoorMap – kaart met wandelingen per gebied

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

fetch('data/walks.json')
  .then(r => r.json())
  .then(({ regions, walks }) => {
    const groups = {}, lines = {}, overlays = {};

    regions.forEach(r => {
      groups[r.id] = L.featureGroup().addTo(map);
      const n = walks.filter(w => w.region === r.id).length;
      overlays[`<span class="swatch" style="background:${r.color}"></span> ${r.name} – ${r.land} (${n})`] = groups[r.id];
    });
    overlays['🥾 Wandelroutes (Waymarked Trails)'] = hikingOverlay;

    walks.forEach(w => {
      const region = regions.find(r => r.id === w.region);
      const line = L.polyline(decodePolyline(w.polyline), { color: region.color, weight: 4, opacity: 0.9 })
        .bindPopup(`<b>${w.name}</b><br>${w.date} · ${w.km} km · ${w.hm} hm<br>` +
                   `<a href="https://www.strava.com/activities/${w.id}" target="_blank" rel="noopener">Open in Strava</a>`);
      line.addTo(groups[w.region]);
      lines[w.id] = line;
    });

    L.control.layers(baseLayers, overlays, { collapsed: window.innerWidth < 700 }).addTo(map);
    map.fitBounds(L.featureGroup(Object.values(lines)).getBounds());

    // Lijst per gebied, nieuwste eerst
    const list = document.getElementById('list');
    regions.forEach(r => {
      const ws = walks.filter(w => w.region === r.id).sort((a, b) => b.date.localeCompare(a.date));
      const km = ws.reduce((s, w) => s + w.km, 0);
      const h = document.createElement('h2');
      h.innerHTML = `<span class="swatch" style="background:${r.color}"></span>${r.name} ` +
                    `<span class="muted">– ${r.land} · ${ws.length}× · ${km.toFixed(0)} km</span>`;
      h.onclick = () => map.fitBounds(groups[r.id].getBounds(), { padding: [30, 30] });
      list.appendChild(h);
      ws.forEach(w => {
        const d = document.createElement('div');
        d.className = 'walk';
        d.innerHTML = `${w.date} – ${w.name} <span class="muted">(${w.km} km, ${w.hm} hm)</span>`;
        d.onclick = () => { map.fitBounds(lines[w.id].getBounds(), { padding: [30, 30] }); lines[w.id].openPopup(); };
        list.appendChild(d);
      });
    });
  });
