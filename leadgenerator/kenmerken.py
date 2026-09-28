"""TIOS samenvatten, koppelen aan Assetmaps, opschonen en kenmerken maken."""

import logging
import re

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from .cbs import normaliseer_naam

log = logging.getLogger(__name__)

# Buurteffect: per adres het (gedempte) aantal klanten in dezelfde buurt en hetzelfde
# postcode4-gebied. De buurt is gemeente + buurtnaam: "Centrum" in Middelburg en
# "Centrum" in Vlissingen zijn verschillende buurten.
REGIO_KOLOMMEN = [
    ("buurt_sleutel", "buurt_klanten_nabij"),
    ("postcode4", "postcode4_klanten_nabij"),
]

BASIS_NUMERIEK = [
    "vbo_oppervlakte", "pandbouwjaar", "pandoppervlakte", "koop", "woz",
    "gasverbruik", "gemiddeld_inkomen", "buurt_frequentie", "woningen_in_pand",
    "voor_spouwmuurnorm_1975", "voor_hrpp_norm_1995", "energieklasse_rang",
    "buurt_klanten_nabij", "postcode4_klanten_nabij",
]
CATEGORISCH = ["gemeente"]

# Kenmerken waarvoor een "_ontbreekt"-kolom gemaakt mag worden.
MISSING_KANDIDATEN = [
    "vbo_oppervlakte", "pandbouwjaar", "pandoppervlakte", "koop", "woz",
    "gasverbruik", "gemiddeld_inkomen", "energieklasse_rang",
]

LABEL_RANG = {letter: i for i, letter in enumerate("ABCDEFG", start=1)}


def vat_tios_samen(tios, cfg):
    """Per adres (vbo_id): ooit een order, jaar van de eerste order, en ooit contact.
    Per pand (pand_id): ooit een order en jaar van de eerste order."""
    datum, status = cfg.tios_kolommen["datum"], cfg.tios_kolommen["status"]
    t = tios.copy()
    t["_jaar"] = pd.to_datetime(t[datum], errors="coerce", dayfirst=True).dt.year
    t["_is_order"] = t[status].isin(cfg.order_statussen)
    t["_order_jaar"] = t["_jaar"].where(t["_is_order"])

    per_vbo = t.dropna(subset=["vbo_id"]).groupby("vbo_id").agg(
        heeft_order_status=("_is_order", "any"),
        klant_jaar_vbo=("_order_jaar", "min"),
        aantal_tios_regels=("_is_order", "size"),
    ).reset_index()
    per_pand = t.dropna(subset=["pand_id"]).groupby("pand_id").agg(
        heeft_order_status_pand=("_is_order", "any"),
        klant_jaar_pand=("_order_jaar", "min"),
    ).reset_index()

    onbekend = sorted(set(t[status].dropna().unique()) - set(cfg.order_statussen))
    log.info("TIOS-statussen die níet als order tellen: %s", onbekend)
    return per_vbo, per_pand


def koppel(assetmaps, per_vbo, per_pand):
    """Koppelt de TIOS-samenvatting aan Assetmaps en maakt het label `is_klant`.

    Een adres is klant als Assetmaps dat zegt, als het adres in TIOS een order had, of als het
    pand een order had én het pand maar één woning bevat. Bij een appartementencomplex zegt een
    order van één bewoner niets over de buren, dus daar telt de pand-order niet."""
    df = assetmaps.merge(per_vbo, on="vbo_id", how="left")
    df = df.merge(per_pand, on="pand_id", how="left")
    df["woningen_in_pand"] = df.groupby("pand_id")["vbo_id"].transform("size")
    grondgebonden = df["woningen_in_pand"].fillna(1) <= 1

    vlag = pd.Series(False, index=df.index)
    if "klant" in df.columns:
        vlag = df["klant"].astype("string").str.strip().str.lower().isin(["1", "true", "ja", "j"])
    vbo_order = df["heeft_order_status"].eq(True)
    pand_order = df["heeft_order_status_pand"].eq(True) & grondgebonden

    df["is_klant"] = (vlag | vbo_order | pand_order).astype(int)
    df["klant_jaar"] = df["klant_jaar_vbo"].where(vbo_order)
    df["klant_jaar"] = df["klant_jaar"].fillna(df["klant_jaar_pand"].where(pand_order))
    df["eerder_contact"] = (df["aantal_tios_regels"].notna() & (df["is_klant"] == 0)).astype(int)
    return df.reset_index(drop=True)


def vervang_missing_code(df, code):
    """-99997 betekent 'onbekend' in Assetmaps: in álle getalkolommen leeg maken."""
    getallen = df.select_dtypes(include="number").columns
    df[getallen] = df[getallen].replace(code, np.nan)
    return df


def energielabel_rang(serie):
    """A=1 ... G=7; elke '+' maakt het label 0,2 beter (A++ = 0,6). Onbekend wordt leeg."""
    def rang(label):
        if not isinstance(label, str):
            return np.nan
        match = re.fullmatch(r"\s*([A-Ga-g])(\+*)\s*", label)
        if not match:
            return np.nan
        return LABEL_RANG[match.group(1).upper()] - 0.2 * len(match.group(2))
    return serie.map(rang).astype(float)


def postcode4(serie):
    schoon = serie.astype("string").str.replace(r"\s", "", regex=True).str.upper()
    return schoon.str[:4].where(schoon.str.match(r"^\d{4}"))


def maak_kenmerken(df, cfg):
    """Maakt de afgeleide kenmerken en de "_ontbreekt"-kolommen.
    Geeft (df, numerieke_kenmerken, categorische_kenmerken)."""
    df = vervang_missing_code(df, cfg.missing_code)

    bouwjaar = df.get("pandbouwjaar", pd.Series(np.nan, index=df.index))
    df["voor_spouwmuurnorm_1975"] = (bouwjaar < 1975).astype(int)
    df["voor_hrpp_norm_1995"] = (bouwjaar < 1995).astype(int)
    df["energieklasse_rang"] = (
        energielabel_rang(df["energieklasse"]) if "energieklasse" in df.columns else np.nan
    )
    df["buurt_sleutel"] = normaliseer_naam(df["gemeente"]) + "|" + normaliseer_naam(df["buurtnaam"])
    df["buurt_frequentie"] = df.groupby("buurt_sleutel")["vbo_id"].transform("size")
    df["postcode4"] = postcode4(df["postcode"])

    missing_indicatoren = []
    for kolom in MISSING_KANDIDATEN:
        if kolom in df.columns and df[kolom].isna().mean() > cfg.missing_indicator_drempel:
            df[f"{kolom}_ontbreekt"] = df[kolom].isna().astype(int)
            missing_indicatoren.append(f"{kolom}_ontbreekt")

    # Regio-kenmerken worden per fold berekend; hier alleen een lege plek.
    for _, naam in REGIO_KOLOMMEN:
        df[naam] = 0.0

    numeriek = []
    for kolom in BASIS_NUMERIEK + missing_indicatoren:
        if kolom not in df.columns:
            log.warning("Kenmerk '%s' ontbreekt in de data en wordt overgeslagen.", kolom)
        elif df[kolom].notna().any():
            df[kolom] = pd.to_numeric(df[kolom], errors="coerce")
            numeriek.append(kolom)
        else:
            log.warning("Kenmerk '%s' is overal leeg en wordt overgeslagen.", kolom)
    categorisch = [k for k in CATEGORISCH if k in df.columns]
    return df, numeriek, categorisch


def _tel_klanten(sleutels, y):
    return pd.Series(y).groupby(np.asarray(sleutels, dtype=object)).sum()


def regio_train(frame, y, cfg):
    """Buurteffect voor trainingsrijen: elk adres krijgt de klanten uit de ándere stukken van
    de trainingsdata, zodat het zichzelf nooit meetelt. Vermenigvuldigd met k/(k-1) zodat de
    schaal gelijk is aan `regio_score`. Gedempt met log1p."""
    y = np.asarray(y)
    resultaat = {naam: np.zeros(len(frame)) for _, naam in REGIO_KOLOMMEN}
    ophoging = cfg.binnen_folds / (cfg.binnen_folds - 1)
    binnen = KFold(n_splits=cfg.binnen_folds, shuffle=True, random_state=cfg.random_state)
    for tel, doel in binnen.split(frame):
        for kolom, naam in REGIO_KOLOMMEN:
            telling = _tel_klanten(frame[kolom].to_numpy()[tel], y[tel])
            gevonden = frame[kolom].iloc[doel].map(telling).fillna(0).to_numpy(dtype=float)
            resultaat[naam][doel] = gevonden * ophoging
    return {naam: np.log1p(w) for naam, w in resultaat.items()}


def regio_score(train_frame, y_train, nieuw_frame):
    """Buurteffect voor adressen die beoordeeld worden: alle klanten uit de trainingsdata."""
    resultaat = {}
    for kolom, naam in REGIO_KOLOMMEN:
        telling = _tel_klanten(train_frame[kolom].to_numpy(), np.asarray(y_train))
        resultaat[naam] = np.log1p(nieuw_frame[kolom].map(telling).fillna(0).to_numpy(dtype=float))
    return resultaat


def met_regio(data, y, train_pos, test_pos, cfg):
    """Kopie van `data` met het buurteffect: regel 1 voor de train-, regel 2 voor de testrijen."""
    uit = data.copy()
    train, test = data.iloc[train_pos], data.iloc[test_pos]
    y_train = np.asarray(y)[train_pos]
    deel_train = regio_train(train, y_train, cfg)
    deel_test = regio_score(train, y_train, test)
    for _, naam in REGIO_KOLOMMEN:
        kolom = uit.columns.get_loc(naam)
        uit.iloc[train_pos, kolom] = deel_train[naam]
        uit.iloc[test_pos, kolom] = deel_test[naam]
    return uit


def klanten_in_de_buurt(data, y):
    """Ongedempte aantallen voor in de leadlijst (alle bekende klanten)."""
    return {
        kolom: data[kolom].map(_tel_klanten(data[kolom].to_numpy(), np.asarray(y)))
        .fillna(0).astype(int).to_numpy()
        for kolom, _ in REGIO_KOLOMMEN
    }
