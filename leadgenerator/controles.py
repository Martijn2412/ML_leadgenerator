"""Controles op de data die niets met het model zelf te maken hebben.

Label-lek: het energielabel in Assetmaps is het huidige label. Bij klanten is dat vaak gemeten ná
de isolatie door Takkenkamp. Dan lijken klanten betere labels te hebben dan ze vóór de order hadden,
en leert het model een vertekend effect van het label. Omdat klanten vaker in oude huizen wonen
(en oude huizen slechtere labels hebben), vergelijken we binnen bouwjaarklassen.
"""

import numpy as np
import pandas as pd

BOUWJAARKLASSEN = [
    ("vóór 1945", -np.inf, 1945),
    ("1945-1974", 1945, 1975),
    ("1975-1994", 1975, 1995),
    ("1995 en later", 1995, np.inf),
]
OUDE_KLASSEN = ["vóór 1945", "1945-1974"]  # hier is het effect van isolatie op het label het grootst


def bouwjaarklasse(bouwjaar):
    klasse = pd.Series(pd.NA, index=bouwjaar.index, dtype="object")
    for naam, van, tot in BOUWJAARKLASSEN:
        klasse[(bouwjaar >= van) & (bouwjaar < tot)] = naam
    return klasse


def _groep(rang, klant):
    k, n = rang[klant], rang[~klant]
    return {
        "klanten": int(klant.sum()), "niet_klanten": int((~klant).sum()),
        "label_klant": k.mean(), "label_niet_klant": n.mean(),
        # positief = klanten hebben een béter (lager) label dan niet-klanten
        "verschil": n.mean() - k.mean(),
        "ab_klant": (k <= 2).sum() / max(k.notna().sum(), 1),
        "ab_niet_klant": (n <= 2).sum() / max(n.notna().sum(), 1),
        "zonder_label_klant": k.isna().mean() if len(k) else np.nan,
        "zonder_label_niet_klant": n.isna().mean() if len(n) else np.nan,
    }


def label_controle(data, drempel=0.5):
    """Vergelijkt de energielabels van klanten en niet-klanten, per bouwjaarklasse.
    Verwacht de kolommen `energielabel_rang_ruw` (A=1 … G=7), `pandbouwjaar` en `is_klant`.
    Geeft None als er geen labels zijn, anders een dict met 'tabel', 'verschil_oud', 'lek' en 'tekst'."""
    if "energielabel_rang_ruw" not in data or data["energielabel_rang_ruw"].notna().sum() == 0:
        return None
    rang = data["energielabel_rang_ruw"].astype(float)
    klant = data["is_klant"].to_numpy() == 1
    klasse = bouwjaarklasse(data.get("pandbouwjaar", pd.Series(np.nan, index=data.index)))

    rijen = {"alle woningen": _groep(rang, klant)}
    for naam, _, _ in BOUWJAARKLASSEN:
        binnen = (klasse == naam).to_numpy()
        if (binnen & klant).sum() >= 5 and (binnen & ~klant).sum() >= 5:
            rijen[naam] = _groep(rang[binnen], klant[binnen])
    tabel = pd.DataFrame(rijen).T

    oud = tabel.loc[tabel.index.isin(OUDE_KLASSEN)]
    if oud.empty:
        verschil_oud = np.nan
    else:
        verschil_oud = float(np.average(oud["verschil"].astype(float), weights=oud["klanten"].astype(float)))
    lek = bool(np.isfinite(verschil_oud) and verschil_oud >= drempel)

    stappen = f"{abs(verschil_oud):.1f}".replace(".", ",") if np.isfinite(verschil_oud) else "?"
    if lek:
        tekst = (f"Vermoedelijk label-lek: in huizen van vóór 1975 hebben klanten gemiddeld {stappen} "
                 "labelstap béter dan niet-klanten. Waarschijnlijk is hun label gemeten ná de isolatie. "
                 "Overweeg energielabel 'weglaten' (of 'negeren' met een labeldatum) en vergelijk met "
                 "de tijdsbacktest.")
    elif np.isfinite(verschil_oud) and abs(verschil_oud) < 0.1:
        tekst = ("Geen label-lek: in huizen van vóór 1975 is er nauwelijks verschil tussen de labels van "
                 "klanten en niet-klanten.")
    elif np.isfinite(verschil_oud) and verschil_oud > 0:
        tekst = (f"Geen duidelijk label-lek: in huizen van vóór 1975 hebben klanten gemiddeld {stappen} "
                 "labelstap beter dan niet-klanten, onder de drempel.")
    elif np.isfinite(verschil_oud):
        tekst = (f"Geen label-lek: in huizen van vóór 1975 hebben klanten gemiddeld {stappen} labelstap "
                 "slechter dan niet-klanten, zoals je verwacht vóór isolatie.")
    else:
        tekst = "Label-controle niet mogelijk: te weinig klanten met een bekend bouwjaar van vóór 1975."
    return {"tabel": tabel, "verschil_oud": verschil_oud, "lek": lek, "tekst": tekst}


def tabel_als_tekst(controle):
    """Leesbare tabel voor terminal en rapport (markdown)."""
    t = controle["tabel"]
    regels = [
        "| bouwjaar | klanten | label klant | label niet-klant | verschil | A/B klant | A/B niet-klant |",
        "|---|---|---|---|---|---|---|",
    ]
    for naam, r in t.iterrows():
        regels.append(
            f"| {naam} | {int(r['klanten'])} | {r['label_klant']:.2f} | {r['label_niet_klant']:.2f} | "
            f"{r['verschil']:+.2f} | {r['ab_klant']:.0%} | {r['ab_niet_klant']:.0%} |"
        )
    uitleg = ("Label: A=1 … G=7 (lager is beter). Verschil > 0 betekent dat klanten een béter label "
              "hebben dan niet-klanten.")
    return "\n".join(regels) + "\n\n" + uitleg + "\n"
