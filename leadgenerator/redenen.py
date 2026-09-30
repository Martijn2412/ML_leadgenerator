"""Per adres in gewone taal: waarom scoort dit adres hoog?

De redenen komen uit het logistic-regression-deel van het ensemble. Daar is de bijdrage
van elk kenmerk simpelweg gewicht × (geschaalde) waarde, dus direct uitlegbaar en snel,
ook voor honderdduizenden adressen. De RandomForest weegt mee in de score, maar geeft
zonder extra pakketten geen uitleg per adres.
"""

import numpy as np
import pandas as pd

# Kenmerken die technisch nuttig zijn maar geen reden om iemand te benaderen.
OVERSLAAN = {"buurt_frequentie"}

# Kenmerken die hetzelfde zeggen: per groep maximaal één reden.
GROEP = {
    "pandbouwjaar": "bouwjaar",
    "voor_spouwmuurnorm_1975": "bouwjaar",
    "voor_hrpp_norm_1995": "bouwjaar",
    "vbo_oppervlakte": "oppervlakte",
    "pandoppervlakte": "oppervlakte",
}

MIN_BIJDRAGE = 0.05  # kleinere bijdragen zijn geen echte reden


def _getal(waarde, decimalen=0):
    """1234567.8 -> '1.234.568' (Nederlandse notatie)."""
    tekst = f"{waarde:,.{decimalen}f}"
    return tekst.replace(",", "_").replace(".", ",").replace("_", ".")


def _bouwjaar(v):
    jaar = int(v)
    if jaar < 1975:
        return f"Bouwjaar {jaar} (vóór 1975: vaak nog geen spouwmuurisolatie)"
    if jaar < 1995:
        return f"Bouwjaar {jaar} (vóór 1995: vaak nog geen HR++-glas)"
    return f"Bouwjaar {jaar}"


def _label(v):
    """Terug van rang naar label: 5 -> 'E', 0,6 -> 'A++' (zie kenmerken.energielabel_rang)."""
    index = int(np.clip(np.ceil(v - 1e-9), 1, 7))
    plussen = int(round((index - v) / 0.2))
    return f"Energielabel {'ABCDEFG'[index - 1]}{'+' * plussen}"


def _vlag(tekst):
    return lambda v: tekst if v == 1 else None


def _aantal(tekst):
    def maak(v):
        n = int(round(np.expm1(v)))
        return tekst.format(n=n, s="" if n == 1 else "en") if n > 0 else None
    return maak


ZINNEN = {
    "pandbouwjaar": _bouwjaar,
    "voor_spouwmuurnorm_1975": _vlag("Gebouwd vóór 1975 (vaak nog geen spouwmuurisolatie)"),
    "voor_hrpp_norm_1995": _vlag("Gebouwd vóór 1995 (vaak nog geen HR++-glas)"),
    "energieklasse_rang": _label,
    "buurt_klanten_nabij": _aantal("{n} klant{s} in dezelfde buurt"),
    "postcode4_klanten_nabij": _aantal("{n} klant{s} in hetzelfde postcodegebied"),
    "gasverbruik": lambda v: f"Hoog gasverbruik in de buurt ({_getal(v)} m³/jaar)",
    "gemiddeld_inkomen": lambda v: "Relatief hoog inkomen in de buurt",
    "woz": lambda v: f"WOZ-waarde € {_getal(v)}",
    "vbo_oppervlakte": lambda v: f"Woonoppervlakte {_getal(v)} m²",
    "pandoppervlakte": lambda v: f"Pand van {_getal(v)} m²",
    "koop": lambda v: "Veel koopwoningen in de buurt",
    "woningen_in_pand": _vlag("Grondgebonden woning (eigen pand)"),
}


def bijdragen(ensemble, X):
    """Bijdrage van elk numeriek kenmerk aan de score volgens de logistic regression."""
    prep = ensemble.log_model.named_steps["prep"]
    clf = ensemble.log_model.named_steps["clf"]
    geschaald = prep.transform(X[ensemble.kenmerken])[:, : len(ensemble.numeriek)]
    return geschaald * clf.coef_[0, : len(ensemble.numeriek)]


def bereken_redenen(ensemble, X, aantal=3):
    """Lijst met per adres een tekst als 'Bouwjaar 1962 (...) · Energielabel F · 4 klanten in ...'."""
    namen = ensemble.numeriek
    bruikbaar = np.array([n in ZINNEN and n not in OVERSLAAN for n in namen])
    b = bijdragen(ensemble, X)
    b = np.where(bruikbaar & (b > MIN_BIJDRAGE), b, -np.inf)
    ruw = X[namen].to_numpy(dtype=float)
    volgorde = np.argsort(-b, axis=1)
    # Bij de bouwjaar-vlaggen liever het echte bouwjaar tonen, dat zegt de binnendienst meer.
    j_bouwjaar = namen.index("pandbouwjaar") if "pandbouwjaar" in namen else None

    uit = []
    for i in range(len(X)):
        zinnen, groepen = [], set()
        for j in volgorde[i]:
            if not np.isfinite(b[i, j]) or len(zinnen) == aantal:
                break
            naam, waarde = namen[j], ruw[i, j]
            groep = GROEP.get(naam, naam)
            if groep in groepen or np.isnan(waarde):
                continue
            if groep == "bouwjaar" and j_bouwjaar is not None and not np.isnan(ruw[i, j_bouwjaar]):
                naam, waarde = "pandbouwjaar", ruw[i, j_bouwjaar]
            zin = ZINNEN[naam](waarde)
            if zin:
                zinnen.append(zin)
                groepen.add(groep)
        uit.append(" · ".join(zinnen))
    return pd.Series(uit, index=X.index)
