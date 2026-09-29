import numpy as np
import pandas as pd

from leadgenerator.config import Config
from leadgenerator.model import Ensemble
from leadgenerator.redenen import ZINNEN, bereken_redenen


def test_zinnen():
    assert ZINNEN["pandbouwjaar"](1962.0).startswith("Bouwjaar 1962 (vóór 1975")
    assert ZINNEN["energieklasse_rang"](5.0) == "Energielabel E"
    assert ZINNEN["energieklasse_rang"](0.6) == "Energielabel A++"
    assert ZINNEN["buurt_klanten_nabij"](np.log1p(1)) == "1 klant in dezelfde buurt"
    assert ZINNEN["buurt_klanten_nabij"](np.log1p(12)) == "12 klanten in dezelfde buurt"
    assert ZINNEN["woz"](345000.0) == "WOZ-waarde € 345.000"
    assert ZINNEN["woningen_in_pand"](3.0) is None


def test_redenen_volgen_het_model():
    # Oude woningen worden klant: bij een oud huis moet het bouwjaar de reden zijn.
    rng = np.random.default_rng(0)
    n = 2000
    X = pd.DataFrame({
        "pandbouwjaar": rng.integers(1930, 2020, n).astype(float),
        "woz": rng.integers(150, 600, n) * 1000.0,
        "buurt_frequentie": rng.integers(10, 500, n).astype(float),
        "gemeente": rng.choice(["Hulst", "Veere"], n),
    })
    y = (rng.random(n) < np.where(X["pandbouwjaar"] < 1975, 0.3, 0.02)).astype(int)
    model = Ensemble(["pandbouwjaar", "woz", "buurt_frequentie"], ["gemeente"], Config(rf_bomen=10))
    model.fit(X, y)

    oud = X.iloc[[int(np.argmin(X["pandbouwjaar"]))]]
    nieuw = X.iloc[[int(np.argmax(X["pandbouwjaar"]))]]
    assert bereken_redenen(model, oud).iloc[0].startswith("Bouwjaar")
    assert "Bouwjaar" not in bereken_redenen(model, nieuw).iloc[0]
    assert "buurt_frequentie" not in " ".join(bereken_redenen(model, X))
