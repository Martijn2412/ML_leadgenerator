"""Hoe goed is het model? Kruisvalidatie, nieuwe postcodegebieden, tijdsbacktest en
belangrijkste kenmerken."""

import logging

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, StratifiedKFold, train_test_split

from .model import scoor_out_of_fold, train_en_voorspel

log = logging.getLogger(__name__)


def precision_at_k(y_werkelijk, kans, k):
    """Aandeel echte klanten in de k adressen met de hoogste kans."""
    volgorde = np.argsort(-np.asarray(kans), kind="stable")[:k]
    return float(np.asarray(y_werkelijk)[volgorde].mean())


def _scores(y, kans, k_waarden):
    uit = {"auc": roc_auc_score(y, kans)}
    for k in k_waarden:
        if k <= len(y):
            uit[f"p@{k}"] = precision_at_k(y, kans, k)
    return uit


def _gemiddeld(per_fold):
    if not per_fold:
        return {}
    df = pd.DataFrame(per_fold)
    return {"gemiddeld": df.mean().to_dict(), "spreiding": df.std(ddof=0).to_dict(), "folds": len(df)}


def kruisvalidatie(data, y, numeriek, categorisch, cfg, groepen=None):
    """Willekeurige (stratified) kruisvalidatie, of per postcodegebied als `groepen` gegeven is.
    Per postcodegebied meet: hoe goed werkt het model in gebieden waar we nog nooit waren?"""
    y = np.asarray(y)
    if groepen is None:
        cv = StratifiedKFold(cfg.cv_folds, shuffle=True, random_state=cfg.random_state)
        splits = cv.split(data, y)
    else:
        groepen = pd.Series(groepen).fillna("onbekend").to_numpy()
        splits = GroupKFold(cfg.groep_folds).split(data, y, groups=groepen)
    per_fold = []
    for fold, (train_pos, test_pos) in enumerate(splits, start=1):
        if y[test_pos].sum() == 0:
            continue
        _, kans, _ = train_en_voorspel(data, y, train_pos, test_pos, numeriek, categorisch, cfg)
        per_fold.append(_scores(y[test_pos], kans, cfg.k_waarden))
        log.info("Fold %d klaar (AUC %.3f).", fold, per_fold[-1]["auc"])
    return _gemiddeld(per_fold)


def tijdsbacktest(data, y, klant_jaar, numeriek, categorisch, cfg):
    """Doet alsof het (laatste jaar - backtest_jaren) is: train met de klanten die er toen
    waren, maak de leadlijst op dezelfde manier als in productie, en kijk of de klanten van
    de jaren erna bovenaan staan. Dit is de eerlijkste maat voor 'wordt dit adres klant'."""
    y = np.asarray(y)
    jaar = pd.Series(klant_jaar).to_numpy(dtype=float)
    if np.isnan(jaar[y == 1]).all():
        return {"overgeslagen": "geen orderjaren in TIOS gevonden"}
    grens = int(np.nanmax(jaar)) - cfg.backtest_jaren
    bekend = (y == 1) & (jaar <= grens)
    nieuw = (y == 1) & (jaar > grens)
    bruikbaar = ~((y == 1) & np.isnan(jaar))  # klant zonder bekend jaar: niet te plaatsen
    if bekend.sum() < 20 or nieuw.sum() < 5:
        return {"overgeslagen": f"te weinig klanten voor/na {grens} ({bekend.sum()} / {nieuw.sum()})"}

    sub = data[bruikbaar].reset_index(drop=True)
    y_toen = bekend[bruikbaar].astype(int)
    kans = scoor_out_of_fold(sub, y_toen, numeriek, categorisch, cfg)
    kandidaten = y_toen == 0
    doel = nieuw[bruikbaar][kandidaten].astype(int)
    uit = _scores(doel, kans[kandidaten], cfg.k_waarden)
    uit.update({"grensjaar": grens, "klanten_tot_grens": int(bekend.sum()),
                "nieuwe_klanten": int(nieuw.sum()), "toevalskans": float(doel.mean())})
    return uit


def belangrijkste_kenmerken(data, y, numeriek, categorisch, cfg, herhalingen=3):
    """Permutatietest op het hele ensemble: hoeveel AUC gaat er verloren als je één kenmerk
    door elkaar husselt? Groot verlies = belangrijk kenmerk."""
    y = np.asarray(y)
    posities = np.arange(len(data))
    train_pos, test_pos = train_test_split(
        posities, test_size=0.2, random_state=cfg.random_state, stratify=y
    )
    model, _, fold_data = train_en_voorspel(data, y, train_pos, test_pos, numeriek, categorisch, cfg)
    rng = np.random.default_rng(cfg.random_state)
    if len(test_pos) > cfg.permutatie_steekproef:
        test_pos = rng.choice(test_pos, cfg.permutatie_steekproef, replace=False)
    X = fold_data.iloc[test_pos][model.kenmerken].reset_index(drop=True)
    basis = roc_auc_score(y[test_pos], model.predict_proba(X))

    verlies = {}
    for kolom in model.kenmerken:
        afnames = []
        for _ in range(herhalingen):
            geschud = X.copy()
            geschud[kolom] = rng.permutation(geschud[kolom].to_numpy())
            afnames.append(basis - roc_auc_score(y[test_pos], model.predict_proba(geschud)))
        verlies[kolom] = float(np.mean(afnames))
    return basis, pd.Series(verlies).sort_values(ascending=False)
