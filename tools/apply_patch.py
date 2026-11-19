"""Verwerk een JSON-patch van Gemini (per routecode) in data/routes.json en data/walks.json.

Gebruik: python tools/apply_patch.py patch.json [--review review.csv]

- zekerheid hoog/middel: bron, code (nieuwe_code), kenmerken, hindernissen,
  weersgevoeligheid, hm, samenvatting en gpx_url worden overgenomen.
  Bestaat nieuwe_code al, dan worden de routes samengevoegd (walks verhuizen).
- zekerheid laag: niets overnemen; de voorstellen gaan naar het review-bestand.
- Onbekende hindernis-tags worden overgeslagen en gemeld.
"""
import argparse, csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAGS = {"doorwading", "rotsklauteren", "ladder_ketting", "afgrond_hoogtevrees", "grot_tunnel_zaklamp",
        "steil", "nat_drassig", "orientatie_spoorzoeken", "reuzenberenklauw", "jachtseizoen",
        "omgevallen_bomen", "prikkeldraad_vee", "begroeiing", "beekoversteek", "losliggende_stenen",
        "kapotte_brug", "geen_beschutting", "verkeer", "drukte"}

ap = argparse.ArgumentParser()
ap.add_argument("patch")
ap.add_argument("--review", default="review.csv")
args = ap.parse_args()

patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
routes = json.loads((ROOT / "data/routes.json").read_text(encoding="utf-8"))
walks = json.loads((ROOT / "data/walks.json").read_text(encoding="utf-8"))
by_code = {r["code"]: r for r in routes}

def merge_list(a, b):
    return a + [x for x in b if x not in a]

review, log, warn = [], {"bijgewerkt": 0, "hernoemd": 0, "samengevoegd": 0, "review": 0, "onbekend": 0}, []
for code, p in patch.items():
    r = by_code.get(code)
    if r is None:
        warn.append(f"onbekende code {code}"); log["onbekend"] += 1; continue
    zek = (p.get("zekerheid") or "laag").lower()
    if zek not in ("hoog", "middel"):
        review.append([code, r["naam"], p.get("nieuwe_code") or "", (p.get("bron") or {}).get("naam") or "",
                       (p.get("bron") or {}).get("url") or "", p.get("toelichting") or "", ""])
        log["review"] += 1
        continue
    if p.get("bron") and p["bron"].get("naam"):
        r["bron"] = {"naam": p["bron"]["naam"], "url": p["bron"].get("url")}
    r["bron_zekerheid"] = zek
    if p.get("kenmerken"):
        r["kenmerken"] = merge_list(r["kenmerken"], p["kenmerken"])
    tags = [t for t in p.get("hindernissen") or [] if t in TAGS]
    warn += [f"{code}: tag '{t}' overgeslagen" for t in p.get("hindernissen") or [] if t not in TAGS]
    r["hindernissen"] = merge_list(r["hindernissen"], tags)
    for veld in ("weersgevoeligheid", "samenvatting"):
        if p.get(veld):
            r[veld] = p[veld]
    if p.get("hm") and not r.get("hm"):
        r["hm"] = p["hm"]
    if p.get("gpx_url"):
        r["gpx_bron"] = p["gpx_url"]
    log["bijgewerkt"] += 1

    nieuw = p.get("nieuwe_code")
    if nieuw and nieuw != code:
        for w in walks:
            if w["route"] == code:
                w["route"] = nieuw
        if nieuw in by_code:  # samenvoegen in bestaande route
            doel = by_code[nieuw]
            doel["kenmerken"] = merge_list(doel["kenmerken"], r["kenmerken"])
            doel["hindernissen"] = merge_list(doel["hindernissen"], r["hindernissen"])
            for veld in ("samenvatting", "weersgevoeligheid"):
                if not doel.get(veld) and r.get(veld):
                    doel[veld] = r[veld]
            if (doel["bron"].get("naam") or "").lower() in ("onbekend", "eigen route", "") and r["bron"].get("url"):
                doel["bron"] = r["bron"]
            routes.remove(r); del by_code[code]
            log["samengevoegd"] += 1
        else:
            r["code"] = nieuw
            by_code[nieuw] = by_code.pop(code)
            log["hernoemd"] += 1

for r in routes:
    r.setdefault("samenvatting", None)
    r.setdefault("bron_zekerheid", None)

(ROOT / "data/routes.json").write_text(json.dumps(sorted(routes, key=lambda r: r["code"]), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
(ROOT / "data/walks.json").write_text(json.dumps(walks, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
with open(args.review, "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh)
    wr.writerow(["code", "naam", "voorgestelde_code", "voorgestelde_bron", "url", "toelichting_gemini", "akkoord (ja/nee)"])
    wr.writerows(review)
print(log)
for w in warn: print("let op:", w)
