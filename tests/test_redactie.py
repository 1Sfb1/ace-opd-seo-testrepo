"""Unit tests for the checks and helpers. Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import redactie as r  # noqa: E402

SRC = r.source()
CFG = r.settings()
SITE = r.sitemap()


def item(kind="thema", path="/gids/nieuw-onderwerp", keuze="nieuw", beeld="vrijgegeven"):
    prof = SRC["profielen"][0]
    return {"sleutel": f"W50-M1-{kind}", "soort": kind, "aanleiding_id": "Q1" if kind == "thema" else "N1",
            "url_pad": path, "keuze": keuze, "profiel": prof, "beeldstatus": beeld, "beeld": "F1",
            "bestand": "meander-berging.jpg", "taak": "test", "botsing": False, "week": "W50"}


def doc(body="Meet je fiets. Je hebt 1,10 m.", claims="| x | B1 | y |"):
    return (f"# Kop\n\n_Onderkop_\n\n{body}\n\n**Over de auteur.** Bio.\n\n{r.READER_END}\n\n## Voor de website\n\n"
            f"- Metatitel: Titel\n- Metabeschrijving: Beschrijving\n- Tags: a, b, c\n- URL-pad: /gids/nieuw-onderwerp\n\n## Voor de reviewer\n\n"
            f"### Claims en bronnen\n\n| Claim | Bron | Bronregel |\n|---|---|---|\n{claims}\n")


def levels(checks, level):
    return [t for lvl, t in checks if lvl == level]


class Checks(unittest.TestCase):
    def test_clean_doc_has_no_errors(self):
        res = r.check(SRC, item(), doc(), CFG, {}, SITE)
        self.assertEqual(levels(res, "FOUT"), [])

    def test_unconfirmed_price_claim_is_an_error(self):
        res = r.check(SRC, item(), doc("De prijzen gingen 12% omhoog, zeg je?"), CFG, {}, SITE)
        self.assertTrue(any("X1" in t for t in levels(res, "FOUT")))

    def test_claim_citing_x1_is_an_error(self):
        res = r.check(SRC, item(), doc(claims="| prijs | X1 | y |"), CFG, {}, SITE)
        self.assertTrue(any("X1" in t for t in levels(res, "FOUT")))

    def test_word_limit(self):
        res = r.check(SRC, item(), doc("je " * 601), CFG, {}, SITE)
        self.assertTrue(any("601 woorden" in t for t in levels(res, "FOUT")))

    def test_number_without_source(self):
        res = r.check(SRC, item(), doc("Je hebt 2,40 m nodig."), CFG, {}, SITE)
        self.assertTrue(any("2,40" in t for t in levels(res, "AANDACHT")))

    def test_list_numbers_are_not_claims(self):
        res = r.check(SRC, item(), doc("1. Meet je fiets.\n2. Neem een meetlint mee."), CFG, {}, SITE)
        self.assertFalse(any("Getal" in t for t in levels(res, "AANDACHT")))

    def test_duplicate_path_in_sitemap(self):
        res = r.check(SRC, item(path="/gids/terras-onderhouden"), doc(), CFG, {}, SITE)
        self.assertTrue(any("bestaat al" in t for t in levels(res, "AANDACHT")))

    def test_duplicate_path_in_other_draft(self):
        res = r.check(SRC, item(), doc(), CFG, {"W51-M2-thema": {"url_pad": "/gids/nieuw-onderwerp"}}, SITE)
        self.assertTrue(any("W51-M2-thema" in t for t in levels(res, "AANDACHT")))

    def test_missing_metadata(self):
        res = r.check(SRC, item(), doc().replace("- Metatitel: Titel", "- Metatitel:"), CFG, {}, SITE)
        self.assertIn("Metatitel ontbreekt.", levels(res, "FOUT"))

    def test_formal_u_is_flagged(self):
        res = r.check(SRC, item(), doc("Meet uw fiets."), CFG, {}, SITE)
        self.assertTrue(any("'u'" in t for t in levels(res, "AANDACHT")))

    def test_image_task(self):
        res = r.check(SRC, item(beeld="beeldtaak"), doc(), CFG, {}, SITE)
        self.assertTrue(any("Beeldtaak" in t for t in levels(res, "AANDACHT")))

    def test_spelled_out_percentage_and_price_rise(self):
        res = r.check(SRC, item(), doc("De prijzen zijn met twaalf procent gestegen."), CFG, {}, SITE)
        self.assertTrue(any("percentage" in t and "prijsontwikkeling" in t for t in levels(res, "FOUT")))

    def test_number_needs_its_own_context(self):
        # 'Hof 8' is in B2, but '8 uur zon' is not
        res = r.check(SRC, item(), doc("Bij Hof 8 krijgt de kamer 8 uur zon.", claims="| x | B2 | y |"), CFG, {}, SITE)
        self.assertTrue(any("8 uur" in t for t in levels(res, "AANDACHT")))

    def test_part_of_a_number_is_not_the_number(self):
        res = r.check(SRC, item(), doc("Reken op 10 cm speling. Je hebt 1,10 m."), CFG, {}, SITE)
        self.assertTrue(any("10 cm" in t for t in levels(res, "AANDACHT")))

    def test_spelled_out_measure(self):
        res = r.check(SRC, item(), doc("De kamer krijgt zes uur zon, zeg je."), CFG, {}, SITE)
        self.assertTrue(any("zes uur" in t for t in levels(res, "AANDACHT")))

    def test_update_without_change_table(self):
        it = item(path="/gids/fietsberging", keuze="update")
        it["pagina"] = {"pad": "/gids/fietsberging"}
        res = r.check(SRC, it, doc(), CFG, {}, SITE)
        self.assertTrue(any("wijzigingentabel" in t for t in levels(res, "AANDACHT")))


class Robustness(unittest.TestCase):
    def test_new_cleared_photo_beats_expired_one(self):
        src = {**SRC, "beeldregister": SRC["beeldregister"] + [
            {"id": "F5", "bestand": "nieuw.jpg", "gebied": "Lindehof", "onderwerp": "route naar fietsenstalling",
             "recht": "vrijgegeven"}]}
        got = r.pick_image(src, "Lindehof", "route naar de fietsenstalling")
        self.assertEqual((got["beeld"], got["beeldstatus"]), ("F5", "vrijgegeven"))

    def test_later_week_first_keeps_calendar_order(self):
        qid, why, clash = r.choose_question(SRC, {"docs": {}, "feedback": {}}, "W51-M2-thema", "W51", "M2")
        self.assertEqual((qid, clash), ("Q4", False))
        self.assertIn("W50-M2-thema", why)

    def test_input_folders_are_not_workspaces(self):
        for name in ("invoer", "kopij", "tests"):
            with self.assertRaises(r.PipelineError):
                r.Workspace(name)

    def test_examples_need_confirmation_to_reset(self):
        with self.assertRaises(r.PipelineError):
            r.reset("voorbeelden")


class Planning(unittest.TestCase):
    def test_expired_image_becomes_task(self):
        got = r.pick_image(SRC, "Lindehof", "route naar de fietsenstalling")
        self.assertEqual(got["beeldstatus"], "beeldtaak")
        self.assertIn("F4", got["taak"])

    def test_rejected_theme_keeps_its_question_this_month(self):
        state = {"docs": {"W50-M2-thema": {"soort": "thema", "maand": "2026-12", "aanleiding_id": "Q2",
                                           "status": "afgewezen"}}, "feedback": {}}
        qid, why, clash = r.choose_question(SRC, state, "W51-M2-thema", "W51", "M2")
        self.assertEqual((qid, clash), ("Q4", False))
        self.assertIn("afgewezen", why)

    def test_sentences_find_added_sentence(self):
        old = r.sentences("1. Meet thuis je fiets.")
        new = r.sentences("1. Meet thuis je fiets. Meet thuis ook hoe breed je stuur is.")
        self.assertEqual([s for s in new if s not in old], ["Meet thuis ook hoe breed je stuur is."])


if __name__ == "__main__":
    unittest.main()
