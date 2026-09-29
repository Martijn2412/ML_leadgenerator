import pandas as pd
import pytest

from leadgenerator.inlezen import (
    controleer_bag_ids,
    controleer_kolommen,
    lees_bronnen,
    normaliseer_bag_id,
    technische_naam,
)


def test_technische_naam():
    assert technische_naam("BAG-ID (vbo_id)") == "vbo_id"
    assert technische_naam("Aanmaakdatum (datum) ") == "datum"
    assert technische_naam("zonder haakjes") == "zonder haakjes"


def test_voorloopnul_wordt_hersteld():
    serie = pd.Series([654010000000001, "0654010000000001", "654010000000001.0", None])
    uit = normaliseer_bag_id(serie)
    assert list(uit[:3]) == ["0654010000000001"] * 3
    assert pd.isna(uit[3])


def test_verwisselde_ids_worden_teruggewisseld():
    df = pd.DataFrame({
        "vbo_id": ["0654100000000001", "0654100000000002"],
        "pand_id": ["0654010000000001", "0654010000000002"],
    })
    waarschuwingen = controleer_bag_ids(df, "test")
    assert df["vbo_id"].str[4:6].eq("01").all()
    assert df["pand_id"].str[4:6].eq("10").all()
    assert "verwisseld" in waarschuwingen[0]


def test_ontbrekende_kolom_geeft_duidelijke_fout():
    with pytest.raises(ValueError, match="niet gevonden"):
        controleer_kolommen(pd.DataFrame({"a": [1]}), ["vbo_id"], "TIOS")


def test_tios_en_assetmaps_koppelen_ondanks_getal_ids(bestanden, cfg):
    tios, assetmaps, _ = lees_bronnen(*bestanden, cfg)
    assert assetmaps["vbo_id"].str.len().eq(16).all()
    assert tios["vbo_id"].isin(assetmaps["vbo_id"]).all()
