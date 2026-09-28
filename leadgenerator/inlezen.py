"""Excel-bestanden inlezen, kolomnamen opschonen en BAG-ID's controleren."""

import logging
import re

import pandas as pd

log = logging.getLogger(__name__)

# Kolommen die als tekst ingelezen moeten worden. Als getal verliezen BAG-ID's hun
# voorloopnul (0654... wordt 654...) en mislukt de koppeling tussen TIOS en Assetmaps stil.
TEKST_KOLOMMEN = {"vbo_id", "pand_id", "postcode", "huisnummer", "buurtcode"}

# Een BAG-ID is 16 cijfers: 4 cijfers gemeentecode, 2 cijfers objecttype, 10 cijfers volgnummer.
BAG_OBJECTTYPE = {"vbo_id": "01", "pand_id": "10"}

ASSETMAPS_VERPLICHT = ["vbo_id", "pand_id", "gemeente", "buurtnaam", "postcode"]


def technische_naam(kop):
    """'Zichtbare naam (technische_naam)' -> 'technische_naam'."""
    match = re.search(r"\(([^)]+)\)\s*$", str(kop).strip())
    return match.group(1).strip() if match else str(kop).strip()


def lees_blad(bestand, gewenst_blad):
    """Leest het gevraagde blad (of het eerste als het niet bestaat) met technische kolomnamen.
    ID- en postcodekolommen worden als tekst gelezen."""
    bladen = pd.ExcelFile(bestand).sheet_names
    blad = gewenst_blad
    if gewenst_blad not in bladen:
        blad = bladen[0]
        log.warning("Blad '%s' niet gevonden in '%s' (wel: %s). Gebruik '%s'.",
                    gewenst_blad, bestand, bladen, blad)

    koppen = pd.read_excel(bestand, sheet_name=blad, nrows=0).columns
    als_tekst = {kop: str for kop in koppen if technische_naam(kop) in TEKST_KOLOMMEN}
    df = pd.read_excel(bestand, sheet_name=blad, dtype=als_tekst)
    df.columns = [technische_naam(k) for k in df.columns]
    return df


def normaliseer_bag_id(serie):
    """Maakt van elke BAG-ID een tekst van 16 cijfers (herstelt een verloren voorloopnul)."""
    tekst = serie.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    tekst = tekst.where(tekst.str.fullmatch(r"\d{1,16}"))
    return tekst.str.zfill(16)


def _aandeel_type(serie, objecttype):
    geldig = serie.dropna()
    if geldig.empty:
        return 0.0
    return float((geldig.str[4:6] == objecttype).mean())


def controleer_bag_ids(df, bron):
    """Normaliseert vbo_id/pand_id en controleert of ze het juiste objecttype hebben.
    Zijn de twee kolommen verwisseld (bekend probleem in de exports), dan worden ze
    automatisch teruggewisseld. Geeft een lijst met waarschuwingen terug."""
    waarschuwingen = []
    for kolom in BAG_OBJECTTYPE:
        if kolom in df.columns:
            df[kolom] = normaliseer_bag_id(df[kolom])
    if not {"vbo_id", "pand_id"} <= set(df.columns):
        return waarschuwingen

    vbo_ok = _aandeel_type(df["vbo_id"], "01")
    pand_ok = _aandeel_type(df["pand_id"], "10")
    vbo_is_pand = _aandeel_type(df["vbo_id"], "10")
    pand_is_vbo = _aandeel_type(df["pand_id"], "01")

    if vbo_is_pand > 0.9 and pand_is_vbo > 0.9:
        df[["vbo_id", "pand_id"]] = df[["pand_id", "vbo_id"]].to_numpy()
        waarschuwingen.append(f"{bron}: vbo_id en pand_id waren verwisseld en zijn teruggewisseld.")
    elif vbo_ok < 0.9 or pand_ok < 0.9:
        waarschuwingen.append(
            f"{bron}: BAG-ID's lijken niet te kloppen ({vbo_ok:.0%} van vbo_id is een "
            f"verblijfsobject-ID, {pand_ok:.0%} van pand_id is een pand-ID). Controleer de kolommen."
        )
    for w in waarschuwingen:
        log.warning(w)
    return waarschuwingen


def controleer_kolommen(df, verwacht, bron):
    """Stopt met een duidelijke melding als verplichte kolommen ontbreken."""
    ontbrekend = [k for k in verwacht if k not in df.columns]
    if ontbrekend:
        raise ValueError(
            f"{bron}: kolom(men) {ontbrekend} niet gevonden. Beschikbare kolommen: "
            f"{list(df.columns)}. Pas zo nodig de instellingen in config.yaml aan."
        )


def lees_bronnen(tios_pad, assetmaps_pad, cfg):
    """Leest TIOS en Assetmaps in en controleert ze. Geeft (tios, assetmaps, waarschuwingen)."""
    tios = lees_blad(tios_pad, cfg.tios_blad)
    assetmaps = lees_blad(assetmaps_pad, cfg.assetmaps_blad)
    log.info("TIOS: %d rijen, Assetmaps: %d rijen ingelezen.", len(tios), len(assetmaps))

    tios_verplicht = [cfg.tios_kolommen["datum"], cfg.tios_kolommen["status"], "vbo_id", "pand_id"]
    controleer_kolommen(tios, tios_verplicht, "TIOS")
    controleer_kolommen(assetmaps, ASSETMAPS_VERPLICHT, "Assetmaps")

    waarschuwingen = controleer_bag_ids(tios, "TIOS") + controleer_bag_ids(assetmaps, "Assetmaps")
    return tios, assetmaps, waarschuwingen
