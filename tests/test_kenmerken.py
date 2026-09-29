import numpy as np
import pandas as pd

from leadgenerator.kenmerken import (
    energielabel_rang,
    koppel,
    maak_kenmerken,
    postcode4,
    regio_score,
    regio_train,
    vervang_missing_code,
)


def _adressen(**kolommen):
    n = len(next(iter(kolommen.values())))
    basis = {
        "vbo_id": [f"06540100000000{i:02d}" for i in range(n)],
        "pand_id": [f"06541000000000{i:02d}" for i in range(n)],
        "gemeente": ["Middelburg"] * n, "buurtnaam": ["Centrum"] * n, "postcode": ["4331 AB"] * n,
    }
    basis.update(kolommen)
    return pd.DataFrame(basis)


def test_missing_code_in_alle_getalkolommen():
    df = pd.DataFrame({"woz": [-99997, 1.0], "pandbouwjaar": [-99997, 1970], "tekst": ["a", "b"]})
    uit = vervang_missing_code(df, -99997)
    assert uit["woz"].isna().sum() == 1 and uit["pandbouwjaar"].isna().sum() == 1


def test_energielabel_met_plussen():
    uit = energielabel_rang(pd.Series(["A++", "A", "g", "onbekend", None]))
    assert uit[0] < uit[1] == 1 and uit[2] == 7
    assert uit[3:].isna().all()


def test_postcode4():
    assert list(postcode4(pd.Series(["4331 AB", "4331ab", None, "abcd"]))[:2]) == ["4331", "4331"]


def test_gelijke_buurtnaam_in_andere_gemeente_is_andere_buurt(cfg):
    df = _adressen(gemeente=["Middelburg", "Middelburg", "Vlissingen", "Vlissingen"],
                   buurtnaam=["Centrum"] * 4, postcode=["4331 AB", "4331 AB", "4381 AB", "4381 AB"])
    df, _, _ = maak_kenmerken(df, cfg)
    assert df["buurt_sleutel"].nunique() == 2
    assert list(df["buurt_frequentie"]) == [2, 2, 2, 2]


def test_buurteffect_telt_adres_zelf_niet_mee(cfg):
    # Eén klant alleen in zijn buurt: hij mag zichzelf niet als "klant in de buurt" zien.
    frame = pd.DataFrame({"buurt_sleutel": ["a"] + ["b"] * 9, "postcode4": [str(i) for i in range(10)]})
    y = np.array([1] + [0] * 9)
    assert regio_train(frame, y, cfg)["buurt_klanten_nabij"][0] == 0
    nieuw = pd.DataFrame({"buurt_sleutel": ["a"], "postcode4": ["x"]})
    assert regio_score(frame, y, nieuw)["buurt_klanten_nabij"][0] == np.log1p(1)


def test_pand_order_telt_niet_voor_appartementen():
    assetmaps = pd.DataFrame({
        "vbo_id": ["v1", "v2", "v3", "v4"],
        "pand_id": ["flat", "flat", "flat", "huis"],
    })
    per_vbo = pd.DataFrame({"vbo_id": ["v1"], "heeft_order_status": [True],
                            "klant_jaar_vbo": [2020.0], "aantal_tios_regels": [1]})
    per_pand = pd.DataFrame({"pand_id": ["flat", "huis"], "heeft_order_status_pand": [True, True],
                             "klant_jaar_pand": [2020.0, 2021.0]})
    uit = koppel(assetmaps, per_vbo, per_pand).set_index("vbo_id")
    assert uit.loc["v1", "is_klant"] == 1          # zelf een order
    assert uit.loc["v2", "is_klant"] == 0          # buurman in de flat: geen klant
    assert uit.loc["v4", "is_klant"] == 1          # grondgebonden: pand-order telt
    assert uit.loc["v4", "klant_jaar"] == 2021
