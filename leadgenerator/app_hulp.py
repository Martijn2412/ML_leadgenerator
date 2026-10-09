"""Hulpfuncties voor de Streamlit-app (app.py): bestanden zoeken, voortgang en foutmeldingen
in gewone taal. Staat los van Streamlit zodat het getest kan worden."""

import logging
import re
from pathlib import Path

import pandas as pd

EXCEL_ENDINGS = {".xlsx", ".xlsm"}


def excel_bestanden(map_):
    """Namen van de Excel-bestanden in `map_` (niet in submappen, geen tijdelijke ~$-bestanden)."""
    map_ = Path(map_)
    if not map_.is_dir():
        return []
    return sorted(
        p.name for p in map_.iterdir()
        if p.is_file() and p.suffix.lower() in EXCEL_ENDINGS and not p.name.startswith("~$")
    )


def raad_bestand(namen, trefwoord):
    """Positie van het eerste bestand waarvan de naam het trefwoord bevat (anders 0)."""
    for i, naam in enumerate(namen):
        if trefwoord in naam.lower():
            return i
    return 0


def veilige_bestandsnaam(naam):
    """Haalt mappen en vreemde tekens uit een geüploade bestandsnaam."""
    naam = Path(str(naam)).name
    return re.sub(r"[^\w.\- ()]", "_", naam)


def eerdere_runs(map_):
    """Outputmappen met een leadlijst, nieuwste eerst: lijst van (mapnaam, pad)."""
    uit = Path(map_) / "output"
    if not uit.is_dir():
        return []
    mappen = [p for p in uit.iterdir() if p.is_dir() and (p / "leadlijst.xlsx").exists()]
    return [(p.name, p) for p in sorted(mappen, key=lambda p: p.name, reverse=True)]


def lees_voorbeeld(uitmap, n=25):
    """Eerste `n` regels en totaal aantal regels van de volledige leadlijst (CSV), of (None, 0)."""
    pad = Path(uitmap) / "leadlijst_volledig.csv"
    if not pad.exists():
        return None, 0
    tabel = pd.read_csv(pad, sep=";", decimal=",", dtype=str)
    return tabel.head(n), len(tabel)


def klasse_telling(uitmap):
    """Aantal adressen per klasse (A/B/C) uit de CSV."""
    pad = Path(uitmap) / "leadlijst_volledig.csv"
    if not pad.exists():
        return {}
    klassen = pd.read_csv(pad, sep=";", usecols=["klasse"], dtype=str)["klasse"]
    return klassen.value_counts().to_dict()


def vriendelijke_fout(fout):
    """(titel, tip) in gewone taal voor een fout uit de pipeline."""
    tekst = str(fout)
    if isinstance(fout, PermissionError):
        return ("Een bestand kon niet geopend worden.",
                "Staat het bestand nog open in Excel? Sluit het en probeer opnieuw.")
    if isinstance(fout, FileNotFoundError):
        return ("Bestand niet gevonden.", "Controleer of de gekozen map en bestanden nog bestaan.")
    if "niet gevonden. Beschikbare kolommen" in tekst:
        bron = tekst.split(":", 1)[0]
        return (f"Het {bron}-bestand heeft niet de verwachte kolommen. {tekst}",
                "Heb je TIOS en Assetmaps misschien omgewisseld? Of is dit een andere export?")
    if "Geen enkel TIOS-adres gekoppeld" in tekst:
        return (tekst, "Zijn dit wel de bestanden van dezelfde regio? Controleer ook of de TIOS- en "
                       "Assetmaps-bestand niet omgewisseld zijn.")
    if "Maar " in tekst and "te weinig om een model" in tekst:
        return (tekst, "Neem een grotere regio of een TIOS-export met meer klanten.")
    if "komt niet voor in de data" in tekst:
        return (tekst, "Controleer de spelling van de gemeente, of laat het veld leeg voor alle gemeenten.")
    if isinstance(fout, MemoryError):
        return ("Er is te weinig geheugen voor dit bestand.",
                "Probeer één gemeente, of een kleiner aantal adressen.")
    return ("Er ging iets mis.", "Probeer het nog eens. Blijft het misgaan, stuur dan de details "
                                 "hieronder door aan de beheerder.")


class VoortgangHandler(logging.Handler):
    """Stuurt logregels van de pipeline door naar een functie (de app toont ze als voortgang)."""

    def __init__(self, doorgeven):
        super().__init__(level=logging.INFO)
        self.doorgeven = doorgeven

    def emit(self, record):
        if record.name.startswith("leadgenerator"):
            self.doorgeven(record.getMessage(), record.levelno)
