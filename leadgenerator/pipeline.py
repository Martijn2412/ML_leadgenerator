"""De hele run in één functie: inlezen -> koppelen -> kenmerken -> (evaluatie) -> leadlijst.

CLI, GitHub-workflow en (later) de Streamlit-app roepen allemaal `run` aan."""

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np

from . import cbs, controles, evaluatie, export, kenmerken, model, redenen
from .inlezen import lees_bronnen

log = logging.getLogger(__name__)


@dataclass
class Resultaat:
    uitmap: Path
    rapport: str
    bestanden: list = field(default_factory=list)


def label_check(tios_pad, assetmaps_pad, cfg):
    """Alleen inlezen, koppelen en de label-controle; geen model (snel)."""
    tios, assetmaps, _ = lees_bronnen(tios_pad, assetmaps_pad, cfg)
    per_vbo, per_pand = kenmerken.vat_tios_samen(tios, cfg)
    data = kenmerken.koppel(assetmaps, per_vbo, per_pand)
    data, _, _ = kenmerken.maak_kenmerken(data, cfg)
    return controles.label_controle(data, cfg.label_lek_drempel)


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
    label_controle = controles.label_controle(data, cfg.label_lek_drempel)
    if label_controle:
        log.info(label_controle["tekst"])
        if label_controle["lek"] and cfg.energielabel_bij_klanten == "gebruiken":
            waarschuwingen.append(label_controle["tekst"])
    y = data["is_klant"].to_numpy()
    if y.sum() < 10:
        raise ValueError(f"Maar {y.sum()} klanten gevonden; te weinig om een model te trainen.")
    log.info("%d adressen, %d klanten, %d kenmerken.", len(data), y.sum(), len(numeriek) + len(categorisch))

    # Voor het model alleen de benodigde kolommen: per fold wordt deze tabel gekopieerd, en met
    # alle Assetmaps-kolommen kost dat bij een grote provincie te veel geheugen.
    modelkolommen = list(dict.fromkeys(
        numeriek + categorisch + [kolom for kolom, _ in kenmerken.REGIO_KOLOMMEN]
    ))
    mdata = data[modelkolommen]

    ev = None
    if evalueren:
        log.info("Evaluatie: kruisvalidatie ...")
        ev = {"cv": evaluatie.kruisvalidatie(mdata, y, numeriek, categorisch, cfg)}
        log.info("Evaluatie: nieuwe postcodegebieden ...")
        ev["groep"] = evaluatie.kruisvalidatie(
            mdata, y, numeriek, categorisch, cfg, groepen=mdata["postcode4"]
        )
        log.info("Evaluatie: tijdsbacktest ...")
        ev["backtest"] = evaluatie.tijdsbacktest(mdata, y, data["klant_jaar"], numeriek, categorisch, cfg)
        log.info("Evaluatie: belangrijkste kenmerken ...")
        ev["holdout_auc"], ev["belangrijkheid"] = evaluatie.belangrijkste_kenmerken(
            mdata, y, numeriek, categorisch, cfg
        )

    log.info("Leadlijst scoren (out-of-fold) ...")
    kans = model.scoor_out_of_fold(mdata, y, numeriek, categorisch, cfg)
    aantallen = kenmerken.klanten_in_de_buurt(data, y)
    data["klanten_in_buurt"] = aantallen["buurt_sleutel"]
    data["klanten_in_postcode4"] = aantallen["postcode4"]

    # Eindmodel op alle data: voor de redenen per adres, en om later te scoren zonder opnieuw
    # te trainen (bijv. in de app).
    log.info("Eindmodel trainen en opslaan ...")
    train_data = mdata.copy()
    for naam, waarde in kenmerken.regio_train(mdata, y, cfg).items():
        train_data[naam] = waarde
    eindmodel = model.Ensemble(numeriek, categorisch, cfg).fit(train_data, y)
    model_pad = uitmap / "model.joblib"
    joblib.dump({"model": eindmodel, "gemaakt": dt.datetime.now().isoformat(timespec="seconds"),
                 "kenmerken": eindmodel.kenmerken}, model_pad)

    niet_klant = y == 0
    leads = export.voeg_score_toe(data[niet_klant], kans[niet_klant], cfg)
    if gemeente:
        leads = leads[leads["gemeente"].astype(str).str.lower() == gemeente.strip().lower()].copy()
        if leads.empty:
            raise ValueError(f"Gemeente '{gemeente}' komt niet voor in de data.")
        gemeente = str(leads["gemeente"].iloc[0])  # schrijfwijze uit de data, niet zoals ingetypt
    log.info("Redenen per adres bepalen ...")
    X_leads = leads[modelkolommen].copy()
    # Buurteffect voor de leads: alle bekende klanten tellen mee (zoals regio_score).
    X_leads["buurt_klanten_nabij"] = np.log1p(leads["klanten_in_buurt"].to_numpy(dtype=float))
    X_leads["postcode4_klanten_nabij"] = np.log1p(leads["klanten_in_postcode4"].to_numpy(dtype=float))
    leads["redenen"] = redenen.bereken_redenen(eindmodel, X_leads)
    leadlijst = export.maak_leadlijst(leads)

    kwaliteit = export.kwaliteit_regels(
        ev, float(y.mean()), waarschuwingen, dt.date.today().isoformat(),
        [Path(tios_pad).name, Path(assetmaps_pad).name],
    )
    excel_pad, csv_pad = uitmap / "leadlijst.xlsx", uitmap / "leadlijst_volledig.csv"
    context = {
        "datum": dt.date.today().strftime("%d-%m-%Y"),
        "bestanden": [Path(tios_pad).name, Path(assetmaps_pad).name],
        "leads": len(leadlijst), "klanten": int(y.sum()), "gemeente": gemeente,
        "max_adressen": max_adressen,
    }
    aantal_witte_vlekken = export.schrijf_excel(excel_pad, leadlijst, max_adressen, kwaliteit, context)
    export.schrijf_csv(csv_pad, leadlijst)


    info = {
        "datum": dt.date.today().isoformat(),
        "adressen": len(data), "klanten": int(y.sum()), "toevalskans": float(y.mean()),
        "eerder_contact": int(data["eerder_contact"].sum()),
        "leads": len(leadlijst), "witte_vlekken": aantal_witte_vlekken,
        "kenmerken": numeriek + categorisch, "cbs": cbs_stats,
        "waarschuwingen": waarschuwingen, "evaluatie": ev,
        "label_controle": label_controle, "energielabel": cfg.energielabel_bij_klanten,
    }
    rapport = export.maak_rapport(info)
    rapport_pad = uitmap / "modelrapport.md"
    rapport_pad.write_text(rapport, encoding="utf-8")
    log.info("Klaar. Resultaten in %s", uitmap)
    return Resultaat(uitmap, rapport, [excel_pad, csv_pad, rapport_pad, model_pad])
