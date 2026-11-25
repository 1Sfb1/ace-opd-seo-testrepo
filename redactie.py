"""Monday desk pipeline for Kade & Hof Wonen.

Turns an agent's weekly note and a search question into reviewable Dutch drafts, keeps every
human edit and decision, and can be rerun for the same week without creating or overwriting
anything. Standard library only; no keys, no network.
"""
from __future__ import annotations

import csv
import datetime as dt
import difflib
import hashlib
import io
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "invoer"
COPY_DIR = ROOT / "kopij"

PIPE_START = "<!-- pipeline:start -->"
PIPE_END = "<!-- pipeline:end -->"
READER_END = "<!-- einde lezerskopij -->"
LOG_COLUMNS = ["werkmap", "week", "makelaar", "soort", "sleutel", "documentpad", "status", "bron_ids",
               "aanleiding", "paginakeuze", "keuzereden", "url_pad", "beeld", "beeldstatus", "besluit",
               "reden", "revisie", "feedback_verwerkt", "aandacht", "kopij"]
RESERVED = {"invoer", "kopij", "tests", "github", "git"}
PROTECTED = {"voorbeelden"}
STOP = {"naar", "en", "de", "het", "een", "van", "op", "wat", "waar", "hoe", "mijn", "tussen", "verschil", "let"}
NUMBER_WORDS = ("een|één|twee|drie|vier|vijf|zes|zeven|acht|negen|tien|elf|twaalf|vijftien|twintig|dertig|"
                "veertig|vijftig|honderd|duizend")
UNITS = "procent|uur|uren|meter|centimeter|cm|mm|euro|minuten|jaar|jaren|graden|vierkante"


class PipelineError(Exception):
    """A problem the user can fix; printed without a traceback."""


# ---------------------------------------------------------------- input

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def settings() -> dict:
    return load_json(INPUT / "instellingen.json")


def source() -> dict:
    return load_json(INPUT / "redactiebron.json")


def sitemap() -> list[dict]:
    return load_json(INPUT / "sitemap.json")["paginas"]


def by_id(items, key="id"):
    return {x[key]: x for x in items}


def slug(text: str) -> str:
    text = text.lower()
    for a, b in (("ë", "e"), ("é", "e"), ("ï", "i"), ("ö", "o"), ("ü", "u"), ("&", "en")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip().split("\n")) + "\n"


def digest(text: str) -> str:
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()[:12]


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def topic_words(text: str) -> list[str]:
    return [w for w in re.split(r"\W+", text.lower()) if len(w) > 3 and w not in STOP]


# ---------------------------------------------------------------- workspace

class Workspace:
    def __init__(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise PipelineError(f"Werkmap '{name}' mag alleen letters, cijfers, - en _ bevatten.")
        if name.lower() in RESERVED:
            raise PipelineError(f"'{name}' is geen werkmap: daar staan invoer, kopij of tests. Kies bijvoorbeeld 'uitvoer'.")
        self.name = name
        self.dir = ROOT / name
        self.state_path = self.dir / "status.json"

    def load(self) -> dict:
        if self.state_path.exists():
            return load_json(self.state_path)
        return {"docs": {}, "feedback": {}, "runs": []}

    def save(self, state: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        write(self.state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    def rel(self, path: Path) -> str:
        return path.relative_to(ROOT).as_posix()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------------------------------------------------------------- planning

def edition(src: dict, week: str) -> dict:
    eds = by_id(src["edities"])
    if week not in eds:
        raise PipelineError(f"Week {week} staat niet in invoer/redactiebron.json. Beschikbaar: {', '.join(eds)}.")
    return eds[week]


def week_index(src: dict, week: str) -> int:
    return [e["id"] for e in src["edities"]].index(week)


def pick_image(src: dict, area: str, topic_text: str) -> dict:
    """Best match on area and subject words. Among equally fitting images a cleared one wins;
    when no best-fitting image is cleared, the article gets an image task instead."""
    topic = topic_text.lower()
    scored = []
    for img in src["beeldregister"]:
        if img["gebied"] == area:
            score = sum(1 for w in topic_words(img["onderwerp"]) if w in topic)
            if score:
                scored.append((score, img))
    if not scored:
        return {"beeld": None, "bestand": None, "beeldstatus": "beeldtaak",
                "taak": f"Geen passend beeld in het beeldregister voor {area}. Zoek of laat een vrijgegeven beeld maken."}
    top = max(s for s, _ in scored)
    best = [img for s, img in scored if s == top]
    cleared = [img for img in best if img["recht"] == "vrijgegeven"]
    if cleared:
        img = cleared[-1]  # the most recently registered of the equally fitting, cleared images
        return {"beeld": img["id"], "bestand": img["bestand"], "beeldstatus": "vrijgegeven", "taak": None}
    img = best[0]
    return {"beeld": None, "bestand": None, "beeldstatus": "beeldtaak",
            "taak": f"{img['id']} ({img['bestand']}) past inhoudelijk, maar de rechten zijn {img['recht']}. "
                    f"Zoek of laat een vrijgegeven beeld maken over: {img['onderwerp']} ({area})."}


def calendar_choices(src: dict, state: dict, month: str) -> list[tuple[str, str, str, str]]:
    """Every theme slot of this month in calendar order, with its question: the one already chosen,
    or the one it will get when it runs. Returns (key, question, reason, status)."""
    order = sorted((c for c in src["kalender"] if edition(src, c["week"])["aanleveren"][:7] == month),
                   key=lambda c: (week_index(src, c["week"]), c["makelaar"]))
    out, taken = [], {}
    for c in order:
        key = f"{c['week']}-{c['makelaar']}-thema"
        doc = state["docs"].get(key)
        if doc and doc.get("aanleiding_id") and doc.get("status") != "gepland":
            q, why, status = doc["aanleiding_id"], doc.get("vraagreden", ""), doc["status"]
        else:
            pref, alt = c["voorkeur"], c.get("alternatief")
            status = "nog niet gedraaid, plek volgens de kalender"
            if pref not in taken:
                q, why = pref, f"Voorkeur {pref} uit de onderwerpkalender; nog vrij in {month}."
            else:
                by, st = taken[pref]
                why = f"Voorkeur {pref} is in {month} al bezet door {by} (status: {st}"
                why += "; ook een afgewezen concept houdt zijn plaats)." if st == "afgewezen" else ")."
                if alt and alt not in taken:
                    q, why = alt, why + f" Alternatief {alt} uit de onderwerpkalender gekozen."
                else:
                    q, why = pref, why + " Er is geen vrij alternatief; de redacteur moet een onderwerp kiezen."
        taken.setdefault(q, (key, status))
        out.append((key, q, why, status))
    return out


def choose_question(src: dict, state: dict, key: str, week: str, agent: str) -> tuple[str, str, bool]:
    """Question for a theme article: stable once chosen; one question per calendar month for the whole desk,
    reserved in calendar order, so running a later week first does not take an earlier week's question."""
    doc = state["docs"].get(key)
    if doc and doc.get("aanleiding_id") and doc.get("vraagreden"):
        return doc["aanleiding_id"], doc["vraagreden"], doc.get("botsing", False)
    if not any(c["week"] == week and c["makelaar"] == agent for c in src["kalender"]):
        raise PipelineError(f"Geen onderwerpkalender voor {week} {agent}.")
    month = edition(src, week)["aanleveren"][:7]
    slots = calendar_choices(src, state, month)
    mine = next(s for s in slots if s[0] == key)
    clash = sum(1 for s in slots if s[1] == mine[1]) > 1
    return mine[1], mine[2], clash


def feedback_for(src: dict, state: dict, key: str, week: str, agent: str) -> list[dict]:
    """Feedback on this agent's earlier themes, applied once to the next theme of the same agent."""
    here = week_index(src, week)
    out = []
    for fid, fb in sorted(state["feedback"].items()):
        if fb["makelaar"] != agent or week_index(src, fb["week"]) >= here:
            continue
        if fb.get("toegepast_in") in (None, key):
            out.append({"id": fid, **fb})
    return out


def plan(src: dict, state: dict, week: str) -> list[dict]:
    ed = edition(src, week)
    month = ed["aanleveren"][:7]
    facts = src["feiten"]
    pages = by_id(src["bestaande_paginas"])
    questions = by_id(src["zoekvragen"])
    items = []
    for prof in src["profielen"]:
        agent, area = prof["id"], prof["gebied"]
        note = next((n for n in src["weeknotities"] if n["week"] == week and n["makelaar"] == agent), None)
        if not note:
            raise PipelineError(f"Geen weeknotitie voor {week} {agent}.")
        area_facts = [f for f in facts if f["gebied"] == area]
        base = {"week": week, "maand": month, "makelaar": agent, "profiel": prof, "edition": ed,
                "feiten": [f for f in area_facts if f["status"] == "vrijgegeven"],
                "onbevestigd": [f for f in area_facts if f["status"] != "vrijgegeven"]}
        key = f"{week}-{agent}-terugblik"
        items.append({**base, "sleutel": key, "soort": "terugblik", "aanleiding_id": note["id"],
                      "aanleiding": note, "keuze": "terugblik", "pagina_id": None, "pagina": None,
                      "keuzereden": f"Weekterugblik op notitie {note['id']}.", "botsing": False,
                      "url_pad": f"/weekbericht/{ed['aanleveren'][:4]}-{week.lower()}-{slug(area)}",
                      "feedback": [], **pick_image(src, area, note["tekst"])})
        key = f"{week}-{agent}-thema"
        qid, q_why, clash = choose_question(src, state, key, week, agent)
        why = q_why
        q = questions[qid]
        if q["bestaand_pad"]:
            page = next(p for p in pages.values() if p["pad"] == q["bestaand_pad"])
            choice, page_id, path = "update", page["id"], page["pad"]
            why += f" De zoekvraag hoort bij bestaande pagina {page['pad']} ({page['id']}): update, geen nieuwe pagina."
        else:
            choice, page_id, path = "nieuw", None, "/gids/" + slug(q["onderwerp"])
            why += " Geen bestaande pagina voor deze zoekvraag: nieuwe pagina."
        item = {**base, "sleutel": key, "soort": "thema", "aanleiding_id": qid, "aanleiding": q,
                "keuze": choice, "pagina_id": page_id, "pagina": pages.get(page_id), "keuzereden": why,
                "botsing": clash, "url_pad": path, **pick_image(src, area, q["onderwerp"] + " " + q["vraag"])}
        item["feedback"] = feedback_for(src, state, key, week, agent)
        items.append(item)
        state["docs"].setdefault(key, {"soort": "thema", "maand": month, "status": "gepland"})
        state["docs"][key].update({"aanleiding_id": qid, "vraagreden": q_why, "botsing": clash})
    return items


# ---------------------------------------------------------------- the model step (prompt and stored output)

def prompt_for(item: dict) -> str:
    p = item["profiel"]
    lines = [
        "Je schrijft een Nederlands concept voor de website van Kade & Hof Wonen, in de stem van een makelaar.",
        f"Makelaar: {p['naam']} ({p['id']}), gebied {p['gebied']}.",
        f"Stijl: {p['stijl']}",
        f"Voorbeeldzin in deze stem: \"{p['voorbeeld']}\"",
        f"Bio (ongewijzigd onder het stuk): {p['bio']}",
        f"Soort stuk: {item['soort']} voor editie {item['week']} (aanleveren {item['edition']['aanleveren']}).",
    ]
    if item["soort"] == "terugblik":
        n = item["aanleiding"]
        lines.append(f"Aanleiding: weeknotitie {n['id']}: \"{n['tekst']}\"")
    else:
        q = item["aanleiding"]
        lines.append(f"Zoekvraag {q['id']}: \"{q['vraag']}\". Redactionele aanwijzing: {q['aanwijzing']}")
        lines.append("Beantwoord de zoekvraag in de eerste alinea.")
        if item["keuze"] == "update":
            pg = item["pagina"]
            lines.append(f"Werk de bestaande pagina {pg['pad']} bij. Houd wat klopt, verbeter wat ontbreekt of niet klopt, "
                         "en noem per passage of je die behoudt, vervangt, toevoegt of schrapt.")
            lines.append(f"Huidige titel: \"{pg['titel']}\". Huidige tekst: \"{pg['tekst']}\"")
    lines.append("Bevestigde feiten die je mag gebruiken (noem het bron-ID bij elke claim):")
    lines += [f"- {f['id']}: {f['tekst']}" for f in item["feiten"]]
    if item["onbevestigd"]:
        lines.append("Onbevestigd; NIET in de lezerskopij, alleen als open redactievraag:")
        lines += [f"- {f['id']}: {f['tekst']}" for f in item["onbevestigd"]]
    if item["feedback"]:
        lines.append("Feedback van de redacteur op eerder werk; verwerk die en zeg waar:")
        lines += [f"- {fb['id']}: {fb['tekst']}" for fb in item["feedback"]]
    lines += [
        "Regels: maximaal 600 woorden lopende tekst; spreek de lezer aan met je; verzin geen maten, zonuren, "
        "zoekvolumes of andere cijfers; wat niet bekend is, laat je open of maak je een controle voor de lezer.",
        "Antwoord als JSON met: kop, onderkop, tekst (Markdown), metatitel (max 60 tekens), metabeschrijving "
        "(max 160 tekens), tags (precies 3), waarom_nu, claims [{claim, bron}], open_vragen [..], "
        "wijzigingen [{soort, passage, toelichting}] (alleen bij een update), feedback_verwerkt [{feedback, waar}].",
    ]
    return "\n".join(lines) + "\n"


def fingerprints(item: dict) -> tuple[str, str, str]:
    """(prompt, exact fingerprint, base fingerprint without the feedback lines)."""
    prompt = prompt_for(item)
    base = prompt_for({**item, "feedback": []})
    return prompt, hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:10], hashlib.sha256(base.encode("utf-8")).hexdigest()[:10]


def stored_copy(item: dict, fp: str, base_fp: str) -> tuple[dict | None, Path | None, str]:
    """Exact match on the full prompt, else the nearest stored answer for the same sources and topic
    (written with other or no feedback), else nothing. Returns (copy, path, 'exact'|'nabij'|'')."""
    exact = COPY_DIR / f"{item['sleutel']}-{fp}.json"
    if exact.exists():
        return load_json(exact), exact, "exact"
    for path in sorted(COPY_DIR.glob(f"{item['sleutel']}-*.json")):
        data = load_json(path)
        if data.get("basis_vingerafdruk") == base_fp:
            return data, path, "nabij"
    return None, None, ""


def template_copy(item: dict) -> dict:
    """Plain fallback when no stored model output fits: only relevant source sentences, clearly marked for rewriting."""
    p = item["profiel"]
    open_q = [f"Feedback {fb['id']} is nog niet verwerkt: {fb['tekst']}" for fb in item["feedback"]]
    if item["soort"] == "terugblik":
        n = item["aanleiding"]
        return {"kop": f"Deze week in {p['gebied']}", "onderkop": f"{p['naam']} over de bezichtigingen van deze week",
                "tekst": f"{n['tekst']}\n\nHeb je dezelfde vraag? Neem hem mee naar je bezichtiging.",
                "metatitel": f"Weekbericht {p['gebied']}: wat bezoekers deze week vroegen"[:60],
                "metabeschrijving": f"{p['naam']} over de vragen van bezoekers deze week in {p['gebied']}."[:160],
                "tags": [p["gebied"], "weekbericht", "bezichtiging"], "waarom_nu": f"Notitie {n['id']} van deze week.",
                "claims": [{"claim": n["tekst"], "bron": n["id"]}], "open_vragen": open_q, "wijzigingen": [],
                "feedback_verwerkt": []}
    q = item["aanleiding"]
    words_q = topic_words(q["onderwerp"] + " " + q["vraag"])
    facts = [f for f in item["feiten"] if any(w in f["tekst"].lower() for w in words_q)]
    known = [f"- {f['tekst']}" for f in facts] or ["- Hierover zijn nog geen bevestigde gegevens."]
    body = "\n".join([f"{q['vraag']} Hieronder staat wat we weten en wat je zelf controleert.", "",
                      "## Wat we weten", ""] + known +
                     ["", "## Wat je zelf controleert", "", "Bekijk het tijdens de bezichtiging en schrijf op wat je ziet."])
    wijz = ([{"soort": "te bepalen", "passage": "hele pagina",
              "toelichting": "Sjabloonkopij: de redacteur bepaalt wat van de huidige tekst blijft."}]
            if item["keuze"] == "update" else [])
    return {"kop": q["vraag"], "onderkop": f"{p['naam']} over {q['onderwerp']} in {p['gebied']}", "tekst": body,
            "metatitel": q["vraag"][:60], "metabeschrijving": q["vraag"][:160],
            "tags": [p["gebied"], q["onderwerp"], "gids"], "waarom_nu": f"Zoekvraag {q['id']} uit de kalender.",
            "claims": [{"claim": f["tekst"], "bron": f["id"]} for f in facts], "open_vragen": open_q,
            "wijzigingen": wijz, "feedback_verwerkt": []}


# ---------------------------------------------------------------- rendering

def source_line(src: dict, sid: str) -> str:
    for group in ("feiten", "weeknotities", "zoekvragen", "bestaande_paginas", "beeldregister"):
        for x in src[group]:
            if x["id"] == sid:
                return x.get("tekst") or x.get("vraag") or x.get("titel") or x.get("bestand")
    return "(onbekend bron-ID)"


def cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def render_human(src: dict, item: dict, copy: dict) -> str:
    p = item["profiel"]
    a = item["aanleiding"]
    out = [f"<!-- sleutel: {item['sleutel']} -->", f"# {copy['kop']}", "", f"_{copy['onderkop']}_", "",
           copy["tekst"].strip(), "", f"**Over de auteur.** {p['bio']}", "", READER_END, "",
           "## Voor de website", "", f"- Metatitel: {copy['metatitel']}",
           f"- Metabeschrijving: {copy['metabeschrijving']}", f"- Tags: {', '.join(copy['tags'])}",
           f"- URL-pad: {item['url_pad']}", "", "## Voor de reviewer", ""]
    if item["soort"] == "thema":
        out.append(f"- Aanleiding: zoekvraag {a['id']}: \"{a['vraag']}\" (aanwijzing: {a['aanwijzing']})")
    else:
        out.append(f"- Aanleiding: weeknotitie {a['id']}: \"{a['tekst']}\"")
    keuze = {"update": f"update van bestaande pagina {item['url_pad']} ({item['pagina_id']})",
             "nieuw": "nieuwe pagina", "terugblik": "weekterugblik"}[item["keuze"]]
    out += [f"- Paginakeuze: {keuze}. {item['keuzereden']}", f"- Waarom nu: {copy['waarom_nu']}", "",
            "### Claims en bronnen", "", "| Claim | Bron | Bronregel |", "|---|---|---|"]
    for c in copy["claims"]:
        ids = re.findall(r"\b[A-Z]\d+\b", c["bron"])
        line = (" / ".join(source_line(src, i) for i in ids) if ids
                else "Geen bron in het bronpakket: algemene kennis. Controleer de formulering.")
        out.append(f"| {cell(c['claim'])} | {cell(c['bron'])} | {cell(line)} |")
    out += ["", "### Open redactievragen", ""]
    open_q = []
    for q in copy.get("open_vragen") or []:
        if item.get("beeld") and re.search(rf"\b{item['beeld']}\b", q) and re.search(r"verlopen|beeldtaak", q, re.I):
            q += f" Opgelost: {item['beeld']} ({item['bestand']}) is nu vrijgegeven en gekozen."
        open_q.append(q)
    out += [f"- {q}" for q in open_q] or ["- Geen."]
    if item["keuze"] == "update":
        out += ["", "### Wijzigingen ten opzichte van de huidige pagina", "", "| Soort | Passage | Toelichting |",
                "|---|---|---|"]
        out += [f"| {cell(w['soort'])} | {cell(w['passage'])} | {cell(w['toelichting'])} |" for w in copy["wijzigingen"]]
    done = copy.get("feedback_verwerkt") or []
    if item["feedback"] or done:
        out += ["", "### Verwerkte feedback", ""]
        out += [f"- {f['feedback']}: {f['waar']}" for f in done] or \
               [f"- {fb['id']}: nog niet verwerkt in deze kopij ({fb['tekst']})" for fb in item["feedback"]]
    return norm("\n".join(out))


def split_doc(text: str) -> tuple[str, str]:
    """(human part, pipeline block). Text after the block counts as human text."""
    text = text.replace("\r\n", "\n")
    if PIPE_START in text:
        human, rest = text.split(PIPE_START, 1)
        if PIPE_END in rest:
            block, tail = rest.split(PIPE_END, 1)
        else:
            block, tail = rest, ""
        return norm(human + tail), norm(PIPE_START + block + PIPE_END)
    return norm(text), ""


def section(human: str, title: str) -> str:
    return human.split(title, 1)[1].split("\n#", 1)[0] if title in human else ""


def table_rows(part: str) -> list[list[str]]:
    rows = []
    for row in part.split("\n"):
        if not row.strip().startswith("|"):
            continue
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if cells and not set(cells[0]) <= set("-:") and cells[0] not in ("Claim", "Soort"):
            rows.append(cells)
    return rows


def parse(human: str) -> dict:
    reader = human.split(READER_END, 1)[0]
    lines = reader.split("\n")
    kop = next((l[2:].strip() for l in lines if l.startswith("# ")), "")
    sub = next((l.strip("_ ").strip() for l in lines if re.fullmatch(r"_.+_", l.strip())), "")
    bio_i = next((i for i, l in enumerate(lines) if l.startswith("**Over de auteur.**")), None)
    sub_i = next((i for i, l in enumerate(lines) if re.fullmatch(r"_.+_", l.strip())), 0)
    body = "\n".join(lines[sub_i + 1:bio_i] if bio_i is not None else lines[sub_i + 1:]).strip()
    meta = {}
    for name in ("Metatitel", "Metabeschrijving", "Tags", "URL-pad"):
        m = re.search(rf"^- {name}: *(.*)$", human, re.M)
        meta[name] = m.group(1).strip() if m else ""
    claim_ids = []
    for cells in table_rows(section(human, "### Claims en bronnen")):
        if len(cells) >= 2:
            claim_ids += re.findall(r"\b[A-Z]\d+\b", cells[1])
    return {"kop": kop, "onderkop": sub, "body": body, "bio": bio_i is not None, "lezerskopij": reader,
            "metatitel": meta["Metatitel"], "metabeschrijving": meta["Metabeschrijving"],
            "tags": [t.strip() for t in meta["Tags"].split(",") if t.strip()], "url_pad": meta["URL-pad"],
            "claim_ids": claim_ids,
            "wijzigingen": len(table_rows(section(human, "### Wijzigingen ten opzichte van de huidige pagina")))}


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:[-'][A-Za-zÀ-ÿ0-9]+)*", re.sub(r"[#*_>`|]", " ", text)))


def sentences(text: str) -> list[str]:
    flat = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line).strip()
        if line and not line.startswith(("#", "<!--")):
            flat += [s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip()]
    return flat


def tokens(text: str) -> list[str]:
    return re.findall(r"\d+(?:,\d+)?|[a-zà-ÿ]+", text.lower())


# ---------------------------------------------------------------- checks

def unconfirmed_hits(text: str) -> list[str]:
    """Percentages and price movements: nothing confirmed in the sources supports them (X1 is unconfirmed)."""
    t = text.lower()
    hits = []
    if re.search(r"%|\bprocent\b|\bpercentage\b", t):
        hits.append("percentage")
    if re.search(r"prijsstijging|waardestijging|prijsdaling", t) or (
            re.search(r"\b(prijs|prijzen|waarde|woningwaarde)\b", t) and
            re.search(r"\b(stijg\w*|gestegen|omhoog|duurder|daal\w*|gedaald)\b", t)):
        hits.append("prijsontwikkeling")
    return hits


def stray_numbers(text: str, known: str) -> list[str]:
    """Numbers whose neighbour words do not occur with that number in a cited source.
    '1,10 m' and 'huis 3' pass; '8 uur' does not pass just because the source says 'Hof 8'."""
    src = tokens(known)
    pairs = {(a, b) for a, b in zip(src, src[1:])}
    t = tokens(text)
    stray = []
    for i, tok in enumerate(t):
        if not re.fullmatch(r"\d+(?:,\d+)?", tok):
            continue
        prev = t[i - 1] if i else ""
        nxt = t[i + 1] if i + 1 < len(t) else ""
        if (prev, tok) not in pairs and (tok, nxt) not in pairs:
            stray.append(" ".join(x for x in (prev, tok, nxt) if x))
    for m in re.finditer(rf"\b({NUMBER_WORDS})\s+({UNITS})\b", text.lower()):
        if m.group(0) not in known.lower():
            stray.append(m.group(0))
    return sorted(set(stray))


def check(src: dict, item: dict, human: str, cfg: dict, all_docs: dict, site: list[dict]) -> list[tuple[str, str]]:
    d = parse(human)
    res = []

    def add(level, text):
        res.append((level, text))

    for field, label in (("kop", "Kop"), ("onderkop", "Onderkop"), ("metatitel", "Metatitel"),
                         ("metabeschrijving", "Metabeschrijving")):
        if not d[field]:
            add("FOUT", f"{label} ontbreekt.")
    if not d["bio"]:
        add("FOUT", "Bio ontbreekt.")
    if d["metatitel"] and len(d["metatitel"]) > cfg["metatitel_max"]:
        add("AANDACHT", f"Metatitel is {len(d['metatitel'])} tekens (max {cfg['metatitel_max']}).")
    if d["metabeschrijving"] and len(d["metabeschrijving"]) > cfg["metabeschrijving_max"]:
        add("AANDACHT", f"Metabeschrijving is {len(d['metabeschrijving'])} tekens (max {cfg['metabeschrijving_max']}).")
    if len(d["tags"]) != 3:
        add("FOUT", f"Tags: {len(d['tags'])} in plaats van 3.")
    n = words(d["body"])
    add("FOUT" if n > cfg["max_woorden"] else "OK", f"Lopende tekst: {n} woorden (max {cfg['max_woorden']}).")
    if item["soort"] == "thema" and not item["aanleiding_id"].startswith("Q"):
        add("FOUT", "Thema zonder zoekvraag.")
    if item["keuze"] == "update" and d["wijzigingen"] == 0:
        add("AANDACHT", "Update zonder wijzigingentabel: geef per passage aan wat blijft, vervangen of toegevoegd is.")
    # URL path (the editor may change it under 'Voor de website')
    path = item["url_pad"]
    if not d["url_pad"]:
        add("FOUT", "URL-pad ontbreekt onder 'Voor de website'.")
    elif not re.fullmatch(r"/[a-z0-9]+(?:[/-][a-z0-9]+)*", path):
        add("FOUT", f"URL-pad {path} heeft geen geldige vorm (kleine letters, cijfers, - en /).")
    others = [k for k, x in all_docs.items() if x.get("url_pad") == path and k != item["sleutel"]]
    if item["keuze"] == "update" and path == (item.get("pagina") or {}).get("pad"):
        if any(p["pad"] == path for p in site):
            add("OK", f"URL-pad {path}: update van een bestaande pagina.")
        else:
            add("FOUT", f"URL-pad {path} hoort bij een update, maar staat niet in de sitemap.")
    else:
        hits = [p["pad"] for p in site if p["pad"] == path]
        if hits:
            add("AANDACHT", f"URL-pad {path} bestaat al in invoer/sitemap.json. Kies onder 'Voor de website' een ander "
                            f"pad, bijvoorbeeld {path}-{slug(item['profiel']['gebied'])}, of maak er een update van.")
        if not hits and not others:
            add("OK", f"URL-pad {path} is nieuw en uniek.")
    if others:
        add("AANDACHT", f"URL-pad {path} wordt ook gebruikt door {', '.join(others)}.")
    # unconfirmed claims never in reader copy
    reader = d["lezerskopij"]
    bad = unconfirmed_hits(reader)
    unconfirmed_ids = {f["id"] for f in src["feiten"] if f["status"] != "vrijgegeven"}
    if bad:
        add("FOUT", f"De lezerskopij noemt een {' en '.join(bad)} zonder bevestigde bron (X1 is onbevestigd). Haal die weg.")
    if set(d["claim_ids"]) & unconfirmed_ids:
        add("FOUT", f"Claim met onbevestigde bron {', '.join(sorted(set(d['claim_ids']) & unconfirmed_ids))}.")
    if not bad and not set(d["claim_ids"]) & unconfirmed_ids:
        add("OK", "Geen onbevestigde uitspraak in de lezerskopij.")
    # numbers must come from a cited source, with the same neighbour word
    known = " ".join(source_line(src, s) for s in d["claim_ids"] + [item["aanleiding_id"]]) + f" week {item['week'][1:]}"
    text = d["kop"] + "\n" + re.sub(r"^\s*\d+\.\s", "", d["body"], flags=re.M)
    stray = stray_numbers(text, known)
    if stray:
        add("AANDACHT", f"Getal of maat zonder geciteerde bron: {'; '.join(stray)}.")
    elif re.search(r"\d", text):
        add("OK", "Elk getal staat zo in een geciteerde bron.")
    unknown = [s for s in d["claim_ids"] if source_line(src, s) == "(onbekend bron-ID)"]
    if unknown:
        add("FOUT", f"Onbekend bron-ID in de claims: {', '.join(unknown)}.")
    if not d["claim_ids"]:
        add("AANDACHT", "Geen claims met bron-ID.")
    if re.search(r"\b(u|uw)\b", reader):
        add("AANDACHT", "De tekst gebruikt 'u'; de makelaars spreken de lezer aan met je.")
    elif not re.search(r"\b(je|jouw|jij)\b", reader, re.I):
        add("AANDACHT", "De tekst spreekt de lezer niet aan met je.")
    if item["beeldstatus"] == "vrijgegeven":
        add("OK", f"Beeld {item['beeld']} ({item['bestand']}) is vrijgegeven.")
    else:
        add("AANDACHT", f"Beeldtaak: {item['taak']}")
    if item["botsing"]:
        add("FOUT", "Geen vrije zoekvraag deze maand; de redacteur moet een onderwerp kiezen.")
    return res


# ---------------------------------------------------------------- the pipeline block

def render_pipeline(src: dict, ws: Workspace, item: dict, doc: dict, checks: list) -> str:
    p = item["profiel"]
    ed = item["edition"]
    img = (f"{item['beeld']} {item['bestand']} · rechten: vrijgegeven" if item["beeldstatus"] == "vrijgegeven"
           else f"geen bruikbaar beeld · beeldtaak: {item['taak']}")
    kop = doc["kopij"]
    source_txt = {"exact": f"opgeslagen modeluitvoer {kop['bestand']}",
                  "nabij": f"opgeslagen modeluitvoer {kop['bestand']} (geschreven bij andere feedback, zie controle)",
                  "sjabloon": "sjabloon (geen opgeslagen modeluitvoer voor deze invoer; laat herschrijven)"}[kop["bron"]]
    path_line = f"- URL-pad: {item['url_pad']}"
    if item["url_pad"] != item["url_voorstel"]:
        path_line += f" (door de redacteur gekozen; voorstel van de pipeline: {item['url_voorstel']})"
    out = [PIPE_START, "## Pad, beeld en controle", "",
           "_Dit blok schrijft de pipeline bij elke run opnieuw. Wijzig het URL-pad onder 'Voor de website'; "
           "wijzigingen in dit blok worden niet overgenomen._", "",
           f"- Sleutel: {item['sleutel']} · editie {item['week']} (aanleveren {ed['aanleveren']}, plaatsing "
           f"{ed['beoogde_publicatie']}) · {p['naam']} ({p['id']}) · {item['soort']}",
           path_line, f"- Beeld: {img}", f"- Kopij: {source_txt}", "", "### Controle", ""]
    out += [f"- {lvl}: {txt}" for lvl, txt in checks]
    out += ["", "### Besluit", "", f"- Status: {doc['status']}"]
    b = doc.get("besluit")
    if b:
        out.append(f"- Besluit: {b['besluit']} op {b['tijd']}, voor revisie r{b['revisie']}" +
                   (f". Reden: \"{b['reden']}\"" if b.get("reden") else ""))
        for s in b.get("toegevoegd", []):
            out.append(f"- Toegevoegd door de redacteur: \"{s}\"")
        for s in b.get("verwijderd", []):
            out.append(f"- Verwijderd door de redacteur: \"{s}\"")
        if b.get("diff"):
            out.append(f"- Volledige wijziging: {b['diff']}")
    if doc.get("handmatig") and doc["status"] == "concept":
        out.append(f"- Handmatig bewerkt na het genereren; je tekst blijft bij een nieuwe run staan (revisie r{doc['revisies'][-1]['nr']}).")
    for note in doc.get("meldingen", []):
        out.append(f"- {note}")
    if doc["status"] == "concept" or doc.get("na_besluit"):
        flag = f" --werkmap {ws.name}" if ws.name != "uitvoer" else ""
        out.append(f"- Beslissen: `python run.py besluit {item['sleutel']} goedgekeurd{flag}` of "
                   f"`python run.py besluit {item['sleutel']} afgewezen --reden \"...\"{flag}`")
    out.append(PIPE_END)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- run an edition

def run_edition(week: str, ws_name: str = "uitvoer", mode: str | None = None) -> list[str]:
    cfg = settings()
    mode = mode or cfg["modus"]
    if mode not in ("opgeslagen", "sjabloon"):
        raise PipelineError("Modus is 'opgeslagen' of 'sjabloon'.")
    src, site = source(), sitemap()
    ws = Workspace(ws_name)
    state = ws.load()
    edition(src, week)  # a clear error for an unknown week
    report = []
    earlier = [e["id"] for e in src["edities"][:week_index(src, week)]
               if not any(d.get("week") == e["id"] and "gen_hash" in d for d in state["docs"].values())]
    if earlier:
        report.append(f"Let op: {', '.join(earlier)} is in werkmap {ws_name} nog niet gedraaid. De onderwerpkalender "
                      f"houdt er rekening mee, maar feedback uit die week ontbreekt nog.")
    items = plan(src, state, week)
    for item in items:
        key = item["sleutel"]
        prompt, fp, base_fp = fingerprints(item)
        write(ws.dir / "prompts" / f"{key}-{fp}.txt", prompt)
        copy, copy_path, match = stored_copy(item, fp, base_fp) if mode == "opgeslagen" else (None, None, "")
        kopij = {"bron": match or "sjabloon", "bestand": ws_rel(copy_path), "fingerprint": fp}
        copy = copy or template_copy(item)
        doc_path = ws.dir / item["week"] / f"{key}.md"
        doc = state["docs"].get(key) or {}
        if doc.get("status") == "gepland":
            doc.pop("status")
        doc.setdefault("meldingen", [])
        item["url_voorstel"] = item["url_pad"]
        # an editor's URL path wins over the proposal
        url_now = doc.get("url_pad") if doc.get("url_bron") == "redacteur" else None
        if url_now:
            item["url_pad"] = url_now
        fresh = render_human(src, item, copy)
        if "gen_hash" not in doc:
            human, action = fresh, "nieuw"
            doc.update({"status": "concept", "revisies": [], "handmatig": False})
            doc["gen_hash"] = digest(human)
            add_revision(ws, doc, key, human, "gegenereerd")
        elif not doc_path.exists():
            last = ROOT / doc["revisies"][-1]["pad"] if doc.get("revisies") else None
            if last and last.exists():
                human = norm(last.read_text(encoding="utf-8"))
                action = f"hersteld uit revisie r{doc['revisies'][-1]['nr']} (bestand ontbrak)"
                doc["meldingen"].append(f"Bestand ontbrak op {now()}; hersteld uit {doc['revisies'][-1]['pad']}.")
            else:
                human, action = fresh, "opnieuw gemaakt (bestand en revisie ontbraken)"
                if doc.get("besluit"):
                    doc["meldingen"].append(f"Bestand en revisie ontbraken op {now()}; het besluit "
                                            f"'{doc['besluit']['besluit']}' is vervallen. Beslis opnieuw.")
                doc.update({"status": "concept", "besluit": None, "handmatig": False})
                doc["gen_hash"] = digest(human)
                add_revision(ws, doc, key, human, "gegenereerd")
        else:
            human, block = split_doc(doc_path.read_text(encoding="utf-8"))
            if doc.get("blok_hash") and block and digest(block) != doc["blok_hash"]:
                n = sum(1 for m in doc["meldingen"] if "pipelineblok" in m) + 1
                saved = ws.dir / "revisies" / key / f"pipelineblok-bewerkt-{n}.md"
                write(saved, block)
                doc["meldingen"].append(f"Een wijziging in het pipelineblok is niet overgenomen; die staat in "
                                        f"{ws.rel(saved)}. Wijzig tekst en URL-pad buiten dit blok.")
            h = digest(human)
            if doc["status"] in ("goedgekeurd", "afgewezen"):
                action = f"bewaard ({doc['status']})"
                if h != doc["revisies"][-1]["hash"]:
                    add_revision(ws, doc, key, human, "na besluit bewerkt")
                    action += ", na het besluit bewerkt"
            elif h != doc["gen_hash"]:
                action = "bewaard (handmatig bewerkt)"
                doc["handmatig"] = True
                if h != doc["revisies"][-1]["hash"]:
                    add_revision(ws, doc, key, human, "handmatig")
            elif digest(fresh) != h:
                human, action = fresh, "bijgewerkt (nieuwe invoer of kopij)"
                doc["gen_hash"] = digest(human)
                add_revision(ws, doc, key, human, "gegenereerd")
            else:
                action = "ongewijzigd"
        # URL path from the document itself (the editor may have changed it)
        url_doc = parse(human)["url_pad"]
        if url_doc and url_doc != item["url_voorstel"]:
            item["url_pad"], doc["url_bron"] = url_doc, "redacteur"
        else:
            doc["url_bron"] = "pipeline"
            item["url_pad"] = item["url_voorstel"] if not url_doc else url_doc
        doc.update({k: item[k] for k in ("week", "maand", "makelaar", "soort", "aanleiding_id", "keuze", "pagina_id",
                                         "keuzereden", "botsing", "url_pad", "beeld", "beeldstatus", "taak")})
        doc["documentpad"] = ws.rel(doc_path)
        generated_now = digest(human) == digest(fresh)
        if generated_now or "kopij" not in doc:
            doc["kopij"] = kopij
        state["docs"][key] = doc
        # feedback counts as applied only when the text was written from a prompt that carried it
        done = {f["feedback"]: f["waar"] for f in copy.get("feedback_verwerkt", [])}
        if doc["kopij"]["fingerprint"] == fp and doc["kopij"]["bron"] == "exact":
            for fb in item["feedback"]:
                fbs = state["feedback"][fb["id"]]
                if fb["id"] in done:
                    fbs["toegepast_in"], fbs["waar"] = key, done[fb["id"]]
                elif fbs.get("toegepast_in") == key:
                    fbs["toegepast_in"], fbs["waar"] = None, None
        checks = check(src, item, human, cfg, state["docs"], site)
        checks += extra_checks(doc, item, human, copy)
        doc["aandacht"] = [f"{lvl}: {txt}" for lvl, txt in checks if lvl != "OK"]
        doc["bron_ids"] = sorted(set(parse(human)["claim_ids"] + [item["aanleiding_id"]]
                                     + ([item["pagina_id"]] if item["pagina_id"] else [])), key=sort_id)
        block = render_pipeline(src, ws, item, doc, checks)
        doc["blok_hash"] = digest(block)
        write(doc_path, human.rstrip("\n") + "\n\n" + block)
        report.append(f"{key}: {action}; {sum(1 for l, _ in checks if l != 'OK')} aandachtspunt(en)")
    state["runs"].append({"tijd": now(), "week": week, "modus": mode})
    ws.save(state)
    write_logs(src, ws, state)
    return report


def extra_checks(doc: dict, item: dict, human: str, copy: dict) -> list[tuple[str, str]]:
    out = []
    kop = doc["kopij"]
    current = digest(human) == doc.get("gen_hash")
    if kop["bron"] == "sjabloon" and current:
        out.append(("AANDACHT", "Kopij uit het sjabloon: er is geen opgeslagen modeluitvoer voor deze invoer. Laat het "
                                "stuk herschrijven (README, 'Nieuwe tekst laten schrijven')."))
    if kop["bron"] == "nabij" and current:
        wanted = ", ".join(fb["id"] for fb in item["feedback"]) or "geen"
        written = ", ".join(f["feedback"] for f in copy.get("feedback_verwerkt", [])) or "geen"
        out.append(("AANDACHT", f"De opgeslagen kopij is geschreven bij andere feedback (verwerkt: {written}; nu geldt: "
                                f"{wanted}). Controleer of de feedback van de redacteur in de tekst zit, of laat het "
                                f"stuk herschrijven met de prompt van deze run."))
    b = doc.get("besluit")
    doc["na_besluit"] = False
    if b and doc["status"] in ("goedgekeurd", "afgewezen") and doc["revisies"][-1]["nr"] != b["revisie"]:
        doc["na_besluit"] = True
        out.append(("AANDACHT", f"De tekst is na het besluit bewerkt (nu revisie r{doc['revisies'][-1]['nr']}, het "
                                f"besluit gold voor r{b['revisie']}). Beslis opnieuw."))
    return out


def ws_rel(path: Path | None) -> str | None:
    return path.relative_to(ROOT).as_posix() if path else None


def sort_id(sid: str):
    return ("NQBXPF".find(sid[0]) if sid[0] in "NQBXPF" else 9, int(re.sub(r"\D", "", sid) or 0))


def add_revision(ws: Workspace, doc: dict, key: str, human: str, kind: str) -> None:
    nr = len(doc["revisies"]) + 1
    path = ws.dir / "revisies" / key / f"r{nr}-{slug(kind)}.md"
    write(path, human)
    doc["revisies"].append({"nr": nr, "soort": kind, "hash": digest(human), "pad": ws.rel(path), "tijd": now()})


# ---------------------------------------------------------------- decisions

def decide(key: str, verdict: str, reason: str | None, ws_name: str = "uitvoer") -> str:
    if verdict not in ("goedgekeurd", "afgewezen"):
        raise PipelineError("Besluit is 'goedgekeurd' of 'afgewezen'.")
    if verdict == "afgewezen" and not (reason or "").strip():
        raise PipelineError("Geef bij afwijzen een reden mee met --reden \"...\".")
    ws = Workspace(ws_name)
    state = ws.load()
    doc = state["docs"].get(key)
    if not doc or "gen_hash" not in doc:
        raise PipelineError(f"Sleutel {key} bestaat niet in {ws_name}. Draai eerst de editie.")
    path = ROOT / doc["documentpad"]
    if not path.exists():
        raise PipelineError(f"{doc['documentpad']} ontbreekt. Draai de editie opnieuw; die herstelt het bestand.")
    human, _ = split_doc(path.read_text(encoding="utf-8"))
    if digest(human) != doc["revisies"][-1]["hash"]:
        add_revision(ws, doc, key, human, "handmatig")
    first = (ROOT / doc["revisies"][0]["pad"]).read_text(encoding="utf-8")
    old_s, new_s = sentences(parse(first)["lezerskopij"]), sentences(parse(human)["lezerskopij"])
    added = [s for s in new_s if s not in old_s]
    removed = [s for s in old_s if s not in new_s]
    rev = doc["revisies"][-1]["nr"]
    diff_rel = None
    if rev > 1:
        diff = "".join(difflib.unified_diff(first.splitlines(True), human.splitlines(True),
                                            fromfile=f"{key} r1 (gegenereerd)", tofile=f"{key} r{rev} ({verdict})"))
        diff_path = ws.dir / "revisies" / key / f"diff-r1-r{rev}.diff"
        write(diff_path, diff)
        diff_rel = ws.rel(diff_path)
    doc["status"] = verdict
    doc["besluit"] = {"besluit": verdict, "reden": (reason or "").strip(), "tijd": now(), "revisie": rev,
                      "toegevoegd": added, "verwijderd": removed, "diff": diff_rel}
    fid = f"FB-{key}"
    if doc["soort"] == "thema" and (verdict == "afgewezen" or added or removed):
        text = reason.strip() if verdict == "afgewezen" else \
            "De redacteur paste je vorige thema aan: " + "; ".join([f"toegevoegd \"{s}\"" for s in added] +
                                                                   [f"verwijderd \"{s}\"" for s in removed])
        state["feedback"][fid] = {"makelaar": doc["makelaar"], "week": doc["week"], "van": key, "soort": verdict,
                                  "tekst": text, "toegepast_in": state["feedback"].get(fid, {}).get("toegepast_in")}
    log = ws.dir / "besluiten.csv"
    new = not log.exists()
    with open(log, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        if new:
            w.writerow(["tijd", "sleutel", "besluit", "reden", "revisie", "toegevoegd", "verwijderd", "diff"])
        w.writerow([doc["besluit"]["tijd"], key, verdict, doc["besluit"]["reden"], f"r{rev}", " | ".join(added),
                    " | ".join(removed), diff_rel or ""])
    state["docs"][key] = doc
    ws.save(state)
    run_block_only(ws, key)
    write_logs(source(), ws, ws.load())
    return f"{key}: {verdict} (revisie r{rev})" + (f"; toegevoegd: {added}" if added else "")


def run_block_only(ws: Workspace, key: str) -> None:
    """Rewrite one document's pipeline block from the current state, without touching the text."""
    state = ws.load()
    doc = state["docs"][key]
    src, site, cfg = source(), sitemap(), settings()
    item = next(i for i in plan(src, ws.load(), doc["week"]) if i["sleutel"] == key)
    item["url_voorstel"] = item["url_pad"]
    item["url_pad"] = doc.get("url_pad", item["url_pad"])
    path = ROOT / doc["documentpad"]
    human, _ = split_doc(path.read_text(encoding="utf-8"))
    checks = check(src, item, human, cfg, state["docs"], site) + extra_checks(doc, item, human, {})
    doc["aandacht"] = [f"{lvl}: {txt}" for lvl, txt in checks if lvl != "OK"]
    block = render_pipeline(src, ws, item, doc, checks)
    doc["blok_hash"] = digest(block)
    write(path, human.rstrip("\n") + "\n\n" + block)
    ws.save(state)


def apply_appendix_b(ws_name: str = "uitvoer") -> list[str]:
    """Enter the two editor decisions from appendix B, as an editor would: edit, then decide."""
    src = source()
    ws = Workspace(ws_name)
    out = []
    for r in src["review"]:
        key = f"{r['na']}-{r['makelaar']}-{r['soort']}"
        doc = ws.load()["docs"].get(key)
        if not doc or "gen_hash" not in doc:
            raise PipelineError(f"{key} bestaat nog niet. Draai eerst editie {r['na']}.")
        if doc["status"] != "concept":
            out.append(f"{key}: al {doc['status']}, niets gedaan")
            continue
        if r["actie"] == "goedgekeurd_met_bewerking":
            path = ROOT / doc["documentpad"]
            text = path.read_text(encoding="utf-8")
            zin = r["bewaar_zin"]
            if zin not in text:
                reader, rest = text.split(READER_END, 1)
                lines = reader.split("\n")
                spots = [i for i, l in enumerate(lines) if re.search(r"\bmeet\b", l, re.I) and not l.startswith("#")]
                i = next((i for i in spots if "thuis" in lines[i].lower()), spots[0] if spots else None)
                if i is None:
                    raise PipelineError(f"Geen plek gevonden om de zin in {key} te zetten; doe het met de hand.")
                lines[i] = lines[i].rstrip() + " " + zin
                write(path, "\n".join(lines) + READER_END + rest)
            out.append(decide(key, "goedgekeurd", None, ws_name))
        else:
            out.append(decide(key, "afgewezen", r["reden"], ws_name))
    return out


# ---------------------------------------------------------------- logs and tasks

def rows_for(ws: Workspace, state: dict) -> list[dict]:
    rows = []
    order = {"terugblik": 0, "thema": 1}
    for key, d in sorted(state["docs"].items(), key=lambda kv: (kv[1].get("week", ""), kv[1].get("makelaar", ""),
                                                               order.get(kv[1].get("soort"), 2))):
        if "gen_hash" not in d:
            continue
        b = d.get("besluit") or {}
        fb = [f"{fid} -> {f.get('waar', '')}" for fid, f in sorted(state["feedback"].items()) if f.get("toegepast_in") == key]
        status = d["status"]
        if d.get("na_besluit"):
            status += " (na besluit bewerkt)"
        elif d.get("handmatig") and d["status"] == "concept":
            status += " (handmatig bewerkt)"
        rows.append({"werkmap": ws.name, "week": d["week"], "makelaar": d["makelaar"], "soort": d["soort"], "sleutel": key,
                     "documentpad": d["documentpad"], "status": status,
                     "bron_ids": " ".join(d.get("bron_ids", [])), "aanleiding": d["aanleiding_id"],
                     "paginakeuze": d["keuze"] + (f" {d['pagina_id']}" if d.get("pagina_id") else ""),
                     "keuzereden": d["keuzereden"], "url_pad": d["url_pad"],
                     "beeld": d["beeld"] or "", "beeldstatus": d["beeldstatus"],
                     "besluit": b.get("besluit", ""), "reden": b.get("reden", ""),
                     "revisie": f"r{d['revisies'][-1]['nr']} {d['revisies'][-1]['pad']}",
                     "feedback_verwerkt": "; ".join(fb), "aandacht": " / ".join(d.get("aandacht", [])),
                     "kopij": d["kopij"]["bestand"] or "sjabloon"})
    return rows


def csv_text(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=LOG_COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def write_logs(src: dict, ws: Workspace, state: dict) -> None:
    write(ws.dir / "redactielog.csv", csv_text(rows_for(ws, state)))
    tasks = ["# Open taken voor de redacteur", "", f"Werkmap `{ws.name}`. De pipeline schrijft dit bestand bij elke run opnieuw.", ""]
    for key, d in sorted(state["docs"].items()):
        if "gen_hash" not in d:
            continue
        for a in d.get("aandacht", []):
            tasks.append(f"- [ ] {key}: {a}")
    write(ws.dir / "taken.md", "\n".join(tasks) + "\n")
    all_rows = []
    for name in settings()["werkmappen"]:
        w = Workspace(name)
        if w.state_path.exists():
            all_rows += rows_for(w, w.load())
    write(ROOT / "redactielog.csv", csv_text(all_rows))


def reset(ws_name: str = "uitvoer", sure: bool = False) -> str:
    ws = Workspace(ws_name)
    if ws_name in PROTECTED and not sure:
        raise PipelineError(f"{ws_name}/ bevat de meegeleverde voorbeelden. Wil je die echt wissen, voeg dan --ja toe.")
    if ws.dir.exists():
        shutil.rmtree(ws.dir)
    ws.dir.mkdir()
    write(ws.dir / ".gitkeep", "")
    write_logs(source(), ws, ws.load())
    return f"{ws_name}/ is leeg."


def status(ws_name: str = "uitvoer") -> str:
    ws = Workspace(ws_name)
    rows = rows_for(ws, ws.load())
    if not rows:
        return f"Nog geen concepten in {ws_name}/."
    return "\n".join(f"{r['sleutel']:<18} {r['status']:<32} {r['aanleiding']:<4} {r['url_pad']:<38} "
                     f"beeld: {r['beeld'] or 'taak'}" for r in rows)
