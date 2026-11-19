# OutdoorMap

Persoonlijke kaart van mijn wandelingen, ingedeeld per gebied, met datum, afstand en hoogtemeters uit Strava, en gekoppeld aan de bron van elke route.

**Live:** https://rick-jongbloed.github.io/OutdoorMap/

## Wat staat erop

- Gelopen wandelingen (263 routes, 200 wandelingen, 36 gebieden) in de Ardennen, Eifel, Mullerthal, Moezel/Hunsrück, Semois, Nederland, Oostenrijk, Zwitserland, Sauerland en Harz, per gebied met het land erbij.
- Per route alle keren dat ik hem liep, met links naar Strava en naar de bron.
- Laag met startpunten van routes die ik nog niet liep (o.a. de catalogus van Originele wandelingen, Gert Sonck).
- Kaartlagen: OSM, topo (OpenTopoMap), satelliet (Esri) en bewegwijzerde wandelroutes (Waymarked Trails).

## Opbouw

Statische site zonder server of build-stap. Deze repo is de enige plek waar de data echt staat; alles daarbuiten (Google Drive, NotebookLM) is een export.

| Pad | Inhoud |
|---|---|
| `index.html`, `css/`, `js/app.js` | De site |
| `data/gebieden.json` | Gebieden (naam, land, kleur) en de groepen voor de NotebookLM-docs |
| `data/routes.json` | Routes: code, naam, bron, gebied, start, afstand, graad, kenmerken, hindernissen, rijtijd, enz. |
| `data/walks.json` | Elke keer dat een route gelopen is: Strava-id, datum, km, hm, eigen notities, track |
| `tools/import_strava.py` | Importeert een Strava-selectie (gpx/tcx/fit) naar gebieden, routes en wandelingen, met herkenning van herhaalde routes |
| `tools/export_notebook.py` | Maakt de gebieds-docs en `master_index.csv` voor NotebookLM |
| `tools/notebook_targets.json` | Google Drive-id's van de docs en de master_index |
| `vendor/leaflet/` | Leaflet 1.9.4 |

Lokaal bekijken: `python -m http.server` in de map en open `http://localhost:8000`.

### Routecodes

Elke route heeft een vaste code, de gedeelde sleutel tussen OutdoorMap, NotebookLM en Gemini.

| Prefix | Bron |
|---|---|
| geen (bijv. `ESN`) | Originele wandelingen (Gert Sonck), code van de site |
| `FW-` | frankwandelt.nl |
| `TT-` / `GW-` | Trage Tochten / Groene Wissels (wandelzoekpagina.nl) |
| `TP-` | Traumpfade / Traumschleifen |
| `MT-` | Mullerthal Trail |
| `WT-` | Wildnis-Trail Eifel |
| `ES-` | EifelSpur |
| `WN-` | wandelnet.nl |
| `WL-` | Wikiloc |
| `SBB-` | Staatsbosbeheer |
| `NM-` | Natuurmonumenten |
| `NS-` | NS wandelen |
| `VZL-` | VisitZuidLimburg |
| `AWD-` | Amsterdamse Waterleidingduinen |
| `PR-` | profirouten.de |
| `GPSW-` | gps-wijzer.nl |
| `KO-` | Komoot (tour-id) |
| `EIG-` | Eigen route of bron onbekend |

### Vaste hindernis-tags

`doorwading`, `rotsklauteren`, `ladder_ketting`, `afgrond_hoogtevrees`, `grot_tunnel_zaklamp`, `steil`, `nat_drassig`, `orientatie_spoorzoeken`, `reuzenberenklauw`, `jachtseizoen`, `omgevallen_bomen`, `prikkeldraad_vee`, plus `begroeiing`, `beekoversteek`, `losliggende_stenen`, `kapotte_brug`, `geen_beschutting`, `verkeer`, `drukte`.

## Export naar NotebookLM

`tools/export_notebook.py` maakt één document per gebiedsgroep en een `master_index` met één regel per route. Die staan als Google Doc en Google Sheet in de Drive-map "Avontuurlijke wandelingen" en worden in NotebookLM als bron toegevoegd. Bij een wijziging worden alleen de betrokken docs bijgewerkt (zelfde bestand, zelfde link).

De omschrijvingen van de bron staan niet in deze openbare repo. Ze komen bij de export uit de Masterlijst in Google Drive en staan alleen in de (privé) docs.

Aanvullingen van Gemini komen als JSON-patch per routecode terug, bijvoorbeeld:

```json
{ "AYW": { "drive_km": 274, "drive_min_sun0800": 177, "hindernissen": ["rotsklauteren"] } }
```

## Plannen

1. ~~Alle wandelingen uit een Strava-export importeren~~ (klaar, 19-11-2026: `tools/import_strava.py`).
2. Bronnen koppelen: frankwandelt.nl, wandelzoekpagina.nl en de overige bronnen; per route omschrijving en GPX.
3. Weer per gebied: voorspelling per uur via Open-Meteo, met een dagkeuze.
4. Oudere wandelingen uit Fitbit toevoegen.
5. Tweede kaart `/fietsen` met MTB-ritten uit Garmin Connect en enduro-trails.
6. Nieuwe Strava-activiteiten automatisch toevoegen met een GitHub Action.
