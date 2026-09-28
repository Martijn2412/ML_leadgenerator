"""Leadlijst naar Excel en CSV, en het modelrapport."""

import re

import numpy as np
import pandas as pd

LEADLIJST_KOLOMMEN = {
    "straatnaam": "straat",
    "huisnummer": "huisnummer",
    "huisletter": "huisletter",
    "toevoeging": "toevoeging",
    "postcode": "postcode",
    "woonplaats": "woonplaats",
    "gemeente": "gemeente",
    "buurtnaam": "buurt",
    "pandbouwjaar": "bouwjaar",
    "energieklasse": "energielabel",
    "klasse": "klasse",
    "score": "score",
    "eerder_contact": "eerder_contact",
    "klanten_in_buurt": "klanten_in_buurt",
    "klanten_in_postcode4": "klanten_in_postcode4",
}

UITLEG = [
    ("klasse", "A = top 10% kansrijkste adressen, B = volgende 20%, C = de rest."),
    ("score", "0-100: hoeveel procent van de adressen lager scoort. Kijk naar de volgorde, "
              "niet naar het getal als 'kans'."),
    ("eerder_contact", "ja = dit adres staat al in TIOS (bijv. offerte) maar werd geen klant."),
    ("klanten_in_buurt", "Aantal bestaande klanten in dezelfde buurt."),
    ("klanten_in_postcode4", "Aantal bestaande klanten in hetzelfde postcodegebied (4 cijfers)."),
    ("Top", "De kansrijkste adressen van de hele lijst."),
    ("Witte vlekken", "Kansrijke adressen in postcodegebieden zonder bestaande klant: "
                      "voor nieuwe gebieden."),
    ("Per gemeente", "Elk gemeente-tabblad bevat de kansrijkste adressen van die gemeente."),
    ("Volledige lijst", "Alle adressen staan in leadlijst_volledig.csv (Excel heeft een "
                        "maximum van ~1 miljoen rijen)."),
]


def voeg_score_toe(leads, kans, cfg):
    """Score (percentiel 0-100) en klasse A/B/C op basis van de volgorde."""
    leads = leads.copy()
    leads["kans_model"] = kans
    percentiel = pd.Series(kans, index=leads.index).rank(pct=True, method="average")
    leads["score"] = (percentiel * 100).round(1)
    grens_a = 1 - cfg.klasse_a_aandeel
    grens_b = grens_a - cfg.klasse_b_aandeel
    leads["klasse"] = np.select([percentiel > grens_a, percentiel > grens_b], ["A", "B"], "C")
    return leads.sort_values("kans_model", ascending=False)


def maak_leadlijst(leads):
    kolommen = [k for k in LEADLIJST_KOLOMMEN if k in leads.columns]
    uit = leads[kolommen].rename(columns=LEADLIJST_KOLOMMEN)
    uit["eerder_contact"] = np.where(uit["eerder_contact"] == 1, "ja", "")
    return uit


def _bladnaam(naam, gebruikt):
    schoon = re.sub(r"[\[\]:*?/\\]", "", str(naam))[:31] or "onbekend"
    basis, i = schoon, 2
    while schoon.lower() in gebruikt:
        schoon = f"{basis[:28]}_{i}"
        i += 1
    gebruikt.add(schoon.lower())
    return schoon


def _schrijf_blad(writer, df, naam):
    df.to_excel(writer, sheet_name=naam, index=False)
    blad = writer.sheets[naam]
    blad.freeze_panes = "A2"
    if len(df):
        blad.auto_filter.ref = blad.dimensions
    for i, kolom in enumerate(df.columns, start=1):
        breedte = max(len(str(kolom)), *(len(str(v)) for v in df[kolom].head(200))) if len(df) else 10
        blad.column_dimensions[blad.cell(1, i).column_letter].width = min(breedte + 2, 40)


def schrijf_excel(pad, leadlijst, max_adressen):
    """Tabbladen: Uitleg, Top, Witte vlekken, en één per gemeente (elk max. `max_adressen`)."""
    gebruikt = {"uitleg", "top", "witte vlekken"}
    geen_klant_dichtbij = (leadlijst["klanten_in_buurt"] == 0) & (leadlijst["klanten_in_postcode4"] == 0)
    witte_vlekken = leadlijst[geen_klant_dichtbij]
    with pd.ExcelWriter(pad, engine="openpyxl") as writer:
        _schrijf_blad(writer, pd.DataFrame(UITLEG, columns=["onderdeel", "uitleg"]), "Uitleg")
        _schrijf_blad(writer, leadlijst.head(max_adressen), "Top")
        _schrijf_blad(writer, witte_vlekken.head(max_adressen), "Witte vlekken")
        for gemeente, deel in leadlijst.groupby("gemeente", sort=True):
            _schrijf_blad(writer, deel.head(max_adressen), _bladnaam(gemeente, gebruikt))
    return len(witte_vlekken)


def schrijf_csv(pad, leadlijst):
    # Puntkomma en utf-8-sig zodat Nederlandse Excel het bestand direct goed opent.
    leadlijst.to_csv(pad, index=False, sep=";", decimal=",", encoding="utf-8-sig")


def _metriektabel(resultaat, toevalskans):
    if not resultaat or "gemiddeld" not in resultaat:
        return "_niet berekend_\n"
    gem, spr = resultaat["gemiddeld"], resultaat["spreiding"]
    regels = ["| maat | waarde |", "|---|---|",
              f"| AUC | {gem['auc']:.3f} (± {spr['auc']:.3f}) |"]
    for sleutel in gem:
        if sleutel.startswith("p@"):
            regels.append(f"| precision top-{sleutel[2:]} | {gem[sleutel]:.1%} |")
    regels.append(f"| toevalskans | {toevalskans:.2%} |")
    return "\n".join(regels) + "\n"


def maak_rapport(info):
    """Markdown-rapport zonder adresgegevens (mag dus in de GitHub job summary)."""
    r = [f"# Leadgenerator – modelrapport ({info['datum']})", ""]
    r += ["## Data", "",
          f"- Adressen in Assetmaps: **{info['adressen']:,}**",
          f"- Klanten: **{info['klanten']:,}** ({info['toevalskans']:.2%})",
          f"- Adressen in TIOS zonder order (eerder contact): {info['eerder_contact']:,}",
          f"- Adressen in de leadlijst: **{info['leads']:,}**, waarvan {info['witte_vlekken']:,} "
          "in witte vlekken",
          f"- Kenmerken: {', '.join(info['kenmerken'])}", ""]
    for stat in info["cbs"]:
        r.append(f"- CBS {stat['kenmerk']}: {stat['buurt']:,} op buurtniveau, "
                 f"{stat['gemeente']:,} op gemeenteniveau, van {stat['totaal']:,}")
    if info["waarschuwingen"]:
        r += ["", "## ⚠️ Waarschuwingen", ""] + [f"- {w}" for w in info["waarschuwingen"]]

    ev = info.get("evaluatie")
    if ev:
        r += ["", "## Kwaliteit", "",
              "Precision top-k = aandeel echte klanten in de k hoogst gescoorde adressen.", "",
              "### Willekeurige kruisvalidatie", "", _metriektabel(ev["cv"], info["toevalskans"]),
              "### Postcodegebieden die het model nooit zag", "",
              _metriektabel(ev["groep"], info["toevalskans"])]
        bt = ev["backtest"]
        r += ["### Tijdsbacktest", ""]
        if "overgeslagen" in bt:
            r.append(f"_Overgeslagen: {bt['overgeslagen']}_")
        else:
            r.append(f"Getraind met {bt['klanten_tot_grens']} klanten t/m {bt['grensjaar']}; "
                     f"getest op {bt['nieuwe_klanten']} klanten daarna.")
            r += ["", "| maat | waarde |", "|---|---|", f"| AUC | {bt['auc']:.3f} |"]
            r += [f"| precision top-{k[2:]} | {v:.1%} |" for k, v in bt.items() if k.startswith("p@")]
            r.append(f"| toevalskans | {bt['toevalskans']:.2%} |")
        r += ["", "### Belangrijkste kenmerken", "",
              f"AUC op 20% testset: {ev['holdout_auc']:.3f}. Verlies in AUC als je het kenmerk "
              "door elkaar husselt:", "", "| kenmerk | AUC-verlies |", "|---|---|"]
        r += [f"| {k} | {v:+.4f} |" for k, v in ev["belangrijkheid"].items()]
    return "\n".join(r) + "\n"
