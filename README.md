# OutdoorMap

Persoonlijke kaart van mijn wandelingen, ingedeeld per gebied, met datum, afstand en hoogtemeters uit Strava.

**Live:** https://rick-jongbloed.github.io/OutdoorMap/

## Wat staat erop

- Wandelingen in de Ardennen, Eifel, Mullerthal, Moezel/Hunsrück en Semois, ingedeeld in 9 gebieden met het land erbij.
- Kaartlagen: OSM, topo (OpenTopoMap), satelliet (Esri) en een laag met bewegwijzerde wandelroutes (Waymarked Trails).
- Lijst per gebied, nieuwste wandeling bovenaan. Klik op een gebied of wandeling om in te zoomen; de popup linkt naar de activiteit in Strava.

## Opbouw

Statische site zonder server of build-stap.

| Pad | Inhoud |
|---|---|
| `index.html` | De pagina |
| `css/style.css` | Opmaak, ook voor telefoon |
| `js/app.js` | Kaart, lagen en lijst |
| `data/walks.json` | Gebieden en wandelingen (track als encoded polyline) |
| `vendor/leaflet/` | Leaflet 1.9.4 |

Lokaal bekijken: start een simpele webserver in de map, bijvoorbeeld `python -m http.server`, en open `http://localhost:8000`. Direct openen als bestand werkt niet, omdat de browser `data/walks.json` dan niet mag laden.

Publiceren gaat via GitHub Pages vanaf branch `main` (root): elke push staat binnen een paar minuten online.

## Plannen

1. Alle wandelingen uit een Strava-export importeren, inclusief Nederland (vanaf 3 km, zonder rondjes rond huis en dubbele opnames).
2. Datamodel splitsen in routes en keren gelopen:
   - `routes.json`: de route met bron (frankwandelt.nl, wandelzoekpagina.nl, Originele wandelingen, Traumpfade, enz.), omschrijving en GPX.
   - `walks.json`: elke keer dat een route gelopen is, met datum en Strava-id.
3. Weer per gebied: voorspelling per uur via Open-Meteo, met een dagkeuze om te zien waar het het beste wandelweer is.
4. Doorzoekbaar maken in Google NotebookLM: per route een tekstbestand met naam, gebied, bron, omschrijving en gelopen datums.
5. Oudere wandelingen uit Fitbit toevoegen.
6. Tweede kaart `/fietsen` met MTB-ritten uit Garmin Connect en enduro-trails.
7. Nieuwe Strava-activiteiten automatisch toevoegen met een GitHub Action.
