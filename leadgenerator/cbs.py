"""CBS-buurtcijfers (gasverbruik, inkomen) ophalen, cachen en aan adressen koppelen.

De cijfers zijn openbaar en landelijk, dus ze worden één keer opgehaald en als CSV in
data/cbs/ bewaard. Zo hangt een run niet af van de bereikbaarheid van de CBS-website.
"""

import logging

import numpy as np
import pandas as pd
import requests

from .config import CBS_CACHE_MAP

log = logging.getLogger(__name__)

CBS_URL = "https://datasets.cbs.nl/odata/v1/CBS/{tabel}"


def cbs_odata_ophalen(url, params=None):
    """Haalt alle pagina's van een CBS OData v4-endpoint op."""
    rijen = []
    while url:
        respons = requests.get(url, params=params, timeout=60)
        respons.raise_for_status()
        pagina = respons.json()
        rijen.extend(pagina["value"])
        url = pagina.get("@odata.nextLink")
        params = None
    return pd.DataFrame(rijen)


def haal_cbs_kenmerk(tabel, measure, filters=None):
    """Eén meting uit een CBS-tabel als tabel met code, waarde, naam en gemeentenaam."""
    basis = CBS_URL.format(tabel=tabel)
    filter_tekst = " and ".join(
        [f"Measure eq '{measure}'"] + [f"{k} eq '{v}'" for k, v in (filters or {}).items()]
    )
    obs = cbs_odata_ophalen(f"{basis}/Observations", params={"$filter": filter_tekst})
    if obs.empty or "WijkenEnBuurten" not in obs.columns:
        raise RuntimeError(f"Geen waarnemingen ontvangen uit CBS-tabel {tabel}.")

    codes = cbs_odata_ophalen(f"{basis}/WijkenEnBuurtenCodes")
    codes = codes[["Identifier", "Title", "DimensionGroupId"]].rename(columns={"Identifier": "code"})
    naam_per_code = codes.set_index("code")["Title"]

    tabel_df = (
        obs[["WijkenEnBuurten", "Value"]]
        .rename(columns={"WijkenEnBuurten": "code", "Value": "waarde"})
        .merge(codes, on="code", how="left")
    )
    tabel_df["code"] = tabel_df["code"].str.strip()
    gemeente_code = tabel_df["code"].where(tabel_df["code"].str.startswith("GM"),
                                           tabel_df["DimensionGroupId"])
    tabel_df["naam"] = tabel_df["Title"]
    tabel_df["gemeentenaam"] = gemeente_code.map(naam_per_code)
    tabel_df = tabel_df[tabel_df["code"].str.match(r"^(BU|GM)")]
    return tabel_df[["code", "waarde", "naam", "gemeentenaam"]].dropna(subset=["waarde"])


def cache_pad(naam):
    return CBS_CACHE_MAP / f"{naam}.csv"


def laad_cbs_kenmerk(naam, spec, offline=False, vernieuwen=False):
    """Geeft de CBS-tabel voor een kenmerk: uit de cache, of opgehaald en daarna gecachet.
    Geeft None als het niet lukt (de run gaat dan door zonder dit kenmerk)."""
    pad = cache_pad(naam)
    if pad.exists() and not vernieuwen:
        return pd.read_csv(pad, dtype={"code": str})
    if offline:
        log.warning("Geen CBS-cache voor '%s' (%s) en offline: kenmerk wordt overgeslagen.", naam, pad)
        return None
    try:
        log.info("CBS-tabel %s ophalen voor '%s' ...", spec["tabel"], naam)
        df = haal_cbs_kenmerk(spec["tabel"], spec["measure"], spec.get("filters"))
    except Exception as fout:  # netwerk, proxy, API-wijziging: nooit de hele run laten stoppen
        log.warning("CBS-kenmerk '%s' kon niet worden opgehaald: %s", naam, fout)
        return None
    pad.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(pad, index=False)
    return df


def normaliseer_naam(serie):
    schoon = serie.astype("string").str.strip().str.lower()
    schoon = schoon.str.replace(r"\s*\([^)]*\)\s*$", "", regex=True)
    return schoon.str.replace(r"\s+", " ", regex=True)


def _buurtcode(serie):
    """Assetmaps-buurtcode naar CBS-formaat 'BU01234567'."""
    tekst = serie.astype("string").str.strip().str.upper().str.replace(r"\.0$", "", regex=True)
    cijfers = tekst.str.replace(r"^BU", "", regex=True)
    return ("BU" + cijfers.str.zfill(8)).where(cijfers.str.fullmatch(r"\d+"))


def koppel_cbs_kenmerk(assetmaps, naam, cbs_df):
    """Zet het CBS-kenmerk als kolom `naam` bij elk adres: eerst op buurtcode (als Assetmaps die
    heeft), dan op gemeente + buurtnaam, en anders het gemeentegemiddelde.
    Geeft (assetmaps, statistiek) terug."""
    stat = {"kenmerk": naam, "buurt": 0, "gemeente": 0, "totaal": len(assetmaps)}
    if cbs_df is None or cbs_df.empty:
        assetmaps[naam] = np.nan
        return assetmaps, stat

    buurten = cbs_df[cbs_df["code"].str.startswith("BU")].drop_duplicates("code")
    gemeenten = cbs_df[cbs_df["code"].str.startswith("GM")].copy()
    waarde = pd.Series(np.nan, index=assetmaps.index)

    if "buurtcode" in assetmaps.columns:
        waarde = _buurtcode(assetmaps["buurtcode"]).map(buurten.set_index("code")["waarde"])

    sleutel_cbs = normaliseer_naam(buurten["gemeentenaam"]) + "|" + normaliseer_naam(buurten["naam"])
    per_naam = pd.Series(buurten["waarde"].to_numpy(), index=sleutel_cbs.to_numpy())
    per_naam = per_naam[~per_naam.index.duplicated()]
    sleutel = normaliseer_naam(assetmaps["gemeente"]) + "|" + normaliseer_naam(assetmaps["buurtnaam"])
    waarde = waarde.fillna(sleutel.map(per_naam).astype(float))
    stat["buurt"] = int(waarde.notna().sum())

    gemeenten["_g"] = normaliseer_naam(gemeenten["naam"])
    per_gemeente = gemeenten.drop_duplicates("_g").set_index("_g")["waarde"]
    waarde = waarde.fillna(normaliseer_naam(assetmaps["gemeente"]).map(per_gemeente).astype(float))
    stat["gemeente"] = int(waarde.notna().sum()) - stat["buurt"]

    assetmaps[naam] = waarde.astype(float).to_numpy()
    return assetmaps, stat


def voeg_cbs_toe(assetmaps, cfg, vernieuwen=False):
    """Voegt alle CBS-kenmerken uit de config toe. Geeft (assetmaps, statistieken, waarschuwingen)."""
    statistieken, waarschuwingen = [], []
    for naam, spec in cfg.cbs.items():
        cbs_df = laad_cbs_kenmerk(naam, spec, offline=cfg.cbs_offline, vernieuwen=vernieuwen)
        assetmaps, stat = koppel_cbs_kenmerk(assetmaps, naam, cbs_df)
        statistieken.append(stat)
        gevonden = (stat["buurt"] + stat["gemeente"]) / max(stat["totaal"], 1)
        if cbs_df is None:
            waarschuwingen.append(f"CBS-kenmerk '{naam}' niet beschikbaar; model draait zonder.")
        elif gevonden < 0.9:
            waarschuwingen.append(
                f"CBS-kenmerk '{naam}' maar voor {gevonden:.0%} van de adressen gevonden. "
                "Controleer de buurt- en gemeentenamen."
            )
    return assetmaps, statistieken, waarschuwingen
