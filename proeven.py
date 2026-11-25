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
    print(f"Schone kopieën in {tmp}")
    try:
        trials(fresh(tmp, "repo"))
        edge_cases(lambda name: fresh(tmp, name))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} van {len(results)} controles geslaagd.")
    return 1 if failed else 0


def fresh(tmp, name):
    repo = tmp / name
    repo.mkdir()
    for item in KEEP:
        src = HERE / item
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, repo / item)
    (repo / "uitvoer").mkdir()
    return repo


def fails(repo, *args):
    p = subprocess.run([sys.executable, "run.py", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    return p.returncode == 2, p.stderr


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text, (path.name, old)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def edge_cases(new_repo):
    """Proef 7: what an editor might do outside the scenario of the assignment."""
    print("\nProef 7. Randgevallen buiten het scenario")
    noor_sentence = "1. Meet thuis je bakfiets op de breedste plek en schrijf die maat op."

    # a different edit than appendix B: the stored W51 copy is still used, flagged for a check
    repo = new_repo("afwijkend")
    run(repo, "editie", "--week", "W50")
    p = repo / "uitvoer/W50/W50-M1-thema.md"
    edit(p, noor_sentence, noor_sentence + " Meet thuis ook hoe breed je stuur is.")
    edit(p, "Dan lopen we de route samen.", "Dan lopen we samen de route.")
    run(repo, "besluit", "W50-M1-thema", "goedgekeurd")
    run(repo, "besluit", "W50-M2-thema", "afgewezen", "--reden", "Geef de lezer een concrete controle voor het volgende bezoek.")
    run(repo, "editie", "--week", "W51")
    doc = (repo / "uitvoer/W51/W51-M1-thema.md").read_text(encoding="utf-8")
    ok("andere bewerking: W51 gebruikt nog de opgeslagen kopij, geen sjabloon",
       "## Bereid je thuis voor" in reader(repo / "uitvoer/W51/W51-M1-thema.md") and "Kopij uit het sjabloon" not in doc)
    ok("andere bewerking: de redacteur krijgt een controlevraag over de feedback", "geschreven bij andere feedback" in doc)
    ok("Ivo's afwijking is gelijk aan bijlage B: feedback geldt als verwerkt",
       "FB-W50-M2-thema" in log_rows(repo)["W51-M2-thema"]["feedback_verwerkt"])

    # false OK's from the blind review
    p = repo / "uitvoer/W50/W50-M2-terugblik.md"
    edit(p, "Deze week liet ik vier keer", "Reken op 10 cm speling. De prijzen zijn met twaalf procent gestegen. "
                                         "De kamer krijgt 8 uur zon. Deze week liet ik vier keer")
    run(repo, "editie", "--week", "W50")
    doc = p.read_text(encoding="utf-8")
    ok("'twaalf procent gestegen' is een FOUT", "FOUT: De lezerskopij noemt een percentage en prijsontwikkeling" in doc)
    ok("'10 cm' en '8 uur' vragen aandacht", "10 cm" in doc.split("### Controle")[1] and "8 uur" in doc.split("### Controle")[1])

    # editing after approval is visible
    p = repo / "uitvoer/W50/W50-M1-thema.md"
    edit(p, "Neem je meetlint mee naar de bezichtiging.", "Neem je meetlint en je fiets mee naar de bezichtiging.")
    run(repo, "editie", "--week", "W50")
    ok("bewerking na goedkeuren wordt gemeld", "De tekst is na het besluit bewerkt" in p.read_text(encoding="utf-8")
       and "na besluit bewerkt" in log_rows(repo)["W50-M1-thema"]["status"])

    # a deleted approved draft comes back from its last revision, with its decision
    p.unlink()
    out = run(repo, "editie", "--week", "W50")
    text = p.read_text(encoding="utf-8")
    ok("verwijderd goedgekeurd concept wordt hersteld uit de revisie", "hersteld uit revisie" in out
       and "Meet thuis ook hoe breed je stuur is." in reader(p) and "Status: goedgekeurd" in text)

    # the editor chooses another URL path; an edit in the pipeline block is kept aside, not lost silently
    p = repo / "uitvoer/W51/W51-M2-thema.md"
    edit(p, "- URL-pad: /gids/looproute-fietsenstalling", "- URL-pad: /gids/route-fietsenstalling-lindehof")
    edit(p, "- Status: concept", "- Status: goedgekeurd door mij")
    run(repo, "editie", "--week", "W51")
    run(repo, "editie", "--week", "W51")
    doc = p.read_text(encoding="utf-8")
    ok("URL-pad van de redacteur blijft staan", log_rows(repo)["W51-M2-thema"]["url_pad"] == "/gids/route-fietsenstalling-lindehof"
       and "door de redacteur gekozen" in doc)
    ok("wijziging in het pipelineblok wordt bewaard en gemeld", "niet overgenomen" in doc
       and any((repo / "uitvoer/revisies/W51-M2-thema").glob("pipelineblok-bewerkt-*.md")))

    # a new cleared photo closes the image task
    bron = json.loads((repo / "invoer/redactiebron.json").read_text(encoding="utf-8"))
    bron["beeldregister"].append({"id": "F5", "bestand": "hof8-fietsroute-2027.jpg", "gebied": "Lindehof",
                                  "onderwerp": "route naar fietsenstalling", "recht": "vrijgegeven"})
    (repo / "invoer/redactiebron.json").write_text(json.dumps(bron, ensure_ascii=False, indent=2), encoding="utf-8")
    run(repo, "editie", "--week", "W51")
    ok("nieuwe foto F5 sluit de beeldtaak", log_rows(repo)["W51-M2-thema"]["beeld"] == "F5"
       and log_rows(repo)["W51-M2-terugblik"]["beeld"] == "F5")

    # running W51 before W50 keeps the calendar order
    repo = new_repo("volgorde")
    out = run(repo, "editie", "--week", "W51")
    ok("W51 eerst: waarschuwing dat W50 nog niet gedraaid is", "W50 is in werkmap uitvoer nog niet gedraaid" in out)
    run(repo, "editie", "--week", "W50")
    rows = log_rows(repo)
    ok("W51 eerst: Ivo krijgt Q4, W50 houdt Q2, geen FOUT", rows["W51-M2-thema"]["aanleiding"] == "Q4"
       and rows["W50-M2-thema"]["aanleiding"] == "Q2" and "FOUT" not in rows["W50-M2-thema"]["aandacht"])

    # guards
    ok("reset van de voorbeelden vraagt om --ja", fails(repo, "reset", "--werkmap", "voorbeelden")[0])
    ok("invoer is geen werkmap", fails(repo, "editie", "--week", "W50", "--werkmap", "invoer")[0])


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
