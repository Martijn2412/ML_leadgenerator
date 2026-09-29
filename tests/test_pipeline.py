import pandas as pd

from cli import main
from leadgenerator.pipeline import run


def test_hele_run(bestanden, cfg, tmp_path):
    tios_pad, assetmaps_pad = bestanden
    resultaat = run(tios_pad, assetmaps_pad, tmp_path / "uit", cfg)

    for pad in resultaat.bestanden:
        assert pad.exists(), pad
    bladen = pd.ExcelFile(resultaat.uitmap / "leadlijst.xlsx").sheet_names
    assert bladen[:3] == ["Uitleg", "Top", "Witte vlekken"]
    assert {"Middelburg", "Vlissingen", "Hulst"} <= set(bladen)

    top = pd.read_excel(resultaat.uitmap / "leadlijst.xlsx", sheet_name="Top")
    assert len(top) == cfg.excel_max_adressen
    assert top["score"].is_monotonic_decreasing
    assert set(top["klasse"]) <= {"A", "B", "C"}

    volledig = pd.read_csv(resultaat.uitmap / "leadlijst_volledig.csv", sep=";", decimal=",")
    assert len(volledig) > cfg.excel_max_adressen
    assert (volledig["eerder_contact"] == "ja").any()  # offertes zonder order zijn gemarkeerd

    uitleg = pd.read_excel(resultaat.uitmap / "leadlijst.xlsx", sheet_name="Uitleg")
    assert uitleg["onderdeel"].str.startswith("Kwaliteit", na=False).any()
    assert uitleg["uitleg"].str.contains("AUC", na=False).any()

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
                 "--gemeente", "hulst", "--geen-evaluatie", "--uit", str(uit)])
    assert code == 0
    volledig = pd.read_csv(uit / "leadlijst_volledig.csv", sep=";", decimal=",")
    assert set(volledig["gemeente"]) == {"Hulst"}
