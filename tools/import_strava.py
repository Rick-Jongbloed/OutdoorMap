#!/usr/bin/env python3
"""Importeert geselecteerde Strava-wandelingen in data/gebieden.json, routes.json en walks.json.

Gebruik:
  python tools/import_strava.py --selectie selectie.csv --export <uitgepakte-export> \
      --originelen <doelmap voor trackbestanden> [--repo .] [--dry-run]

Invoer: selectie.csv (kolom status = houden) en de uitgepakte Strava-export
(activities.csv + activities/). Vereist: pip install fitdecode.

Per wandeling: track inlezen (gpx, tcx of fit, ook .gz), vereenvoudigen (Douglas-Peucker,
5 m) en coderen als Google encoded polyline (precisie 5). Herhaald gelopen routes worden
herkend op start/eind binnen 300 m en grote overlap van de track; die worden één route met
meerdere walks. De originele trackbestanden worden naar --originelen gekopieerd en gaan
niet in de repo.
"""
import argparse, csv, gzip, io, json, math, re, shutil, sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ap = argparse.ArgumentParser()
ap.add_argument("--selectie", required=True)
ap.add_argument("--export", required=True)
ap.add_argument("--originelen", required=True)
ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
ap.add_argument("--uitsluiten", default="", help="komma-gescheiden strava_id's om over te slaan")
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--diag", action="store_true", help="toon bijna-gelijke paren")
ap.add_argument("--diag-naam", default="", help="regex: toon alle paren waarvan beide namen matchen")
args = ap.parse_args()

REPO = Path(args.repo)
EXPORT = Path(args.export)
M_LAT = 110540.0

# ---------- geometrie ----------

def kx(lat):
    return 111320.0 * math.cos(math.radians(lat))

def dist(p, q):
    lat0 = p[0]
    return math.hypot((q[1] - p[1]) * kx(lat0), (q[0] - p[0]) * M_LAT)

def dp_indices(xy, tol):
    n = len(xy)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = xy[a]; bx, by = xy[b]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        best, bi = -1.0, None
        for i in range(a + 1, b):
            px, py = xy[i]
            if L2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack.append((a, bi)); stack.append((bi, b))
    return [i for i in range(n) if keep[i]]

def simplify(pts, tol=5.0):
    lat0 = sum(p[0] for p in pts) / len(pts)
    lon0 = pts[0][1]
    k = kx(lat0)
    xy = [((lo - lon0) * k, (la - lat0) * M_LAT) for la, lo in pts]
    return [pts[i] for i in dp_indices(xy, tol)]

def enc_polyline(pts):
    out, plat, plon = [], 0, 0
    for la, lo in pts:
        ila, ilo = round(la * 1e5), round(lo * 1e5)
        for v in (ila - plat, ilo - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63)); v >>= 5
            out.append(chr(v + 63))
        plat, plon = ila, ilo
    return "".join(out)

def dec_polyline(s):
    pts, i, lat, lon = [], 0, 0, 0
    while i < len(s):
        for which in (0, 1):
            shift = res = 0
            while True:
                b = ord(s[i]) - 63; i += 1
                res |= (b & 0x1F) << shift; shift += 5
                if b < 0x20:
                    break
            d = ~(res >> 1) if res & 1 else res >> 1
            if which == 0: lat += d
            else: lon += d
        pts.append((lat / 1e5, lon / 1e5))
    return pts

def resample(pts, step=25.0):
    out = [pts[0]]
    acc = 0.0
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = dist(a, b)
        total += seg
        if seg == 0:
            continue
        pos = step - acc
        while pos <= seg:
            t = pos / seg
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            pos += step
        acc = (acc + seg) % step
    out.append(pts[-1])
    return out, total

def containment(S, L, tol=50.0):
    """Aandeel van de punten van S dat binnen tol meter van een punt van L ligt."""
    lat0 = S[0][0]; k = kx(lat0)
    grid = {}
    for la, lo in L:
        grid.setdefault((int((lo * k) // tol), int((la * M_LAT) // tol)), []).append((lo * k, la * M_LAT))
    hit = 0
    for la, lo in S:
        x, y = lo * k, la * M_LAT
        cx, cy = int(x // tol), int(y // tol)
        ok = False
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for (qx, qy) in grid.get((gx, gy), ()):
                    if math.hypot(qx - x, qy - y) <= tol:
                        ok = True; break
                if ok: break
            if ok: break
        hit += ok
    return hit / len(S)

# ---------- tracks lezen ----------

def read_track(path):
    name = path.name
    opener = gzip.open if name.endswith(".gz") else open
    base = name[:-3] if name.endswith(".gz") else name
    ext = base.rsplit(".", 1)[-1].lower()
    pts = []
    if ext == "fit":
        import fitdecode
        with opener(path, "rb") as fh, fitdecode.FitReader(fh) as fr:
            for fr_ in fr:
                if isinstance(fr_, fitdecode.FitDataMessage) and fr_.name == "record":
                    la = fr_.get_value("position_lat", fallback=None)
                    lo = fr_.get_value("position_long", fallback=None)
                    if la is not None and lo is not None:
                        pts.append((la * 180 / 2**31, lo * 180 / 2**31))
    elif ext == "gpx":
        with opener(path, "rb") as fh:
            for _, el in ET.iterparse(io.BytesIO(fh.read().lstrip()), events=("end",)):
                if el.tag.split("}")[-1] == "trkpt":
                    pts.append((float(el.attrib["lat"]), float(el.attrib["lon"])))
                    el.clear()
    elif ext == "tcx":
        with opener(path, "rb") as fh:
            for _, el in ET.iterparse(io.BytesIO(fh.read().lstrip()), events=("end",)):
                if el.tag.split("}")[-1] == "Position":
                    d = {c.tag.split("}")[-1]: c.text for c in el}
                    if d.get("LatitudeDegrees") and d.get("LongitudeDegrees"):
                        pts.append((float(d["LatitudeDegrees"]), float(d["LongitudeDegrees"])))
                    el.clear()
    else:
        raise ValueError(f"onbekend type {name}")
    pts = [p for p in pts if abs(p[0]) > 0.01 and abs(p[1]) > 0.01]
    return pts, base.split(".", 1)[1] if "." in base else ext, name.split(".", 1)[1]

# ---------- bronlinks ----------

PREFIX = {
    "wandelnet.nl": ("WN", "wandelnet.nl"),
    "nl.wikiloc.com": ("WL", "Wikiloc"),
    "wikiloc.com": ("WL", "Wikiloc"),
    "staatsbosbeheer.nl": ("SBB", "Staatsbosbeheer"),
    "natuurmonumenten.nl": ("NM", "Natuurmonumenten"),
    "ns.nl": ("NS", "NS wandelen"),
    "visitzuidlimburg.nl": ("VZL", "VisitZuidLimburg"),
    "awd.waternet.nl": ("AWD", "Amsterdamse Waterleidingduinen (Waternet)"),
    "profirouten.de": ("PR", "profirouten.de"),
    "gps-wijzer.nl": ("GPSW", "gps-wijzer.nl"),
    "thehike.nl": ("TH", "thehike.nl"),
    "eifel.info": ("ES", "EifelSpur (eifel.info)"),
}

def link_info(url):
    """-> (code, bronnaam, schone url) of None als de link geen specifieke route aanwijst."""
    if not url:
        return None
    u = urlparse(url.strip())
    host = u.netloc.lower().removeprefix("www.")
    segs = [s for s in u.path.split("/") if s]
    clean = f"{u.scheme}://{u.netloc}{u.path}"
    if not segs and host != "originelewandelingen.be":
        return None
    if host == "frankwandelt.nl":
        return "FW-" + segs[-1], "frankwandelt.nl", clean
    if host == "wandelzoekpagina.nl" and len(segs) >= 3:
        slug, wid = segs[1], segs[2]
        pre = "TT" if "trage-tocht" in slug else "GW"
        return f"{pre}-{wid}", "wandelzoekpagina.nl", clean
    if host == "komoot.nl" and "tour" in segs:
        tid = segs[segs.index("tour") + 1]
        return f"KO-{tid}", "Komoot", f"https://www.komoot.nl/tour/{tid}"
    if host == "originelewandelingen.be":
        keuze = parse_qs(u.query).get("keuze")
        if keuze:
            return keuze[0].upper(), "Originele wandelingen (Gert Sonck)", url.strip()
        return None
    if host in PREFIX:
        pre, naam = PREFIX[host]
        last = re.sub(r"\.html?$", "", segs[-1])
        if host == "wandelnet.nl" and len(segs) >= 2:
            last = segs[1]
        elif host in ("nl.wikiloc.com", "wikiloc.com"):
            m = re.search(r"(\d+)$", last)
            last = m.group(1) if m else last
        elif host == "natuurmonumenten.nl" and len(segs) >= 2:
            last = f"{segs[1]}-{segs[-1]}"
        elif host == "visitzuidlimburg.nl":
            last = last[:50]
        return f"{pre}-{last}", naam, clean
    return None

# ---------- gebieden ----------

NIEUWE_GEBIEDEN = [
    ("veluwezoom", "Veluwezoom", "Nederland", "#2d6a4f"),
    ("zuid-veluwe", "Zuid-Veluwe", "Nederland", "#52b788"),
    ("veluwe", "Veluwe", "Nederland", "#bc6c25"),
    ("utrechtse-heuvelrug", "Utrechtse Heuvelrug", "Nederland", "#606c38"),
    ("rijk-van-nijmegen", "Rijk van Nijmegen", "Nederland", "#c9184a"),
    ("oost-nederland", "Oost-Nederland", "Nederland", "#a4161a"),
    ("zuid-limburg", "Zuid-Limburg", "Nederland", "#f77f00"),
    ("noord-midden-limburg", "Noord- en Midden-Limburg", "Nederland", "#577590"),
    ("noord-brabant", "Noord-Brabant", "Nederland", "#3f37c9"),
    ("flevoland", "Flevoland", "Nederland", "#4cc9f0"),
    ("drenthe", "Drenthe", "Nederland", "#9c6644"),
    ("noord-hollandse-duinen", "Noord-Hollandse duinen", "Nederland", "#e9c46a"),
    ("oostenrijk", "Oostenrijk", "Oostenrijk", "#ae2012"),
    ("zwitserland", "Zwitserland", "Zwitserland", "#0a9396"),
    ("sauerland", "Sauerland", "Duitsland", "#3d5a80"),
    ("harz", "Harz", "Duitsland", "#99582a"),
    ("overig-buitenland", "Overig buitenland", "Diverse landen", "#8d99ae"),
]
NL_MAP = {
    "Veluwezoom": "veluwezoom", "Rijk van Nijmegen": "rijk-van-nijmegen", "Veluwe": "veluwe",
    "Flevoland": "flevoland", "Utrechtse Heuvelrug": "utrechtse-heuvelrug", "Drenthe": "drenthe",
    "Noord-Hollandse duinen": "noord-hollandse-duinen", "Oost-Nederland": "oost-nederland",
    "Zuid-Limburg": "zuid-limburg", "Noord-Brabant": "noord-brabant",
    "Noord- en Midden-Limburg": "noord-midden-limburg", "Gooi": "utrechtse-heuvelrug",
}
EXT_MAP = {
    "Hoge Venen": "hoge-venen", "Vesdre": "vesdre", "Ourthe": "ourthe", "Semois": "semois",
    "Moezel": "moezel", "Noordeifel": "noordeifel", "Zuid-Eifel": "zuid-eifel", "Mullerthal": "mullerthal",
}

def gebied_van(row, lat, lon, routes):
    land, vg = row["land"], row["voorgesteld_gebied"]
    if land == "NL":
        for k, v in NL_MAP.items():
            if vg.startswith(k):
                return v
        if lat > 52.6 and lon < 4.9: return "noord-hollandse-duinen"
        if 51.9 <= lat <= 52.1 and lon < 5.6: return "utrechtse-heuvelrug"
        if 51.9 <= lat <= 52.05 and 5.6 <= lon < 5.9: return "zuid-veluwe"
        if 52.2 <= lat <= 52.45 and 5.85 <= lon < 6.1: return "veluwe"
        if lat > 52.7 and 5.9 <= lon < 6.4: return "oost-nederland"
        return None
    for k, v in EXT_MAP.items():
        if vg.startswith(k):
            return v
    if land == "AT": return "oostenrijk"
    if land == "CH": return "zwitserland"
    if land == "DE":
        if 51.0 <= lat <= 51.4 and 7.9 <= lon <= 8.8: return "sauerland"
        if 51.6 <= lat <= 52.0 and 10.3 <= lon <= 11.2: return "harz"
        return "overig-buitenland"
    if land in ("BE", "LU"):
        best = min((r for r in routes if r.get("start")), key=lambda r: dist((lat, lon), r["start"]))
        return best["gebied"]
    return "overig-buitenland"

# ---------- hulpfuncties ----------

GENERIEK = re.compile(r"^(\d{4}-\d{2}-\d{2}|(afternoon|morning|lunch|evening|night)\s+(hike|walk)|walk|hike|"
                      r"(middag|avond|ochtend|namiddag)wandeling(etje)?|wandeling)\b", re.I)

def slug(s):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.upper()).strip("-")
    return s[:24].rstrip("-")

def notities(t):
    t = re.sub(r"https?://\S+", "", t or "")
    t = re.sub(r"\s+", " ", t).strip()
    out = " ".join(re.split(r"(?<=[.!?])\s+", t)[:3])
    if len(out) > 300:
        out = out[:297].rsplit(" ", 1)[0] + "…"
    return out

def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

# ---------- hoofdprogramma ----------

geb = json.loads((REPO / "data/gebieden.json").read_text(encoding="utf-8"))
routes = json.loads((REPO / "data/routes.json").read_text(encoding="utf-8"))
walks = json.loads((REPO / "data/walks.json").read_text(encoding="utf-8"))
n_routes0, n_walks0 = len(routes), len(walks)
have_ids = {w["strava_id"] for w in walks}
skip_ids = {s.strip() for s in args.uitsluiten.split(",") if s.strip()}
GNAAM = {g["id"]: g["naam"] for g in geb["gebieden"]}
GNAAM.update({x[0]: x[1] for x in NIEUWE_GEBIEDEN})
route_by_code = {r["code"]: r for r in routes}
route_by_url = {r["bron"]["url"]: r["code"] for r in routes if r["bron"].get("url")}

with open(EXPORT / "activities.csv", encoding="utf-8", newline="") as fh:
    rd = csv.reader(fh); next(rd)
    omschr = {row[0]: row[4] for row in rd if len(row) > 4}

with open(args.selectie, encoding="utf-8-sig", newline="") as fh:
    rows = [r for r in csv.DictReader(fh, delimiter=";") if r["status"] == "houden"]

nieuw, warn = [], []
for r in rows:
    sid = r["strava_id"]
    if sid in have_ids or sid in skip_ids:
        continue
    pts, ext, fullext = read_track(EXPORT / r["trackbestand"])
    if len(pts) < 10:
        warn.append(f"{sid}: track met {len(pts)} punten, overgeslagen"); continue
    simp = simplify(pts, 5.0)
    res, length = resample(pts)
    li = link_info(r["link_in_omschrijving"])
    g = gebied_van(r, pts[0][0], pts[0][1], routes)
    if g is None:
        warn.append(f"{sid}: geen gebied ({r['naam'][:25]})"); continue
    nieuw.append(dict(sid=sid, row=r, pts=pts, simp=simp, res=res, length=length, link=li,
                      gebied=g, start=pts[0], end=pts[-1], datum=r["datum"], ext=fullext,
                      src=EXPORT / r["trackbestand"], km=float(r["km"]), hm=int(float(r["hm"] or 0))))

# bestaande walks als vergelijkingsmateriaal
bestaand = []
for w in walks:
    if w.get("polyline"):
        p = dec_polyline(w["polyline"])
        if len(p) > 3:
            res, length = resample(p)
            bestaand.append(dict(sid=w["strava_id"], route=w["route"], datum=w["datum"], start=p[0], end=p[-1], res=res, length=length))

def bbox(res):
    la = [p[0] for p in res]; lo = [p[1] for p in res]
    return min(la), max(la), min(lo), max(lo)

def gelijk(a, b):
    """Zelfde route? Nooit op dezelfde dag. Strikt: start en eind binnen 300 m en overlap.
    Soepel: dezelfde lus met een andere start (zeer grote overlap)."""
    if a.get("datum") and a["datum"] == b.get("datum"):
        return False
    ba, bb = a.setdefault("bbox", bbox(a["res"])), b.setdefault("bbox", bbox(b["res"]))
    m = 0.001
    if ba[1] + m < bb[0] or bb[1] + m < ba[0] or ba[3] + m < bb[2] or bb[3] + m < ba[2]:
        return False
    S, L = (a, b) if a["length"] <= b["length"] else (b, a)
    c1 = containment(S["res"], L["res"]); c2 = containment(L["res"], S["res"])
    se = (dist(a["start"], b["start"]) <= 300 and dist(a["end"], b["end"]) <= 300) or \
         (dist(a["start"], b["end"]) <= 300 and dist(a["end"], b["start"]) <= 300)
    if se and c1 >= 0.7 and c2 >= 0.6:
        return True
    return (c1 >= 0.9 and c2 >= 0.55) or (c1 >= 0.85 and c2 >= 0.75)

if args.diag_naam:
    rx = re.compile(args.diag_naam, re.I)
    for i in range(len(nieuw)):
        for j in range(i):
            a, b = nieuw[i], nieuw[j]
            if rx.search(a["row"]["naam"]) and rx.search(b["row"]["naam"]):
                S, L = (a, b) if a["length"] <= b["length"] else (b, a)
                print(f"{a['datum']} {a['row']['naam'][:14]:14} {a['km']:5.1f} | {b['datum']} {b['row']['naam'][:14]:14} {b['km']:5.1f} | ds {dist(a['start'], b['start']):5.0f} de {dist(a['end'], b['end']):5.0f} c {containment(S['res'], L['res']):.2f}/{containment(L['res'], S['res']):.2f}")
if args.diag:
    n = 0
    for i in range(len(nieuw)):
        for j in range(i):
            a, b = nieuw[i], nieuw[j]
            ds = dist(a["start"], b["start"]); de = dist(a["end"], b["end"])
            if ds <= 300 and not gelijk(a, b) and n < 40:
                S, L = (a, b) if a["length"] <= b["length"] else (b, a)
                n += 1
                print(f"{a['datum']} {a['row']['naam'][:16]:16} {a['km']:5.1f} | {b['datum']} {b['row']['naam'][:16]:16} {b['km']:5.1f} | ds {ds:4.0f} de {de:5.0f} c {containment(S['res'], L['res']):.2f}/{containment(L['res'], S['res']):.2f}")

# union-find over nieuwe walks
parent = list(range(len(nieuw)))
def find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]; i = parent[i]
    return i
for i in range(len(nieuw)):
    for j in range(i):
        a, b = nieuw[i], nieuw[j]
        ca = a["link"][0] if a["link"] else None
        cb = b["link"][0] if b["link"] else None
        same_code = ca and ca == cb
        if (ca and cb and ca != cb):
            continue
        if same_code or gelijk(a, b):
            parent[find(i)] = find(j)
clusters = {}
for i, w in enumerate(nieuw):
    clusters.setdefault(find(i), []).append(w)

nieuwe_routes, nieuwe_walks, aan_bestaand = [], [], 0
gebruikt = set(route_by_code)
for members in clusters.values():
    members.sort(key=lambda w: (w["datum"], w["sid"]))
    oud, lang = members[0], max(members, key=lambda w: w["km"])
    codes = {w["link"][0] for w in members if w["link"]}
    if len(codes) > 1:
        warn.append(f"cluster met meerdere linkcodes {sorted(codes)}")
    link = next((w["link"] for w in members if w["link"]), None)
    code = None
    if link:
        code = route_by_url.get(link[2], link[0])
    if code is None:  # overlap met een bestaande walk?
        for w in members:
            for b in bestaand:
                if gelijk(w, b):
                    code = b["route"]; break
            if code: break
    if code in route_by_code:
        aan_bestaand += 1
    else:
        if code is None:
            gnaam = GNAAM.get(oud["gebied"], oud["gebied"])
            base = "EIG-" + (slug(gnaam) + "-" + oud["datum"].replace("-", "") if GENERIEK.match(oud["row"]["naam"]) else slug(oud["row"]["naam"]))
            code, n = base, 2
            while code in gebruikt:
                code = f"{base}-{n}"; n += 1
        naam = oud["row"]["naam"].strip()
        if GENERIEK.match(naam):
            gnaam = GNAAM.get(oud["gebied"], oud["gebied"])
            naam = f"Wandeling {gnaam} ({oud['datum']})"
        bron = {"naam": link[1], "url": link[2]} if link else {"naam": "Onbekend", "url": None}
        rt = {"code": code, "naam": naam, "bron": bron, "gebied": oud["gebied"], "plaats": None,
              "start": [round(oud["start"][0], 5), round(oud["start"][1], 5)], "km": round(lang["km"], 1),
              "hm": lang["hm"], "graad": None, "graad_kleur": None, "kenmerken": [], "hindernissen": [],
              "hindernissen_toelichting": None, "highlights": None, "weersgevoeligheid": None,
              "varianten": None, "rijtijd": None, "gids": None, "gpx_bron": None, "opmerking": None}
        routes.append(rt); route_by_code[code] = rt; nieuwe_routes.append(rt)
    gebruikt.add(code)
    for w in members:
        nieuwe_walks.append({"strava_id": w["sid"], "route": code, "naam": w["row"]["naam"].strip(),
                             "datum": w["datum"], "km": round(w["km"], 2), "hm": w["hm"],
                             "notities": notities(omschr.get(w["sid"], "")),
                             "polyline": enc_polyline(w["simp"])})
        w["code"] = code

walks = walks + nieuwe_walks
walks.sort(key=lambda w: w["datum"], reverse=True)

# gebieden en groepen
bekend = {g["id"] for g in geb["gebieden"]}
gebruikte = {r["gebied"] for r in nieuwe_routes}
for gid, naam, land, kleur in NIEUWE_GEBIEDEN:
    if gid in gebruikte and gid not in bekend:
        geb["gebieden"].append({"id": gid, "naam": naam, "land": land, "kleur": kleur, "groep": gid})
        geb["groepen"].append({"id": gid, "naam": naam if land != "Nederland" else f"Nederland – {naam}"})

# rapport
print(f"nieuwe walks: {len(nieuwe_walks)}  nieuwe routes: {len(nieuwe_routes)}  clusters aan bestaande route: {aan_bestaand}")
print("walks totaal:", len(walks), " routes totaal:", len(routes))
per_g = {}
for r in nieuwe_routes: per_g.setdefault(r["gebied"], [0, 0])[0] += 1
for w in nieuwe_walks: per_g.setdefault(route_by_code[w["route"]]["gebied"], [0, 0])[1] += 1
print("gebied: routes/walks")
for k, v in sorted(per_g.items()): print(f"  {k}: {v[0]}/{v[1]}")
pre = {}
for r in nieuwe_routes: pre[r["code"].split("-")[0]] = pre.get(r["code"].split("-")[0], 0) + 1
print("prefixen:", pre)
herh = {}
for w in nieuwe_walks: herh.setdefault(w["route"], []).append(w)
print("herhaald gelopen (route: aantal, naam):")
for c, ws in sorted(herh.items(), key=lambda x: -len(x[1])):
    if len(ws) > 1 or c in [r["code"] for r in routes[:n_routes0]]:
        print(f"  {c[:34]}: {len(ws)}x  {route_by_code[c]['naam'][:30]}")
for x in warn: print("WAARSCHUWING:", x)
print("polyline totaal bytes:", sum(len(w["polyline"]) for w in nieuwe_walks))

if args.dry_run:
    sys.exit(0)

dump(REPO / "data/gebieden.json", geb)
dump(REPO / "data/routes.json", routes)
dump(REPO / "data/walks.json", walks)
out = Path(args.originelen)
for w in nieuw:
    if "code" not in w: continue
    dst = out / w["datum"][:4] / f"{w['sid']}.{w['ext']}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(w["src"], dst)
print("klaar; originelen gekopieerd naar", out)
