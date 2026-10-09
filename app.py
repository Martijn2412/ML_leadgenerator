"""Leadgenerator Takkenkamp als webpagina.

    streamlit run app.py

Kies een Assetmaps- en TIOS-bestand, klik op de knop en download de leadlijst.
De map met bestanden staat in LEADGEN_MAP (standaard: de huidige map).
"""

import datetime as dt
import logging
import os
import traceback
from pathlib import Path

import streamlit as st

from leadgenerator import app_hulp as hulp
from leadgenerator.config import ENERGIELABEL_KEUZES, laad_config
from leadgenerator.demodata import schrijf_demodata
from leadgenerator.pipeline import run

st.set_page_config(page_title="Leadgenerator Takkenkamp", page_icon="🏠", layout="centered")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BESTANDSTYPES = {
    "leadlijst.xlsx": ("Leadlijst (Excel)", XLSX),
    "leadlijst_volledig.csv": ("Alle adressen (CSV)", "text/csv"),
    "modelrapport.md": ("Modelrapport", "text/markdown"),
}


def toon_downloads(uitmap, sleutel):
    """Downloadknoppen voor de bestanden van één run."""
    uitmap = Path(uitmap)
    kolommen = st.columns(len(BESTANDSTYPES))
    for kolom, (naam, (label, mime)) in zip(kolommen, BESTANDSTYPES.items(), strict=True):
        pad = uitmap / naam
        if pad.exists():
            kolom.download_button(label, pad.read_bytes(), file_name=naam, mime=mime,
                                  key=f"{sleutel}-{naam}", use_container_width=True,
                                  type="primary" if naam == "leadlijst.xlsx" else "secondary")


def toon_resultaat(uitmap, rapport=None):
    voorbeeld, totaal = hulp.lees_voorbeeld(uitmap)
    klassen = hulp.klasse_telling(uitmap)
    kolommen = st.columns(4)
    kolommen[0].metric("Adressen in de lijst", f"{totaal:,}".replace(",", "."))
    for kolom, klasse in zip(kolommen[1:], "ABC", strict=True):
        kolom.metric(f"Klasse {klasse}", f"{klassen.get(klasse, 0):,}".replace(",", "."))
    toon_downloads(uitmap, "nieuw")
    st.caption("Open de Excel en kijk eerst op het tabblad **Uitleg**.")
    if voorbeeld is not None:
        st.subheader("De eerste 25 adressen")
        st.dataframe(voorbeeld, hide_index=True, use_container_width=True)
    if rapport:
        with st.expander("Hoe goed is het model? (modelrapport)"):
            st.markdown(rapport)


# ---------------------------------------------------------------- kop en map
st.title("🏠 Leadgenerator Takkenkamp")
st.write("Maak een lijst met de woningen die de grootste kans hebben om klant te worden.")

with st.sidebar:
    st.header("Waar staan de bestanden?")
    map_ = st.text_input("Map", value=os.environ.get("LEADGEN_MAP", "."),
                         help="De map met de Excel-exports van Assetmaps en TIOS. "
                              "De lijsten komen in de submap 'output'.")
    st.divider()
    st.subheader("Zomaar proberen")
    st.caption("Maakt twee bestanden met verzonnen adressen, zonder klantgegevens.")
    if st.button("Demo-bestanden maken", use_container_width=True):
        schrijf_demodata(map_, n=3000)
        st.success("Klaar: kies hieronder Woningen_demo.xlsx en TIOS_demo.xlsx.")

if not Path(map_).is_dir():
    st.error(f"De map '{map_}' bestaat niet. Pas de map links aan.")
    st.stop()

# ---------------------------------------------------------------- stap 1: bestanden
st.header("1. Kies de bestanden")
with st.expander("Bestanden uploaden in plaats van kiezen"):
    uploads = st.file_uploader("Excel-bestanden (.xlsx)", type=["xlsx"], accept_multiple_files=True)
    if uploads and st.button("Opslaan in de map"):
        for upload in uploads:
            (Path(map_) / hulp.veilige_bestandsnaam(upload.name)).write_bytes(upload.getbuffer())
        st.success(f"{len(uploads)} bestand(en) opgeslagen.")
        st.rerun()

namen = hulp.excel_bestanden(map_)
if len(namen) < 2:
    st.warning("Er staan minder dan twee Excel-bestanden in de map. Upload ze hierboven, "
               "of zet ze in de map.")
    st.stop()

links, rechts = st.columns(2)
assetmaps = links.selectbox("Assetmaps-bestand (de woningen)", namen,
                            index=hulp.raad_bestand(namen, "woningen"))
tios = rechts.selectbox("TIOS-bestand (de klanten)", namen, index=hulp.raad_bestand(namen, "tios"))

# ---------------------------------------------------------------- stap 2: opties
st.header("2. Wat wil je zien?")
gemeente = st.text_input("Alleen deze gemeente (leeg = alle gemeenten)", placeholder="bijv. Veere")
with st.expander("Meer opties (meestal niet nodig)"):
    energielabel = st.selectbox(
        "Energielabel bij klanten", ENERGIELABEL_KEUZES,
        help="gebruiken = gewoon meenemen (standaard). weglaten = niet gebruiken, als het label bij "
             "klanten pas ná de isolatie is gemeten. Zie de uitleg in het README.")
    evaluatie = st.checkbox("Ook de kwaliteitstest draaien (duurt veel langer)", value=False)
    max_adressen = st.number_input("Maximaal aantal adressen per Excel-tabblad (0 = alle)",
                                   min_value=0, value=0, step=1000)

# ---------------------------------------------------------------- stap 3: draaien
st.header("3. Maak de lijst")
if tios == assetmaps:
    st.error("Je hebt twee keer hetzelfde bestand gekozen.")
    st.stop()
st.caption("Dit duurt 5 tot 30 minuten, afhankelijk van de regio. Laat dit venster open staan.")

if st.button("Leadlijst maken", type="primary", use_container_width=True):
    st.session_state.pop("resultaat", None)
    uitmap = Path(map_) / "output" / f"{dt.datetime.now():%Y-%m-%d_%H%M}_{Path(assetmaps).stem}"
    cfg = laad_config(os.environ.get("LEADGEN_CONFIG"))
    cfg.energielabel_bij_klanten = energielabel
    voortgang = st.status("Bezig ...", expanded=True)
    regels = []

    def toon(bericht, niveau):
        regels.append(bericht)
        if niveau >= logging.WARNING:
            voortgang.write(f"⚠️ {bericht}")
        else:
            voortgang.write(bericht)
            voortgang.update(label=bericht)

    handler = hulp.VoortgangHandler(toon)
    root = logging.getLogger()
    root.addHandler(handler)
    oud_niveau = root.level
    root.setLevel(logging.INFO)
    try:
        resultaat = run(Path(map_) / tios, Path(map_) / assetmaps, uitmap, cfg, evalueren=evaluatie,
                        gemeente=gemeente.strip() or None, max_adressen=int(max_adressen) or None)
    except Exception as fout:  # noqa: BLE001 - alles melden in gewone taal, details uitklapbaar
        voortgang.update(label="Het is niet gelukt", state="error")
        titel, tip = hulp.vriendelijke_fout(fout)
        st.error(titel)
        st.info(tip)
        with st.expander("Technische details (voor de beheerder)"):
            st.code("".join(traceback.format_exception(fout)))
    else:
        voortgang.update(label="Klaar!", state="complete", expanded=False)
        st.session_state["resultaat"] = (str(resultaat.uitmap), resultaat.rapport)
    finally:
        root.removeHandler(handler)
        root.setLevel(oud_niveau)

if "resultaat" in st.session_state:
    uitmap, rapport = st.session_state["resultaat"]
    st.success("De leadlijst staat klaar.")
    toon_resultaat(uitmap, rapport)

# ---------------------------------------------------------------- eerdere lijsten
eerder = hulp.eerdere_runs(map_)
if eerder:
    st.divider()
    with st.expander(f"Eerder gemaakte lijsten ({len(eerder)})"):
        keuze = st.selectbox("Kies een lijst", [naam for naam, _ in eerder])
        toon_downloads(dict(eerder)[keuze], "eerder")
