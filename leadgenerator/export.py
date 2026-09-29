"""Leadlijst naar Excel en CSV, en het modelrapport."""

import re

import numpy as np
import pandas as pd
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

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
    "redenen": "redenen",
    "eerder_contact": "eerder_contact",
    "klanten_in_buurt": "klanten_in_buurt",
    "klanten_in_postcode4": "klanten_in_postcode4",
}

# Kolommen om bij te houden wie benaderd is; staan vooraan op elk adrestabblad.
AFVINK_KOLOMMEN = ["benaderd", "opmerking"]
BENADERD_KEUZES = ["ja", "nee", "geen interesse"]

KOLOMUITLEG = [
    ("benaderd", "Vul hier in of het adres benaderd is (keuzelijst: ja / nee / geen interesse). "
                 "Bij 'ja' wordt de rij grijs."),
    ("opmerking", "Ruimte voor eigen notities, bijv. datum of reactie."),
    ("klasse", "A = top 10% kansrijkste adressen, B = volgende 20%, C = de rest."),
    ("score", "0-100: hoeveel procent van de adressen lager scoort. Een volgorde, geen kans."),
    ("redenen", "De (max. 3) kenmerken die de score van dit adres het meest omhoog brengen."),
    ("eerder_contact", "ja = dit adres staat al in TIOS (bijv. een offerte) maar werd geen klant."),
    ("klanten_in_buurt", "Aantal bestaande klanten in dezelfde buurt."),
    ("klanten_in_postcode4", "Aantal bestaande klanten in hetzelfde postcodegebied (4 cijfers)."),
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


def _pas_breedte_aan(blad, df, maximum=40):
    for i, kolom in enumerate(df.columns, start=1):
        waarden = [len(str(v)) for v in df[kolom].head(200)] if len(df) else [8]
        breedte = min(max(len(str(kolom)), *waarden) + 2, maximum)
        blad.column_dimensions[blad.cell(1, i).column_letter].width = breedte


def _schrijf_adresblad(writer, df, naam):
    """Adrestabblad met vooraan 'benaderd' (keuzelijst) en 'opmerking'; afgevinkte rijen worden grijs."""
    df = df.copy()
    for i, kolom in enumerate(AFVINK_KOLOMMEN):
        df.insert(i, kolom, "")
    df.to_excel(writer, sheet_name=naam, index=False)
    blad = writer.sheets[naam]
    blad.freeze_panes = "C2"
    _pas_breedte_aan(blad, df)
    blad.column_dimensions["A"].width = 14
    blad.column_dimensions["B"].width = 30
    if "redenen" in df.columns:
        letter = blad.cell(1, df.columns.get_loc("redenen") + 1).column_letter
        blad.column_dimensions[letter].width = 70

    laatste_rij = max(len(df) + 1, 2)
    keuzelijst = DataValidation(
        type="list", formula1='"' + ",".join(BENADERD_KEUZES) + '"', allow_blank=True,
        showErrorMessage=True, errorTitle="Ongeldige keuze",
        error="Kies ja, nee of geen interesse.",
    )
    blad.add_data_validation(keuzelijst)
    keuzelijst.add(f"A2:A{laatste_rij}")
    grijs = FormulaRule(formula=['$A2="ja"'], fill=PatternFill("solid", fgColor="E7E6E6"),
                        font=Font(color="808080"))
    blad.conditional_formatting.add(f"A2:{blad.cell(1, len(df.columns)).column_letter}{laatste_rij}", grijs)
    if len(df):
        blad.auto_filter.ref = blad.dimensions
    for cel in blad[1]:
        cel.font = Font(bold=True)


def _duizend(n):
    return f"{int(n):,}".replace(",", ".")


def _lees_mij_tekst(context, kwaliteit):
    """(kop, tekst)-regels voor het eerste tabblad. Een kop zonder tekst is een sectietitel."""
    gebied = f"gemeente {context['gemeente']}" if context.get("gemeente") else "het hele bestand"
    max_ = _duizend(context["max_adressen"])
    regels = [
        ("Leadlijst Takkenkamp", ""),
        ("Wat is dit?", ""),
        ("", f"Dit bestand bevat {_duizend(context['leads'])} adressen in {gebied} die nog géén "
             "klant zijn, gesorteerd van meest naar minst kansrijk om klant te worden bij Takkenkamp. "
             "Bovenaan staan de adressen die het meest lijken op woningen die al klant zijn."),
        ("", f"Gemaakt op {context['datum']} met {' en '.join(context['bestanden'])}. "
             f"Het model leerde van {_duizend(context['klanten'])} bestaande klanten."),
        ("Hoe komt de volgorde tot stand?", ""),
        ("", "Een rekenmodel heeft gekeken welke kenmerken klanten uit TIOS gemeen hebben: bouwjaar, "
             "energielabel, oppervlakte, WOZ-waarde, gasverbruik en inkomen in de buurt (CBS) en hoeveel "
             "klanten er al in de buurt wonen. Elk ander adres krijgt een score op basis van die kenmerken."),
        ("Hoe lees je de lijst?", ""),
        ("", "Klasse A = de 10% kansrijkste adressen, B = de volgende 20%, C = de rest. Begin bij A."),
        ("", "De score (0-100) is een volgorde, géén kans: score 95 betekent dat 95% van de adressen "
             "lager scoort, niet dat er 95% kans is op een opdracht."),
        ("", "De kolom 'redenen' laat per adres zien welke kenmerken de score het meest omhoog brengen. "
             "Handig als gespreksopener, bijvoorbeeld 'uw woning is van vóór 1975'."),
        ("", "'eerder_contact = ja' betekent: dit adres staat al in TIOS (bijvoorbeeld een offerte), "
             "maar werd geen klant. Kijk in TIOS wat er toen speelde voordat je belt."),
        ("Hoe werk je ermee?", ""),
        ("", "Vul in de kolom 'benaderd' ja, nee of 'geen interesse' in; bij 'ja' wordt de rij grijs. "
             "In 'opmerking' kun je notities kwijt. Met de filterknoppen in de kopregel kun je bijvoorbeeld "
             "alleen klasse A of één woonplaats tonen."),
        ("", "Let op: elk tabblad is een eigen kopie. Afvinken op 'Top' verandert het gemeente-tabblad niet. "
             "Werk voor één actie dus vanuit één tabblad."),
        ("Tabbladen", ""),
        ("Top", f"De {max_} kansrijkste adressen van de hele lijst."),
        ("Per gemeente", f"Per gemeente de {max_} kansrijkste adressen, bijvoorbeeld voor een brievenactie."),
        ("Witte vlekken", "Laatste tabblad: kansrijke adressen in postcodegebieden waar nog géén klant "
                          "woont. Voor het openen van nieuwe gebieden; hier ontbreekt het buurteffect, "
                          "de score komt dus uit de woning zelf."),
        ("Volledige lijst", "Alle adressen staan in leadlijst_volledig.csv "
                            "(Excel toont max. ~1 miljoen rijen)."),
        ("Hoe betrouwbaar is de lijst?", ""),
    ]
    regels += [(k, t) for k, t in kwaliteit if k and k != "Gemaakt op"]
    regels += [("Kolommen", "")] + KOLOMUITLEG
    return regels


def _schrijf_lees_mij(writer, context, kwaliteit):
    blad = writer.book.create_sheet("Lees mij", 0)
    blad.column_dimensions["A"].width = 30
    blad.column_dimensions["B"].width = 110
    boven = Alignment(wrap_text=True, vertical="top")
    for rij, (kop, tekst) in enumerate(_lees_mij_tekst(context, kwaliteit), start=1):
        a, b = blad.cell(rij, 1, kop), blad.cell(rij, 2, tekst)
        a.alignment = b.alignment = boven
        if rij == 1:
            a.font = Font(bold=True, size=16)
        elif kop and not tekst:
            a.font = Font(bold=True, size=12, color="1F4E78")
        elif kop:
            a.font = Font(bold=True)
    blad.sheet_view.showGridLines = False


def _beste_k(scores):
    """Grootste top-k waarvoor een precision berekend is, met die precision."""
    ks = [int(s[2:]) for s in scores if s.startswith("p@")]
    return (max(ks), scores[f"p@{max(ks)}"]) if ks else (None, None)


def _pct(waarde, decimalen=1):
    return f"{waarde * 100:.{decimalen}f}%".replace(".", ",")


def _keer(p, toevalskans):
    if not toevalskans:
        return ""
    factor = f"{p / toevalskans:.1f}".replace(".", ",")
    return f" Bij willekeurig kiezen is dat {_pct(toevalskans, 2)}, dus {factor}× zo goed."


def kwaliteit_regels(ev, toevalskans, waarschuwingen, datum, bestanden):
    """Regels voor bovenaan het uitlegblad: hoe betrouwbaar is deze lijst, in gewone taal."""
    regels = [("Gemaakt op", f"{datum} met {' en '.join(bestanden)}")]
    if not ev:
        regels.append(("Kwaliteit", "Niet gemeten in deze run (de kwaliteitstest stond uit)."))
    else:
        bt = ev.get("backtest", {})
        if "auc" in bt:
            k, p = _beste_k(bt)
            if k:
                regels.append((
                    "Kwaliteit (test op nieuwe klanten)",
                    f"Het model kende alleen de klanten t/m {bt['grensjaar']}. Van de {k} adressen die "
                    f"het toen bovenaan zette, werd daarna {_pct(p)} klant."
                    + _keer(p, bt["toevalskans"]),
                ))
        cv = ev.get("cv", {}).get("gemiddeld", {})
        if cv:
            k, p = _beste_k(cv)
            if k:
                regels.append(("Kwaliteit (kruisvalidatie)",
                               f"Van de top-{k} is {_pct(p)} al klant." + _keer(p, toevalskans)))
            auc = f"AUC {cv['auc']:.2f}".replace(".", ",")
            if "auc" in bt:
                auc += f" (test op nieuwe klanten: {bt['auc']:.2f})".replace(".", ",")
            regels.append(("AUC", auc + ". 0,5 = gokken, 1 = perfect; 0,65–0,75 is goed bruikbaar."))
    regels += [("Let op", w) for w in waarschuwingen]
    return regels + [("", "")]


def schrijf_excel(pad, leadlijst, max_adressen, kwaliteit=(), context=None):
    """Tabbladen: Lees mij, Top, één per gemeente en als laatste Witte vlekken
    (adrestabbladen elk max. `max_adressen` rijen)."""
    context = context or {"datum": "", "bestanden": [], "leads": len(leadlijst), "klanten": 0,
                          "gemeente": None, "max_adressen": max_adressen}
    gebruikt = {"lees mij", "top", "witte vlekken"}
    geen_klant_dichtbij = (leadlijst["klanten_in_buurt"] == 0) & (leadlijst["klanten_in_postcode4"] == 0)
    witte_vlekken = leadlijst[geen_klant_dichtbij]
    with pd.ExcelWriter(pad, engine="openpyxl") as writer:
        _schrijf_adresblad(writer, leadlijst.head(max_adressen), "Top")
        for gemeente, deel in leadlijst.groupby("gemeente", sort=True):
            _schrijf_adresblad(writer, deel.head(max_adressen), _bladnaam(gemeente, gebruikt))
        _schrijf_adresblad(writer, witte_vlekken.head(max_adressen), "Witte vlekken")
        _schrijf_lees_mij(writer, context, kwaliteit)
        writer.book.active = 0
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
