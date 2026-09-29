"""De hele run in één functie: inlezen -> koppelen -> kenmerken -> (evaluatie) -> leadlijst.

CLI, GitHub-workflow en (later) de Streamlit-app roepen allemaal `run` aan."""

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import joblib

from . import cbs, evaluatie, export, kenmerken, model
from .inlezen import lees_bronnen

log = logging.getLogger(__name__)


@dataclass
class Resultaat:
    uitmap: Path
    rapport: str
    bestanden: list = field(default_factory=list)


def run(tios_pad, assetmaps_pad, uitmap, cfg, evalueren=False, gemeente=None, max_adressen=None):
    uitmap = Path(uitmap)
    uitmap.mkdir(parents=True, exist_ok=True)
    max_adressen = max_adressen or cfg.excel_max_adressen

    tios, assetmaps, waarschuwingen = lees_bronnen(tios_pad, assetmaps_pad, cfg)
    assetmaps, cbs_stats, cbs_waarschuwingen = cbs.voeg_cbs_toe(assetmaps, cfg)
    waarschuwingen += cbs_waarschuwingen

    per_vbo, per_pand = kenmerken.vat_tios_samen(tios, cfg)
    data = kenmerken.koppel(assetmaps, per_vbo, per_pand)
    gekoppeld = int(data["aantal_tios_regels"].notna().sum())
    if gekoppeld == 0:
        raise ValueError(
            "Geen enkel TIOS-adres gekoppeld aan Assetmaps. Controleer vbo_id in beide bestanden."
        )
    data, numeriek, categorisch = kenmerken.maak_kenmerken(data, cfg)
    y = data["is_klant"].to_numpy()
    if y.sum() < 10:
        raise ValueError(f"Maar {y.sum()} klanten gevonden; te weinig om een model te trainen.")
    log.info("%d adressen, %d klanten, %d kenmerken.", len(data), y.sum(), len(numeriek) + len(categorisch))

    ev = None
    if evalueren:
        log.info("Evaluatie: kruisvalidatie ...")
        ev = {"cv": evaluatie.kruisvalidatie(data, y, numeriek, categorisch, cfg)}
        log.info("Evaluatie: nieuwe postcodegebieden ...")
        ev["groep"] = evaluatie.kruisvalidatie(
            data, y, numeriek, categorisch, cfg, groepen=data["postcode4"]
        )
        log.info("Evaluatie: tijdsbacktest ...")
        ev["backtest"] = evaluatie.tijdsbacktest(data, y, data["klant_jaar"], numeriek, categorisch, cfg)
        log.info("Evaluatie: belangrijkste kenmerken ...")
        ev["holdout_auc"], ev["belangrijkheid"] = evaluatie.belangrijkste_kenmerken(
            data, y, numeriek, categorisch, cfg
        )

    log.info("Leadlijst scoren (out-of-fold) ...")
    kans = model.scoor_out_of_fold(data, y, numeriek, categorisch, cfg)
    aantallen = kenmerken.klanten_in_de_buurt(data, y)
    data["klanten_in_buurt"] = aantallen["buurt_sleutel"]
    data["klanten_in_postcode4"] = aantallen["postcode4"]

    niet_klant = y == 0
    leads = export.voeg_score_toe(data[niet_klant], kans[niet_klant], cfg)
    if gemeente:
        leads = leads[leads["gemeente"].astype(str).str.lower() == gemeente.strip().lower()]
        if leads.empty:
            raise ValueError(f"Gemeente '{gemeente}' komt niet voor in de data.")
    leadlijst = export.maak_leadlijst(leads)

    kwaliteit = export.kwaliteit_regels(
        ev, float(y.mean()), waarschuwingen, dt.date.today().isoformat(),
        [Path(tios_pad).name, Path(assetmaps_pad).name],
    )
    excel_pad, csv_pad = uitmap / "leadlijst.xlsx", uitmap / "leadlijst_volledig.csv"
    aantal_witte_vlekken = export.schrijf_excel(excel_pad, leadlijst, max_adressen, kwaliteit)
    export.schrijf_csv(csv_pad, leadlijst)

    # Eindmodel op alle data, voor later scoren zonder opnieuw te trainen (bijv. in de app).
    train_data = data.copy()
    for naam, waarde in kenmerken.regio_train(data, y, cfg).items():
        train_data[naam] = waarde
    eindmodel = model.Ensemble(numeriek, categorisch, cfg).fit(train_data, y)
    model_pad = uitmap / "model.joblib"
    joblib.dump({"model": eindmodel, "gemaakt": dt.datetime.now().isoformat(timespec="seconds"),
                 "kenmerken": eindmodel.kenmerken}, model_pad)

    info = {
        "datum": dt.date.today().isoformat(),
        "adressen": len(data), "klanten": int(y.sum()), "toevalskans": float(y.mean()),
        "eerder_contact": int(data["eerder_contact"].sum()),
        "leads": len(leadlijst), "witte_vlekken": aantal_witte_vlekken,
        "kenmerken": numeriek + categorisch, "cbs": cbs_stats,
        "waarschuwingen": waarschuwingen, "evaluatie": ev,
    }
    rapport = export.maak_rapport(info)
    rapport_pad = uitmap / "modelrapport.md"
    rapport_pad.write_text(rapport, encoding="utf-8")
    log.info("Klaar. Resultaten in %s", uitmap)
    return Resultaat(uitmap, rapport, [excel_pad, csv_pad, rapport_pad, model_pad])
