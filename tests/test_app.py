import pytest

from leadgenerator import app_hulp as hulp
from leadgenerator.pipeline import run


def test_excel_bestanden_en_raden(tmp_path):
    for naam in ["Woningen_Zeeland.xlsx", "TIOS_export.xlsx", "~$tijdelijk.xlsx", "notities.txt"]:
        (tmp_path / naam).write_bytes(b"")
    namen = hulp.excel_bestanden(tmp_path)
    assert namen == ["TIOS_export.xlsx", "Woningen_Zeeland.xlsx"]
    assert hulp.raad_bestand(namen, "tios") == 0
    assert hulp.raad_bestand(namen, "woningen") == 1
    assert hulp.raad_bestand(namen, "bestaatniet") == 0
    assert hulp.excel_bestanden(tmp_path / "bestaat_niet") == []


def test_veilige_bestandsnaam():
    assert hulp.veilige_bestandsnaam("../../etc/passwd.xlsx") == "passwd.xlsx"
    assert hulp.veilige_bestandsnaam("a<b>.xlsx") == "a_b_.xlsx"


@pytest.mark.parametrize("fout,woord", [
    (ValueError("TIOS: kolom(men) ['status'] niet gevonden. Beschikbare kolommen: []"), "TIOS"),
    (ValueError("Gemeente 'X' komt niet voor in de data."), "gemeente"),
    (PermissionError("x"), "Excel"),
    (RuntimeError("onbekend"), "details"),
])
def test_vriendelijke_fout(fout, woord):
    titel, tip = hulp.vriendelijke_fout(fout)
    assert woord.lower() in (titel + tip).lower()


def test_voortgang_resultaat_en_runs(bestanden, cfg, tmp_path):
    import logging

    berichten = []
    handler = hulp.VoortgangHandler(lambda tekst, niveau: berichten.append(tekst))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    try:
        tios_pad, assetmaps_pad = bestanden
        uitmap = tmp_path / "output" / "2026-01-01_0000_demo"
        run(tios_pad, assetmaps_pad, uitmap, cfg)
    finally:
        logging.getLogger().removeHandler(handler)
    assert any("Leadlijst scoren" in b for b in berichten)

    voorbeeld, totaal = hulp.lees_voorbeeld(uitmap, n=5)
    assert len(voorbeeld) == 5 and totaal > 5
    assert sum(hulp.klasse_telling(uitmap).values()) == totaal
    assert hulp.eerdere_runs(tmp_path)[0][0] == "2026-01-01_0000_demo"


def test_app_start_zonder_fout(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("LEADGEN_MAP", str(tmp_path))
    app = AppTest.from_file("app.py", default_timeout=60).run()
    assert not app.exception
    assert any("minder dan twee" in w.value for w in app.warning)
