"""Eenmalige migratie (al uitgevoerd op 19-11-2026; leest het oude v1-formaat en draait daarom niet opnieuw) naar datamodel v2: gebieden.json, routes.json en walks.json.

Bronnen:
- data/walks.json (v1: regions + walks met polyline)
- Masterlijst V2 van Gert Sonck (CSV-export uit Google Drive), pad als argument
- Rijtijden-patch van Gemini (inline hieronder)
"""
import csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
master_csv = Path(sys.argv[1])

# Gebieden: naam, land, kleur, groep (= gebieds-doc voor NotebookLM)
GROEPEN = {
    "ourthe-ambleve": "Ardennen – Ourthe & Amblève",
    "oost-belgie": "Ardennen – Hoge Venen, Vesdre & Oostkantons",
    "semois": "Ardennen – Semois & Anlier",
    "maas-lesse": "Maas, Lesse & Condroz",
    "viroin-henegouwen": "Viroin, Fagne, Samber & Henegouwen",
    "vlaanderen": "Vlaanderen",
    "eifel-moezel-mullerthal": "Eifel, Moezel & Mullerthal",
}
GEBIEDEN = [
    # id, naam, land, kleur, groep
    ("hoge-venen", "Hoge Venen", "België", "#d7263d", "oost-belgie"),
    ("noordeifel", "Noordeifel / Roetgen–Monschau", "Duitsland / België", "#f46036", "eifel-moezel-mullerthal"),
    ("vesdre", "Vesdre / Theux–Spa", "België", "#2e294e", "oost-belgie"),
    ("ambleve", "Amblève", "België", "#1b998b", "ourthe-ambleve"),
    ("ourthe", "Ourthe", "België", "#6a994e", "ourthe-ambleve"),
    ("zuid-eifel", "Zuid-Eifel", "Duitsland", "#8e44ad", "eifel-moezel-mullerthal"),
    ("mullerthal", "Mullerthal", "Luxemburg", "#0077b6", "eifel-moezel-mullerthal"),
    ("moezel", "Moezel / Hunsrück", "Duitsland", "#e09f3e", "eifel-moezel-mullerthal"),
    ("semois", "Semois", "België", "#e84393", "semois"),
    ("oostkantons", "Oostkantons / Our", "België", "#b5179e", "oost-belgie"),
    ("herve-voeren", "Land van Herve / Voeren", "België", "#7f5539", "oost-belgie"),
    ("anlier", "Anlier / Sûre", "België", "#9d4edd", "semois"),
    ("maas", "Maas / Naamse Condroz", "België", "#3a86ff", "maas-lesse"),
    ("lesse", "Lesse / Famenne", "België", "#fb5607", "maas-lesse"),
    ("luikse-condroz", "Luikse Condroz", "België", "#8338ec", "maas-lesse"),
    ("viroin", "Viroin / Fagne / Calestienne", "België", "#ff006e", "viroin-henegouwen"),
    ("samber", "Samber / Entre-Sambre-et-Meuse", "België", "#06d6a0", "viroin-henegouwen"),
    ("henegouwen", "Henegouwen / Waals-Brabant", "België", "#118ab2", "viroin-henegouwen"),
    ("vlaanderen", "Vlaanderen", "België", "#ffbe0b", "vlaanderen"),
]
naam2id = {g[1]: g[0] for g in GEBIEDEN}

# Vrije tekst uit de Masterlijst -> vaste hindernis-tags (afspraak met Gemini, plus extra's uit de data)
HINDERNIS_MAP = [
    (r"steil", ["steil"]),
    (r"oriëntatie|spoorzoeken", ["orientatie_spoorzoeken"]),
    (r"rotsklauteren", ["rotsklauteren"]),
    (r"nat|drassig", ["nat_drassig"]),
    (r"afgrond|hoogtevrees", ["afgrond_hoogtevrees"]),
    (r"doorwading", ["doorwading"]),
    (r"berenklauw", ["reuzenberenklauw"]),
    (r"begroeiing", ["begroeiing"]),
    (r"omgevallen bomen", ["omgevallen_bomen"]),
    (r"losliggende stenen", ["losliggende_stenen"]),
    (r"beekoversteken", ["beekoversteek"]),
    (r"grot|tunnel", ["grot_tunnel_zaklamp"]),
    (r"prikkeldraad|vee", ["prikkeldraad_vee"]),
    (r"kapotte brug", ["kapotte_brug"]),
    (r"jachtseizoen", ["jachtseizoen"]),
    (r"ladder|ketting", ["ladder_ketting"]),
    (r"geen beschutting", ["geen_beschutting"]),
    (r"verkeer", ["verkeer"]),
    (r"drukte", ["drukte"]),
]

def hindernis_tags(tekst):
    tags = []
    for deel in tekst.split(";"):
        kern = re.sub(r"\(.*?\)", "", deel).strip().lower()
        if not kern or kern.startswith("geen bijzondere") or kern.startswith("geen zware"):
            continue
        for patroon, t in HINDERNIS_MAP:
            if re.search(patroon, kern):
                tags += [x for x in t if x not in tags]
    return tags

def num(s, f=float):
    s = (s or "").strip().replace(",", ".")
    return f(s) if s else None

KLEUR_GRAAD = {1: "lichtgroen", 2: "donkergroen", 3: "oranje", 4: "rood", 5: "zwart"}

# Rijtijden (Almere, zondag 08:00) – patch van Gemini, 19-11-2026
RIJTIJDEN = {
    "AYW": {"km": 274, "min": 177},
    "DRE": {"km": 299, "min": 184},
    "YVO": {"km": 296, "min": 187},
    "BOT": {"km": 351, "min": 224},
}

def leeg_route(code):
    return {
        "code": code, "naam": None, "bron": {"naam": None, "url": None},
        "gebied": None, "plaats": None, "start": None,
        "km": None, "hm": None, "graad": None, "graad_kleur": None,
        "kenmerken": [], "hindernissen": [], "hindernissen_toelichting": None,
        "highlights": None, "weersgevoeligheid": None, "varianten": None,
        "rijtijd": None, "gids": None, "gpx_bron": None, "opmerking": None,
    }

routes = {}

# 1. Gert Sonck (Originele wandelingen)
with open(master_csv, encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        code = r["code"].strip()
        rt = leeg_route(code)
        graad = num(r["graad"], int)
        rt.update({
            "naam": r["titel"].strip(),
            "bron": {"naam": "Originele wandelingen (Gert Sonck)", "url": r["bron_url"].strip() or None},
            "gebied": naam2id[r["gebied"].strip()],
            "plaats": r["plaats"].strip().title(),
            "start": [num(r["lat"]), num(r["lon"])] if r["lat"].strip() else None,
            "km": num(r["km"]),
            "graad": graad,
            "graad_kleur": KLEUR_GRAAD.get(graad),
            "hindernissen": hindernis_tags(r["hindernissen"]),
            "hindernissen_toelichting": r["hindernissen"].strip() or None,
            "highlights": r["highlights"].strip() or None,
            "gids": {
                "in_gids_5e_editie": r["in_gids_5e_editie"].strip() == "ja",
                "pagina": r["gids_pagina"].strip() or None,
                "alleen_in_gids": r["alleen_in_gids"].strip() == "ja",
            },
            "gpx_bron": r["gpx"].strip() or None,
            "opmerking": r["opmerking"].strip() or None,
        })
        if "grensoverschrijdend" in r["hindernissen"].lower():
            rt["kenmerken"].append("grensoverschrijdend")
        if code in RIJTIJDEN:
            rt["rijtijd"] = RIJTIJDEN[code]
        routes[code] = rt

# 2. Eigen en overige routes van de gelopen wandelingen (codes met bron-prefix)
#    code: (naam, bron-naam, bron-url, gebied, hindernissen)
EXTRA = {
    "EIG-HOEGNE": ("Vallei van de Hoëgne", "Eigen route", None, "hoge-venen", ["nat_drassig", "steil"]),
    "EIG-OVIFAT-19": ("Hoge Venen – Ovifat (19 km)", "Eigen route", None, "hoge-venen", ["rotsklauteren"]),
    "EIG-OVIFAT-12": ("Hoge Venen – Ovifat (12 km)", "Eigen route", None, "hoge-venen", []),
    "EIG-BOTRANGE-27": ("Hoge Venen – Botrange (27 km)", "Eigen route", None, "hoge-venen", []),
    "KO-905263451": ("Wandeling Petergensfeld", "Komoot", "https://www.komoot.nl/tour/905263451", "noordeifel", []),
    "EIG-RAEREN": ("Raeren – Roetgen", "Eigen route", None, "noordeifel", []),
    "KO-894582602": ("Fuhrtsbachtal", "Komoot", "https://www.komoot.nl/tour/894582602", "noordeifel", []),
    "WT-2": ("Wildnis-Trail etappe 2 (Einruhr – Gemünd)", "Wildnis-Trail Nationalpark Eifel",
             "https://www.thehike.nl/wildernis-trail-wandeling-nationaal-park-eifel/", "noordeifel", ["steil"]),
    "EIG-NINGLINSPO": ("Ninglinspo", "Eigen route", None, "ambleve", []),
    "ES-DAHLEM": ("EifelSpur Dahlemer Quellenpfad", "EifelSpur (eifel.info)",
                  "https://www.eifel.info/wandern/wanderwege/a-eifelspur-dahlemer-quellenpfad", "zuid-eifel", []),
    "MT-2": ("Mullerthal Trail – Route 2", "Mullerthal Trail", None, "mullerthal", []),
    "MT-3": ("Mullerthal Trail – Route 3", "Mullerthal Trail", None, "mullerthal", []),
    "EIG-BERDORF": ("Berdorf", "Eigen route", None, "mullerthal", []),
    "EIG-MAYBACHKLAMM": ("Maybachklamm", "Onbekend", None, "moezel", ["rotsklauteren"]),
    "TP-EHRBACHKLAMM": ("Traumschleife Ehrbachklamm", "Traumpfade / Traumschleifen", None, "moezel",
                        ["rotsklauteren", "steil"]),
    "EIG-BOUILLON": ("Bouillon – Cordemois", "Eigen route", None, "semois", []),
}
for code, (naam, bron, url, gebied, hind) in EXTRA.items():
    rt = leeg_route(code)
    rt.update({"naam": naam, "bron": {"naam": bron, "url": url}, "gebied": gebied, "hindernissen": hind})
    routes[code] = rt

# 3. Walks: koppeling Strava-id -> route, plus eigen notities (zonder links)
KOPPELING = {
    "15169105880": "EIG-HOEGNE", "13024575326": "EIG-HOEGNE",
    "13967326162": "EIG-OVIFAT-19", "7102484192": "EIG-OVIFAT-12", "7266218765": "EIG-BOTRANGE-27",
    "7716395345": "KO-905263451", "7002549983": "EIG-RAEREN", "7671018520": "KO-894582602",
    "8967717435": "WT-2", "13901280680": "FRA", "14755221745": "REI",
    "13760768115": "RUY", "13825615655": "EIG-NINGLINSPO",
    "15103153610": "ESN", "14091208315": "BOM", "14235551384": "WIB",
    "8002585720": "ES-DAHLEM",
    "15480720429": "MT-2", "15493345512": "MT-2", "8032699975": "MT-3", "8037456891": "MT-3",
    "7211658567": "EIG-BERDORF",
    "15952445199": "EIG-MAYBACHKLAMM", "15956110180": "TP-EHRBACHKLAMM",
    "14633565216": "LAC", "7206110682": "EIG-BOUILLON",
}
NOTITIES = {
    "13024575326": "Erg mooie omgeving. Intensieve wandeling met veel rotsen, watervallen, hellingen, boomwortels en vooral veel modder.",
    "13967326162": "Lekker klimmen en klauteren weer. Top!",
    "7716395345": "Ook leuke MTB-route hier (nr 5).",
    "8967717435": "Mooie wandeling! Met pittige klimmetjes. Geparkeerd in Gemünd en toen met de bus naar het startpunt in Einruhr.",
    "13901280680": "Toffe en avontuurlijke wandeling. Aanrader! Gelopen op basis van de omschrijving, soms wat puzzelen maar dat maakt het leuk. Ook een aantal enduro-MTB-paadjes ontdekt.",
    "14755221745": "Erg leuke wandeling, 2 keer rivier overgestoken. Veel steile paden, heel veel mooie uitzichten en overwoekerde paden.",
    "13760768115": "Heel veel hoogtemeters op relatief weinig km. In de eerste 11 km al bijna 500 hm. Verder heel veel water, bronnen en beekjes zonder bruggetjes.",
    "13825615655": "Mooi!",
    "15103153610": "Heftige wandeling. 20% zonder pad op kleine officieuze wildspoortjes die niet op de kaart stonden. Veel klimmen (73% stijgingspercentage), spoorzoeken en glijden bij dalen.",
    "14091208315": "Op basis van diverse versies van De rotsen van Sy. Lekker klimmen en klauteren. Veel grotten en een simpele klettersteig. Aan het eind door een klein afvoertunneltje onder het spoor door.",
    "14235551384": "Superwandeling door ruig terrein. Sommige paden compleet overwoekerd en andere onder water door het constructiewerk van de bevers. Top 10!",
    "8002585720": "Erg mooie en gevarieerde wandeling. Meanderende beekjes!",
    "15480720429": "Mooie wandeling weer. Morgen rondje afmaken en weer naar Echternach.",
    "15493345512": "Wat een mooie wandeling. Tweede deel alleen gelopen en veel kloven verkend.",
    "8032699975": "Wandeling in een van de mooiste gebieden van Europa! Morgen deel 2.",
    "8037456891": "GPS-opname halverwege gestopt.",
    "15952445199": "Erg mooie kloof en leuke klimpassages! Toproute! Stukje begin niet opgenomen.",
    "15956110180": "Wat een topwandeling. Hele ruige kloven en supersteile wanden waar je soms recht omhoog moet klimmen. Aanrader!",
    "14633565216": "Heel veel groen en twee keer tot mijn middel door de Semois heen, 1x 70 m doorwaden en 1x 20 m. Verder leuke klimstukken steil en recht omhoog.",
}

v1 = json.loads((ROOT / "data/walks.json").read_text(encoding="utf-8"))
walks = []
for w in v1["walks"]:
    walks.append({
        "strava_id": w["id"], "route": KOPPELING[w["id"]], "naam": w["name"], "datum": w["date"],
        "km": w["km"], "hm": w["hm"], "notities": NOTITIES.get(w["id"]), "polyline": w["polyline"],
    })
assert all(w["route"] in routes for w in walks)

# Afstand/hoogtemeters van eigen routes overnemen uit de (langste) gelopen versie
for code, rt in routes.items():
    ws = [w for w in walks if w["route"] == code]
    if ws and rt["km"] is None:
        langste = max(ws, key=lambda w: w["km"])
        rt["km"], rt["hm"] = langste["km"], langste["hm"]

gebieden = [{"id": i, "naam": n, "land": l, "kleur": k, "groep": g} for i, n, l, k, g in GEBIEDEN]
groepen = [{"id": k, "naam": v} for k, v in GROEPEN.items()]

def dump(name, obj):
    (ROOT / "data" / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

dump("gebieden.json", {"groepen": groepen, "gebieden": gebieden})
dump("routes.json", sorted(routes.values(), key=lambda r: r["code"]))
dump("walks.json", sorted(walks, key=lambda w: w["datum"], reverse=True))
print(len(routes), "routes,", len(walks), "walks,", len(gebieden), "gebieden")
