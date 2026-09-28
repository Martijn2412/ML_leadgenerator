"""Leadgenerator vanaf de opdrachtregel.

    python cli.py run --tios TIOS.xlsx --assetmaps Woningen_Zeeland.xlsx
    python cli.py cbs-vernieuwen

Alle opties van `run` kunnen ook via omgevingsvariabelen (LEADGEN_...) worden gezet;
de GitHub-workflow gebruikt dat.
"""

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

from leadgenerator import cbs
from leadgenerator.config import laad_config
from leadgenerator.pipeline import run


def _env(naam, standaard=None):
    waarde = os.environ.get(f"LEADGEN_{naam}", "").strip()
    return waarde or standaard


def _ja(waarde):
    return str(waarde).strip().lower() in {"1", "true", "ja", "yes", "j", "y"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Leadgenerator Takkenkamp")
    parser.add_argument("--config", default=_env("CONFIG"), help="pad naar config.yaml")
    sub = parser.add_subparsers(dest="opdracht", required=True)

    p_run = sub.add_parser("run", help="model trainen en leadlijst maken")
    p_run.add_argument("--map", default=_env("MAP", "."),
                       help="map met de Excel-bestanden; output komt in <map>/output/")
    p_run.add_argument("--tios", default=_env("TIOS"), help="TIOS-bestand (in --map)")
    p_run.add_argument("--assetmaps", default=_env("ASSETMAPS"), help="Assetmaps-bestand (in --map)")
    p_run.add_argument("--gemeente", default=_env("GEMEENTE"), help="alleen deze gemeente in de lijst")
    p_run.add_argument("--max-adressen", type=int, default=int(_env("MAX_ADRESSEN", "0")) or None,
                       help="max. adressen per Excel-tabblad")
    p_run.add_argument("--geen-evaluatie", action="store_true",
                       default=not _ja(_env("EVALUATIE", "ja")), help="sla de kwaliteitstest over")
    p_run.add_argument("--uit", default=_env("UIT"), help="outputmap (standaard <map>/output/<datum>_<naam>)")

    sub.add_parser("cbs-vernieuwen", help="CBS-buurtcijfers opnieuw ophalen naar data/cbs/")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = laad_config(args.config)

    if args.opdracht == "cbs-vernieuwen":
        mislukt = [naam for naam, spec in cfg.cbs.items()
                   if cbs.laad_cbs_kenmerk(naam, spec, vernieuwen=True) is None]
        return 1 if mislukt else 0

    if not args.tios or not args.assetmaps:
        parser.error("geef --tios en --assetmaps op (of LEADGEN_TIOS / LEADGEN_ASSETMAPS)")
    basis = Path(args.map)
    tios_pad, assetmaps_pad = basis / args.tios, basis / args.assetmaps
    for pad in (tios_pad, assetmaps_pad):
        if not pad.exists():
            parser.error(f"bestand niet gevonden: {pad}")
    uitmap = Path(args.uit) if args.uit else (
        basis / "output" / f"{dt.datetime.now():%Y-%m-%d_%H%M}_{assetmaps_pad.stem}"
    )

    resultaat = run(tios_pad, assetmaps_pad, uitmap, cfg, evalueren=not args.geen_evaluatie,
                    gemeente=args.gemeente, max_adressen=args.max_adressen)

    samenvatting = os.environ.get("GITHUB_STEP_SUMMARY")
    if samenvatting:
        with open(samenvatting, "a", encoding="utf-8") as f:
            f.write(resultaat.rapport)
            f.write(f"\n**Resultaten staan in:** `{resultaat.uitmap}`\n")
    print(f"\nResultaten staan in: {resultaat.uitmap}")
    for pad in resultaat.bestanden:
        print(f"  - {pad.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
