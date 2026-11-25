"""Replays the six trials from the assignment ("Zo beproeven we je inzending") on a clean copy.

Run `python proeven.py`. It copies the repository to a temporary folder without any output,
runs every step exactly as the README describes, and checks the observable result.
Exit code 0 means all trials passed. Nothing in this folder changes.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEEP = ["redactie.py", "run.py", "invoer", "kopij"]
results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  {'OK  ' if cond else 'FOUT'} {name}" + (f"  ({detail})" if detail and not cond else ""))


def run(repo, *args):
    p = subprocess.run([sys.executable, "run.py", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise SystemExit(f"run.py {' '.join(args)} faalde:\n{p.stdout}\n{p.stderr}")
    return p.stdout


def docs(repo):
    return sorted((repo / "uitvoer").glob("W*/*.md"))


def reader(path):
    return path.read_text(encoding="utf-8").split("<!-- einde lezerskopij -->")[0]


def human(path):
    return path.read_text(encoding="utf-8").split("<!-- pipeline:start -->")[0]


def tree_hash(repo):
    h = {}
    for p in sorted((repo / "uitvoer").rglob("*")):
        if p.is_file() and p.name not in ("status.json",):
            h[p.relative_to(repo).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return h


def log_rows(repo):
    import csv
    with open(repo / "uitvoer" / "redactielog.csv", encoding="utf-8") as f:
        return {r["sleutel"]: r for r in csv.DictReader(f)}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="maandagredactie-"))
    repo = tmp / "repo"
    repo.mkdir()
    for name in KEEP:
        src = HERE / name
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, repo / name)
    (repo / "uitvoer").mkdir()
    print(f"Schone kopie in {repo}")
    try:
        trials(repo)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} van {len(results)} controles geslaagd.")
    return 1 if failed else 0


def trials(repo):
    src = json.loads((repo / "invoer/redactiebron.json").read_text(encoding="utf-8"))
    rights = {f["id"]: f for f in src["beeldregister"]}

    print("\nProef 1. Eerste maandag: start W50 vanaf een schone kopie")
    run(repo, "editie", "--week", "W50")
    d = docs(repo)
    ok("vier concepten in uitvoer/W50", [p.name for p in d] == [
        "W50-M1-terugblik.md", "W50-M1-thema.md", "W50-M2-terugblik.md", "W50-M2-thema.md"])
    rows = log_rows(repo)
    ok("Noors thema werkt /gids/fietsberging bij", rows["W50-M1-thema"]["paginakeuze"] == "update P1"
       and rows["W50-M1-thema"]["url_pad"] == "/gids/fietsberging")
    ok("Ivo krijgt een eigen, nieuw onderwerp", rows["W50-M2-thema"]["paginakeuze"] == "nieuw"
       and rows["W50-M2-thema"]["aanleiding"] == "Q2")
    noor = reader(repo / "uitvoer/W50/W50-M1-thema.md")
    ivo = reader(repo / "uitvoer/W50/W50-M2-thema.md")
    ok("Noor begint bij een handeling", re.search(r"_\n\nZet je bakfiets even neer", noor))
    ok("Ivo beschrijft twee opties", ivo.count("## De woonkamer op het") == 2)
    ok("alle concepten komen uit opgeslagen modeluitvoer", all(r["kopij"].startswith("kopij/") for r in rows.values()))

    print("\nProef 2. Feit en beeld")
    ok("de claim uit X1 staat in geen enkele lezerskopij",
       not any(re.search(r"12\s?%|prijsstijging", reader(p), re.I) for p in docs(repo)))
    used = [r["beeld"] for r in rows.values() if r["beeld"]]
    ok("elk gebruikt beeld is vrijgegeven", used and all(rights[b]["recht"] == "vrijgegeven" for b in used))
    ok("beeld past bij gebied en onderwerp", rows["W50-M1-thema"]["beeld"] == "F1" and rows["W50-M2-thema"]["beeld"] == "F2")
    ok("elke rij in het log heeft bron-ID's", all(r["bron_ids"] for r in rows.values()))

    print("\nProef 3. Dezelfde maandag: beide besluiten uit bijlage B, dan W50 opnieuw")
    before = {p.name for p in docs(repo)}
    run(repo, "bijlage-b")
    run(repo, "editie", "--week", "W50")
    after = {p.name for p in docs(repo)}
    ok("dezelfde vier documentsleutels", before == after and len(after) == 4)
    noor = (repo / "uitvoer/W50/W50-M1-thema.md").read_text(encoding="utf-8")
    ok("Noors extra zin staat in de lezerskopij", "Meet thuis ook hoe breed je stuur is." in reader(repo / "uitvoer/W50/W50-M1-thema.md"))
    ok("Noors stuk is goedgekeurd met die wijziging", "Status: goedgekeurd" in noor and
       "Toegevoegd door de redacteur: \"Meet thuis ook hoe breed je stuur is.\"" in noor)
    ivo = (repo / "uitvoer/W50/W50-M2-thema.md").read_text(encoding="utf-8")
    reden = "Geef de lezer een concrete controle voor het volgende bezoek."
    ok("Ivo's afwijzing met reden staat in het document", "Status: afgewezen" in ivo and reden in ivo)
    rows = log_rows(repo)
    ok("besluit en reden staan in het log", rows["W50-M2-thema"]["besluit"] == "afgewezen" and rows["W50-M2-thema"]["reden"] == reden)
    ok("de afgewezen tekst is bewaard", "## De woonkamer op het oosten" in ivo)
    ok("diff van Noors wijziging bestaat", (repo / "uitvoer/revisies/W50-M1-thema/diff-r1-r2.diff").exists())
    snap = tree_hash(repo)
    run(repo, "editie", "--week", "W50")
    ok("een derde run verandert niets", tree_hash(repo) == snap)

    print("\nProef 4. Volgende maandag: W51")
    run(repo, "editie", "--week", "W51")
    ok("acht concepten in totaal", len(docs(repo)) == 8)
    rows = log_rows(repo)
    t = rows["W51-M2-thema"]
    ok("Ivo krijgt de alternatieve zoekvraag Q4", t["aanleiding"] == "Q4")
    ok("het log zegt waarom", "Q2" in t["keuzereden"] and "afgewezen" in t["keuzereden"] and "Alternatief Q4" in t["keuzereden"])
    body = reader(repo / "uitvoer/W51/W51-M2-thema.md")
    ok("een concrete controle voor het volgende bezoek", "## Controle voor je volgende bezoek" in body)
    ok("feedback is herleidbaar", "FB-W50-M2-thema" in t["feedback_verwerkt"])
    ok("open beeldtaak, F4 niet als bruikbaar beeld", t["beeldstatus"] == "beeldtaak" and t["beeld"] == ""
       and "F4" in t["aandacht"] and "verlopen" in t["aandacht"])
    ok("beeldtaak staat in uitvoer/taken.md", "W51-M2-thema: AANDACHT: Beeldtaak" in (repo / "uitvoer/taken.md").read_text(encoding="utf-8"))
    snap = tree_hash(repo)
    run(repo, "editie", "--week", "W51")
    ok("tweede run W51 maakt niets extra en verandert niets", tree_hash(repo) == snap)

    print("\nProef 5. Controles: URL-pad van Ivo's W51-thema in de sitemap, W51 opnieuw")
    sm_path = repo / "invoer/sitemap.json"
    sm = json.loads(sm_path.read_text(encoding="utf-8"))
    sm["paginas"].append({"pad": t["url_pad"], "titel": "Proef: bestaande pagina", "bron": "proef"})
    sm_path.write_text(json.dumps(sm, ensure_ascii=False, indent=2), encoding="utf-8")
    text_before = human(repo / "uitvoer/W51/W51-M2-thema.md")
    run(repo, "editie", "--week", "W51")
    doc = (repo / "uitvoer/W51/W51-M2-thema.md").read_text(encoding="utf-8")
    ok("het concept toont het URL-pad als aandachtsveld", f"AANDACHT: URL-pad {t['url_pad']} bestaat al" in doc)
    ok("tekst gelijk", human(repo / "uitvoer/W51/W51-M2-thema.md") == text_before)
    ok("sleutel en aantal documenten gelijk", len(docs(repo)) == 8 and "W51-M2-thema" in log_rows(repo))

    print("\nProef 6. Overdracht")
    noor = (repo / "uitvoer/W50/W50-M1-thema.md").read_text(encoding="utf-8")
    row = next(l for l in noor.splitlines() if l.startswith("|") and "1,10 m" in l)
    ok("een cijfer (1,10 m) is naar bron B1 te volgen", "B1" in row and
       "1,10 m" in next(f["tekst"] for f in src["feiten"] if f["id"] == "B1"))
    # a manual edit in a concept survives a rerun
    p = repo / "uitvoer/W51/W51-M1-terugblik.md"
    p.write_text(p.read_text(encoding="utf-8").replace("Een goed plan,", "Een slim plan,"), encoding="utf-8")
    run(repo, "editie", "--week", "W51")
    ok("handmatige bewerking in een concept blijft staan", "Een slim plan," in p.read_text(encoding="utf-8")
       and "handmatig bewerkt" in log_rows(repo)["W51-M1-terugblik"]["status"])
    # an image task is closed by registering a cleared image
    bron = json.loads((repo / "invoer/redactiebron.json").read_text(encoding="utf-8"))
    next(f for f in bron["beeldregister"] if f["id"] == "F4")["recht"] = "vrijgegeven"
    (repo / "invoer/redactiebron.json").write_text(json.dumps(bron, ensure_ascii=False, indent=2), encoding="utf-8")
    run(repo, "editie", "--week", "W51")
    ok("beeldtaak sluit zodra F4 weer vrijgegeven is", log_rows(repo)["W51-M2-thema"]["beeld"] == "F4")
    bad = subprocess.run([sys.executable, "run.py", "editie", "--week", "W52"], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    ok("een week zonder invoer geeft een duidelijke fout", bad.returncode == 2 and "W52" in bad.stderr)
    bad = subprocess.run([sys.executable, "run.py", "besluit", "W51-M1-thema", "afgewezen"], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    ok("afwijzen zonder reden wordt geweigerd", bad.returncode == 2 and "reden" in bad.stderr)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
