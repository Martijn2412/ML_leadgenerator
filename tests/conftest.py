"""Kleine synthetische TIOS- en Assetmaps-bestanden met de valkuilen van de echte data:
voorloopnullen in BAG-ID's, gelijke buurtnamen in verschillende gemeenten, -99997,
A++-labels en appartementencomplexen."""

import numpy as np
import pandas as pd
import pytest

from leadgenerator.config import Config

GEMEENTEN = {"0654": "Middelburg", "0718": "Vlissingen", "0677": "Hulst"}


def _bag(gemeentecode, objecttype, nummer):
    return f"{gemeentecode}{objecttype}{nummer:010d}"


def maak_assetmaps(n=1500, seed=0):
    rng = np.random.default_rng(seed)
    rijen = []
    pand_nr = 0
    i = 0
    while i < n:
        code = rng.choice(list(GEMEENTEN))
        gemeente = GEMEENTEN[code]
        buurt = rng.choice(["Centrum", "Noord", "Zuid"])  # zelfde namen in elke gemeente
        woningen = 12 if rng.random() < 0.05 else 1        # soms een appartementencomplex
        bouwjaar = int(rng.integers(1930, 2020))
        pand_nr += 1
        for _ in range(woningen):
            i += 1
            rijen.append({
                "BAG-ID (vbo_id)": _bag(code, "01", i),
                "Pand-ID (pand_id)": _bag(code, "10", pand_nr),
                "Straat (straatnaam)": "Teststraat",
                "Nr (huisnummer)": str(i),
                "Postcode (postcode)": f"{4300 + int(code) % 50 + int(rng.integers(0, 4))} AB",
                "Plaats (woonplaats)": gemeente,
                "Gemeente (gemeente)": gemeente,
                "Buurt (buurtnaam)": buurt,
                "Provincie (provincie)": "Zeeland",
                "Bouwjaar (pandbouwjaar)": bouwjaar,
                "Opp (vbo_oppervlakte)": float(rng.integers(50, 200)),
                "Pand opp (pandoppervlakte)": float(rng.integers(50, 400)),
                "WOZ (woz)": -99997 if rng.random() < 0.05 else float(rng.integers(150, 600)) * 1000,
                "Koop (koop)": float(rng.integers(20, 90)),
                "Huur (huur)": float(rng.integers(10, 80)),
                "Label (energieklasse)": rng.choice(["A++", "A", "B", "C", "D", "E", "F", "G", None]),
                "Klant (klant)": "nee",
            })
    return pd.DataFrame(rijen[:n])


def maak_tios(assetmaps, seed=1):
    """Klanten: vooral oude woningen in Middelburg-Centrum, plus wat ruis en offertes zonder order."""
    rng = np.random.default_rng(seed)
    rijen = []
    for _, r in assetmaps.iterrows():
        oud = r["Bouwjaar (pandbouwjaar)"] < 1975
        hotspot = r["Gemeente (gemeente)"] == "Middelburg" and r["Buurt (buurtnaam)"] == "Centrum"
        p = 0.02 + 0.10 * oud + 0.10 * hotspot
        if rng.random() < p:
            status = "Opdracht" if rng.random() < 0.8 else "Offerte verstuurd"
            rijen.append({
                "Aanmaakdatum (datum)": pd.Timestamp(int(rng.integers(2016, 2024)), 6, 1),
                "Status (status)": status,
                "BAG-ID (vbo_id)": int(r["BAG-ID (vbo_id)"]),  # als getal: voorloopnul weg!
                "Pand-ID (pand_id)": int(r["Pand-ID (pand_id)"]),
                "ID (id)": len(rijen) + 1,
            })
    return pd.DataFrame(rijen)


@pytest.fixture
def cfg():
    return Config(
        cbs={}, cbs_offline=True, rf_bomen=30, binnen_folds=3, scoring_folds=3, cv_folds=3,
        groep_folds=3, k_waarden=[10, 50], permutatie_steekproef=500, backtest_jaren=2,
        excel_max_adressen=100,
    )


@pytest.fixture
def bestanden(tmp_path):
    assetmaps = maak_assetmaps()
    tios = maak_tios(assetmaps)
    a_pad, t_pad = tmp_path / "Woningen_test.xlsx", tmp_path / "TIOS.xlsx"
    assetmaps.to_excel(a_pad, sheet_name="Blad1", index=False)
    tios.to_excel(t_pad, sheet_name="WoningBron", index=False)
    return t_pad, a_pad
