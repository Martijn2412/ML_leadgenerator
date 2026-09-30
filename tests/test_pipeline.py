import pandas as pd
from openpyxl import load_workbook

from cli import main
from leadgenerator.pipeline import run


def test_hele_run(bestanden, cfg, tmp_path):
    tios_pad, assetmaps_pad = bestanden
    resultaat = run(tios_pad, assetmaps_pad, tmp_path / "uit", cfg, evalueren=True)

    for pad in resultaat.bestanden:
        assert pad.exists(), pad
    excel = resultaat.uitmap / "leadlijst.xlsx"
    bladen = pd.ExcelFile(excel).sheet_names
    assert bladen == ["Uitleg", "Resultaat", "Witte vlekken"]

    top = pd.read_excel(excel, sheet_name="Resultaat")
    assert list(top.columns[:2]) == ["benaderd", "opmerking"]
    assert len(top) == cfg.excel_max_adressen  # begrensd in deze test
    assert top["score"].is_monotonic_decreasing
    assert set(top["klasse"]) <= {"A", "B", "C"}
    assert top["redenen"].fillna("").str.len().gt(0).mean() > 0.9  # bijna overal een reden

    blad = load_workbook(excel)["Resultaat"]
    keuzelijsten = blad.data_validations.dataValidation
    assert keuzelijsten and "ja" in keuzelijsten[0].formula1
    assert "A2" in str(keuzelijsten[0].sqref)

    volledig = pd.read_csv(resultaat.uitmap / "leadlijst_volledig.csv", sep=";", decimal=",")
    assert len(volledig) > cfg.excel_max_adressen
    assert (volledig["eerder_contact"] == "ja").any()  # offertes zonder order zijn gemarkeerd

    lees_mij = pd.read_excel(excel, sheet_name="Uitleg", header=None).fillna("")
    assert lees_mij.iloc[0, 0] == "Leadlijst Takkenkamp"
    assert (lees_mij[0] == "Wat is dit?").any()
    assert lees_mij[0].str.startswith("Kwaliteit").any()
    assert lees_mij[1].str.contains("AUC").any()

    assert "Tijdsbacktest" in resultaat.rapport
    assert "Teststraat" not in resultaat.rapport  # geen adressen in het rapport


def test_gemeentefilter_en_cli(bestanden, tmp_path, monkeypatch):
    tios_pad, assetmaps_pad = bestanden
    config = tmp_path / "config.yaml"
    config.write_text(
        "cbs_offline: true\nrf_bomen: 20\nscoring_folds: 3\nbinnen_folds: 3\n", encoding="utf-8"
    )
    uit = tmp_path / "cli_uit"
    code = main(["--config", str(config), "run", "--map", str(tios_pad.parent),
                 "--tios", tios_pad.name, "--assetmaps", assetmaps_pad.name,
                 "--gemeente", "hulst", "--uit", str(uit)])
    assert code == 0
    volledig = pd.read_csv(uit / "leadlijst_volledig.csv", sep=";", decimal=",")
    assert set(volledig["gemeente"]) == {"Hulst"}
    lees_mij = pd.read_excel(uit / "leadlijst.xlsx", sheet_name="Uitleg", header=None).fillna("")
    assert lees_mij[1].str.contains("Niet gemeten").any()  # standaard geen evaluatie
    assert "Hulst" in " ".join(lees_mij[1])
    top = pd.read_excel(uit / "leadlijst.xlsx", sheet_name="Resultaat")
    assert len(top) == len(volledig)  # standaard staan álle adressen op Resultaat
    assert top["score"].is_monotonic_decreasing
