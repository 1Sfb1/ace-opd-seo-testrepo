"""Command line for the Monday desk. Run `python run.py --help`."""
import argparse
import sys

import redactie


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python run.py", description="Maandagredactie Kade & Hof Wonen")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def ws(p):
        p.add_argument("--werkmap", default="uitvoer", help="map voor concepten en log (standaard: uitvoer)")

    p = sub.add_parser("editie", help="maak of ververs de vier concepten van een week")
    p.add_argument("--week", required=True, help="bijvoorbeeld W50")
    p.add_argument("--modus", choices=["opgeslagen", "sjabloon"], help="overschrijft invoer/instellingen.json")
    ws(p)
    p = sub.add_parser("besluit", help="keur een concept goed of wijs het af")
    p.add_argument("sleutel", help="bijvoorbeeld W50-M2-thema")
    p.add_argument("besluit", choices=["goedgekeurd", "afgewezen"])
    p.add_argument("--reden", help="verplicht bij afwijzen")
    p.add_argument("--ondanks-fout", action="store_true", help="keur goed terwijl de controle nog een FOUT meldt")
    ws(p)
    p = sub.add_parser("bijlage-b", help="voer de twee redactiebesluiten uit bijlage B in (bewerking + afwijzing)")
    ws(p)
    p = sub.add_parser("status", help="toon de concepten en hun status")
    ws(p)
    p = sub.add_parser("reset", help="maak de werkmap leeg (alleen voor een schone proef)")
    p.add_argument("--ja", action="store_true", help="nodig om de meegeleverde voorbeelden te wissen")
    ws(p)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "editie":
            out = redactie.run_edition(a.week.upper(), a.werkmap, a.modus)
        elif a.cmd == "besluit":
            out = [redactie.decide(a.sleutel, a.besluit, a.reden, a.werkmap, a.ondanks_fout)]
        elif a.cmd == "bijlage-b":
            out = redactie.apply_appendix_b(a.werkmap)
        elif a.cmd == "status":
            out = [redactie.status(a.werkmap)]
        else:
            out = [redactie.reset(a.werkmap, a.ja)]
    except redactie.PipelineError as e:
        print(f"Fout: {e}", file=sys.stderr)
        return 2
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
