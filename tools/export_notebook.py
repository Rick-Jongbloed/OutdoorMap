"""Export voor NotebookLM: één document per gebiedsgroep en een master_index.

Gebruik:
  python tools/export_notebook.py --omschrijvingen masterlijst.csv --out out/notebook

Schrijft per groep:
  <groep>.html   voor het eerste aanmaken van de Google Doc (Drive zet HTML om naar Docs-opmaak)
  <groep>.txt    platte tekst, dezelfde inhoud
  <groep>.headings.json  koppen met niveau, voor het bijwerken van een bestaande Doc
en master_index.csv met één regel metadata per route.

De omschrijvingen van de bron staan niet in de openbare repo; ze worden bij de export
gelezen uit de Masterlijst (CSV-export van de Google Sheet in Drive).
"""
import argparse, csv, html, json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--omschrijvingen", help="CSV met kolommen code en omschrijving")
ap.add_argument("--out", default=str(ROOT / "out/notebook"))
args = ap.parse_args()

geb = json.loads((ROOT / "data/gebieden.json").read_text(encoding="utf-8"))
routes = json.loads((ROOT / "data/routes.json").read_text(encoding="utf-8"))
walks = json.loads((ROOT / "data/walks.json").read_text(encoding="utf-8"))
gebied = {g["id"]: g for g in geb["gebieden"]}

omschrijving = {}
if args.omschrijvingen:
    with open(args.omschrijvingen, encoding="utf-8") as fh:
        omschrijving = {r["code"].strip(): r["omschrijving"].strip() for r in csv.DictReader(fh)}

per_route = {}
for w in sorted(walks, key=lambda w: w["datum"]):
    per_route.setdefault(w["route"], []).append(w)

ONBEKEND = "onbekend"

def km(v):
    return ONBEKEND if v is None else f"{v:g}".replace(".", ",") + " km"

def status(code):
    ws = per_route.get(code, [])
    return f"GELOPEN ({len(ws)}x – laatst: {ws[-1]['datum']})" if ws else "NOG NIET GELOPEN"

def route_blok(r):
    g = gebied[r["gebied"]]
    ws = per_route.get(r["code"], [])
    plaats = f" · Plaats: {r['plaats']}" if r["plaats"] else ""
    start = f" · Start: {r['start'][0]}, {r['start'][1]}" if r["start"] else ""
    bron = r["bron"]["naam"] or ONBEKEND
    if r.get("gids") and r["gids"]["in_gids_5e_editie"]:
        bron += " – gids 5e editie" + (f" p. {r['gids']['pagina']}" if r["gids"]["pagina"] else "")
    if r["bron"]["url"]:
        bron += f" – {r['bron']['url']}"
    graad = f"{r['graad']} ({r['graad_kleur']})" if r["graad"] else ONBEKEND
    rij = f"{r['rijtijd']['min'] // 60}u {r['rijtijd']['min'] % 60:02d}m ({r['rijtijd']['km']} km)" if r["rijtijd"] else ONBEKEND
    hind = ", ".join(r["hindernissen"]) if r["hindernissen"] else "geen bekend"
    regels = [
        f"Status: {status(r['code'])}",
        f"Gebied: {g['naam']} ({g['land']}){plaats}{start}",
        f"Bron: {bron}",
        f"Afstand: {km(r['km'])} · Hoogtemeters: {r['hm'] or ONBEKEND} · Graad: {graad} · Rijtijd (Almere zo 08:00): {rij}",
        f"Kenmerken: {', '.join(r['kenmerken']) if r['kenmerken'] else 'nog niet ingevuld'}",
        f"Hindernissen: {hind}",
    ]
    if r["hindernissen_toelichting"]:
        regels.append(f"Toelichting hindernissen: {r['hindernissen_toelichting']}")
    if r["highlights"]:
        regels.append(f"Highlights: {r['highlights']}")
    regels.append(f"Weersgevoeligheid: {r['weersgevoeligheid'] or ONBEKEND}")
    regels.append(f"Varianten: {r['varianten'] or ONBEKEND}")
    for w in ws:
        regels.append(f"Gelopen: {w['datum']} ({km(w['km'])}, {w['hm']} hm) – Strava {w['strava_id']}")
        if w["notities"]:
            regels.append(f"Mijn notities ({w['datum']}): {w['notities']}")
    if omschrijving.get(r["code"]):
        regels.append(f"Omschrijving: {omschrijving[r['code']]}")
    if r["gpx_bron"]:
        regels.append(f"GPX: {r['gpx_bron']}")
    if r["opmerking"]:
        regels.append(f"Opmerking: {r['opmerking']}")
    return f"{r['code']} – {r['naam']}", regels

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
vandaag = date.today().isoformat()

for groep in geb["groepen"]:
    leden = [g for g in geb["gebieden"] if g["groep"] == groep["id"]]
    blokken = []  # (niveau, tekst) ; niveau 0 = gewone regel
    blokken.append((1, groep["naam"]))
    blokken.append((0, f"Export uit OutdoorMap (GitHub) van {vandaag}. Niet handmatig aanpassen: wijzigingen gaan via de repo. "
                       f"Gebieden in dit document: {', '.join(g['naam'] for g in leden)}."))
    for g in leden:
        rs = sorted((r for r in routes if r["gebied"] == g["id"]), key=lambda r: r["code"])
        if not rs:
            continue
        blokken.append((2, f"{g['naam']} ({g['land']})"))
        for r in rs:
            kop, regels = route_blok(r)
            blokken.append((3, kop))
            blokken += [(0, t) for t in regels]

    tekst = "\n".join(t for _, t in blokken) + "\n"
    (out / f"{groep['id']}.txt").write_text(tekst, encoding="utf-8")
    (out / f"{groep['id']}.headings.json").write_text(
        json.dumps([{"niveau": n, "tekst": t} for n, t in blokken if n], ensure_ascii=False, indent=1), encoding="utf-8")
    h = ["<html><body>"]
    for n, t in blokken:
        h.append(f"<h{n}>{html.escape(t)}</h{n}>" if n else f"<p>{html.escape(t)}</p>")
    h.append("</body></html>")
    (out / f"{groep['id']}.html").write_text("\n".join(h), encoding="utf-8")
    print(f"{groep['id']}: {sum(1 for n, _ in blokken if n == 3)} routes, {len(tekst.split())} woorden")

# master_index
kolommen = ["code", "naam", "groep", "gebied", "land", "plaats", "lat", "lon", "status", "keer_gelopen",
            "laatst_gelopen", "km", "hm", "graad", "graad_kleur", "bron", "bron_url", "rijtijd_km",
            "rijtijd_min_zo0800", "kenmerken", "hindernissen", "weersgevoeligheid", "in_gids_5e_editie",
            "gids_pagina", "strava_ids"]
groepnaam = {g["id"]: g["naam"] for g in geb["groepen"]}
with open(out / "master_index.csv", "w", encoding="utf-8", newline="") as fh:
    wr = csv.writer(fh)
    wr.writerow(kolommen)
    for r in sorted(routes, key=lambda r: (gebied[r["gebied"]]["groep"], r["gebied"], r["code"])):
        g = gebied[r["gebied"]]
        ws = per_route.get(r["code"], [])
        wr.writerow([
            r["code"], r["naam"], groepnaam[g["groep"]], g["naam"], g["land"], r["plaats"] or "",
            r["start"][0] if r["start"] else "", r["start"][1] if r["start"] else "",
            "GELOPEN" if ws else "NOG NIET GELOPEN", len(ws), ws[-1]["datum"] if ws else "",
            r["km"] if r["km"] is not None else "", r["hm"] or "", r["graad"] or "", r["graad_kleur"] or "",
            r["bron"]["naam"] or "", r["bron"]["url"] or "",
            r["rijtijd"]["km"] if r["rijtijd"] else "", r["rijtijd"]["min"] if r["rijtijd"] else "",
            ", ".join(r["kenmerken"]), ", ".join(r["hindernissen"]), r["weersgevoeligheid"] or "",
            "ja" if r.get("gids") and r["gids"]["in_gids_5e_editie"] else "nee",
            (r.get("gids") or {}).get("pagina") or "", " ".join(w["strava_id"] for w in ws),
        ])
print("master_index.csv:", len(routes), "routes")
