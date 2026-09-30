"""Leadlijst naar Excel en CSV, en het modelrapport."""

import numpy as np
import pandas as pd
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

# Excel kan per tabblad 1.048.576 rijen tonen, waarvan één de kopregel is.
EXCEL_MAX_RIJEN = 1_048_575

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

# Kolommen om bij te houden wie benaderd is; staan achteraan op elk adrestabblad.
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


def _kolombreedtes(df, maximum=40):
    breedtes = []
    for kolom in df.columns:
        waarden = [len(str(v)) for v in df[kolom].head(200)] if len(df) else [8]
        breedtes.append(min(max(len(str(kolom)), *waarden) + 2, maximum))
    return breedtes


def _schrijf_adresblad(boek, opmaak, df, naam):
    """Adrestabblad met achteraan 'benaderd' (keuzelijst) en 'opmerking'; afgevinkte rijen worden grijs.
    Rij voor rij geschreven, zodat ook 400.000+ adressen weinig geheugen kosten."""
    df = df.copy()
    for kolom in AFVINK_KOLOMMEN:
        df[kolom] = ""
    k_benaderd = df.columns.get_loc("benaderd")
    k_opmerking = df.columns.get_loc("opmerking")

    blad = boek.add_worksheet(naam)
    for i, breedte in enumerate(_kolombreedtes(df)):
        blad.set_column(i, i, breedte)
    blad.set_column(k_benaderd, k_benaderd, 14)
    blad.set_column(k_opmerking, k_opmerking, 30)
    if "redenen" in df.columns:
        i = df.columns.get_loc("redenen")
        blad.set_column(i, i, 70)

    blad.write_row(0, 0, list(df.columns), opmaak["kopregel"])
    rijen = df.astype(object).where(df.notna(), None).itertuples(index=False, name=None)
    for r, rij in enumerate(rijen, start=1):
        blad.write_row(r, 0, rij)

    laatste, laatste_kolom = max(len(df), 1), len(df.columns) - 1
    blad.freeze_panes(1, 2)  # kopregel en straat + huisnummer blijven zichtbaar bij scrollen
    blad.autofilter(0, 0, laatste, laatste_kolom)
    blad.data_validation(1, k_benaderd, laatste, k_benaderd, {
        "validate": "list", "source": BENADERD_KEUZES,
        "error_title": "Ongeldige keuze", "error_message": "Kies ja, nee of geen interesse.",
    })
    letter = xl_col_to_name(k_benaderd)
    blad.conditional_format(1, 0, laatste, laatste_kolom, {
        "type": "formula", "criteria": f'=${letter}2="ja"', "format": opmaak["afgevinkt"],
    })


def _duizend(n):
    return f"{int(n):,}".replace(",", ".")


def _lees_mij_tekst(context, kwaliteit):
    """(kop, tekst)-regels voor het eerste tabblad. Een kop zonder tekst is een sectietitel."""
    gebied = f"gemeente {context['gemeente']}" if context.get("gemeente") else "het hele bestand"
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
        ("", "Begin bovenaan het tabblad 'Resultaat': daar staan de kansrijkste adressen. Vul in de kolom "
             "'benaderd' (achteraan) ja, nee of 'geen interesse' in; bij 'ja' wordt de rij grijs. "
             "In 'opmerking' kun je notities kwijt."),
        ("", "Met de filterknoppen in de kopregel kies je bijvoorbeeld één gemeente, woonplaats of alleen "
             "klasse A. De volgorde op score blijft dan gewoon staan."),
        ("", "Let op: 'Witte vlekken' is een aparte kopie. Een adres dat je daar afvinkt, is op 'Resultaat' "
             "niet afgevinkt (en andersom)."),
        ("Tabbladen", ""),
        ("Resultaat", "Alle adressen die nog geen klant zijn, van hoogste naar laagste score"
                + (f" (de eerste {_duizend(context['op_top'])}; de rest staat in leadlijst_volledig.csv)."
                   if context["op_top"] < context["leads"] else ".")),
        ("Witte vlekken", "Laatste tabblad: kansrijke adressen in postcodegebieden waar nog géén klant "
                          "woont. Voor het openen van nieuwe gebieden; hier ontbreekt het buurteffect, "
                          "de score komt dus uit de woning zelf."),
        ("Hoe betrouwbaar is de lijst?", ""),
    ]
    regels += [(k, t) for k, t in kwaliteit if k and k != "Gemaakt op"]
    regels += [("Kolommen", "")] + KOLOMUITLEG
    return regels


def _schrijf_lees_mij(boek, opmaak, context, kwaliteit):
    blad = boek.add_worksheet("Uitleg")
    blad.hide_gridlines(2)
    blad.set_column(0, 0, 30, opmaak["tekst"])
    blad.set_column(1, 1, 110, opmaak["tekst"])
    for rij, (kop, tekst) in enumerate(_lees_mij_tekst(context, kwaliteit)):
        if rij == 0:
            stijl = opmaak["titel"]
        elif kop and not tekst:
            stijl = opmaak["sectie"]
        else:
            stijl = opmaak["label"]
        blad.write_string(rij, 0, kop, stijl)
        blad.write_string(rij, 1, tekst, opmaak["tekst"])


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
    """Drie tabbladen: Uitleg, Resultaat (alle adressen op volgorde van score) en Witte vlekken.
    `max_adressen` (0 = alles) begrenst het aantal rijen per adrestabblad."""
    limiet = min(max_adressen or EXCEL_MAX_RIJEN, EXCEL_MAX_RIJEN)
    context = {"datum": "", "bestanden": [], "leads": len(leadlijst), "klanten": 0, "gemeente": None,
               **(context or {}), "op_top": min(len(leadlijst), limiet)}
    geen_klant_dichtbij = (leadlijst["klanten_in_buurt"] == 0) & (leadlijst["klanten_in_postcode4"] == 0)
    witte_vlekken = leadlijst[geen_klant_dichtbij]

    # strings_to_formulas uit: een adres of opmerking die met '=' begint blijft gewoon tekst.
    boek = xlsxwriter.Workbook(pad, {"constant_memory": True, "strings_to_formulas": False,
                                     "strings_to_urls": False})
    opmaak = {
        "kopregel": boek.add_format({"bold": True, "bottom": 1}),
        "afgevinkt": boek.add_format({"bg_color": "#E7E6E6", "font_color": "#808080"}),
        "titel": boek.add_format({"bold": True, "font_size": 16}),
        "sectie": boek.add_format({"bold": True, "font_size": 12, "font_color": "#1F4E78",
                                   "text_wrap": True, "valign": "top"}),
        "label": boek.add_format({"bold": True, "text_wrap": True, "valign": "top"}),
        "tekst": boek.add_format({"text_wrap": True, "valign": "top"}),
    }
    _schrijf_lees_mij(boek, opmaak, context, kwaliteit)
    _schrijf_adresblad(boek, opmaak, leadlijst.head(limiet), "Resultaat")
    _schrijf_adresblad(boek, opmaak, witte_vlekken.head(limiet), "Witte vlekken")
    boek.close()
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
