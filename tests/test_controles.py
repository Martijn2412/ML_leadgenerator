import numpy as np
import pandas as pd
import pytest

from cli import main
from leadgenerator.config import Config
from leadgenerator.controles import label_controle, tabel_als_tekst
from leadgenerator.kenmerken import maak_kenmerken


def _woningen(label_klant, label_niet_klant, n=400, seed=0):
    rng = np.random.default_rng(seed)
    klant = rng.random(n) < 0.3
    return pd.DataFrame({
        "pandbouwjaar": rng.integers(1930, 1975, n).astype(float),
        "is_klant": klant.astype(int),
        "energielabel_rang_ruw": np.where(klant, label_klant, label_niet_klant).astype(float),
    })


def test_lek_wordt_gemeld_als_klanten_een_beter_label_hebben():
    controle = label_controle(_woningen(label_klant=2, label_niet_klant=6))  # klant B, rest F
    assert controle["lek"]
    assert controle["verschil_oud"] == pytest.approx(4)
    assert "Vermoedelijk label-lek" in controle["tekst"]
    assert "| alle woningen |" in tabel_als_tekst(controle)


def test_geen_lek_als_klanten_een_slechter_label_hebben():
    controle = label_controle(_woningen(label_klant=6, label_niet_klant=5))
    assert not controle["lek"]
    assert controle["tekst"].startswith("Geen label-lek")


def test_geen_labels_geeft_geen_controle():
    df = _woningen(2, 6)
    df["energielabel_rang_ruw"] = np.nan
    assert label_controle(df) is None


def _gekoppeld():
    """Minimale gekoppelde tabel zoals maak_kenmerken die verwacht."""
    n = 60
    rng = np.random.default_rng(1)
    klant = np.arange(n) < 20
    return pd.DataFrame({
        "vbo_id": [f"065401{i:010d}" for i in range(n)],
        "gemeente": "Middelburg", "buurtnaam": "Centrum", "postcode": "4331 AB",
        "pandbouwjaar": rng.integers(1930, 1970, n).astype(float),
        "energieklasse": np.where(klant, "B", "F"),
        "is_klant": klant.astype(int),
        "klant_jaar": np.where(klant, 2020.0, np.nan),
        # klanten 0-9: label ná de order (2022), klanten 10-19: vóór de order (2015)
        "label_datum": np.where(np.arange(n) < 10, "01-06-2022", "01-06-2015"),
    })


def test_negeren_vervangt_alleen_labels_van_na_de_order():
    cfg = Config(energielabel_bij_klanten="negeren", energielabel_datum_kolom="label_datum",
                 missing_indicator_drempel=0.0)
    df, numeriek, _ = maak_kenmerken(_gekoppeld(), cfg)
    assert (df.loc[:9, "energieklasse_rang"] == 6).all()      # vervangen door label van niet-klanten (F)
    assert (df.loc[10:19, "energieklasse_rang"] == 2).all()   # vóór de order: echte label (B) blijft
    assert (df.loc[20:, "energieklasse_rang"] == 6).all()     # niet-klanten ongewijzigd
    assert (df.loc[:9, "energielabel_rang_ruw"] == 2).all()   # ruwe label blijft bewaard
    assert "energieklasse_rang" in numeriek
    assert "energieklasse_rang_ontbreekt" not in numeriek


def test_negeren_zonder_datumkolom_geeft_duidelijke_fout():
    with pytest.raises(ValueError, match="weglaten"):
        maak_kenmerken(_gekoppeld(), Config(energielabel_bij_klanten="negeren"))


def test_weglaten_haalt_het_label_uit_de_kenmerken():
    _, numeriek, _ = maak_kenmerken(_gekoppeld(), Config(energielabel_bij_klanten="weglaten",
                                                         missing_indicator_drempel=0.0))
    assert not any(k.startswith("energieklasse_rang") for k in numeriek)


def test_cli_controle(bestanden, capsys):
    tios_pad, assetmaps_pad = bestanden
    code = main(["controle", "--map", str(tios_pad.parent), "--tios", tios_pad.name,
                 "--assetmaps", assetmaps_pad.name])
    assert code == 0
    uit = capsys.readouterr().out
    assert "| bouwjaar |" in uit and "label" in uit.lower()
