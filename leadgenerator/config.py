"""Instellingen laden uit config.yaml."""

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

REPO_MAP = Path(__file__).resolve().parent.parent
STANDAARD_CONFIG = REPO_MAP / "config.yaml"
CBS_CACHE_MAP = REPO_MAP / "data" / "cbs"


@dataclass
class Config:
    tios_blad: str = "WoningBron"
    assetmaps_blad: str = "Blad1"
    missing_code: int = -99997
    order_statussen: list = field(default_factory=lambda: [
        "Overgedragen aan Planning", "Opdracht", "Opdracht o.v.v. Subsidie",
    ])
    tios_kolommen: dict = field(default_factory=lambda: {"datum": "datum", "status": "status"})
    missing_indicator_drempel: float = 0.005

    random_state: int = 42
    rf_bomen: int = 500
    rf_max_diepte: int = 8
    rf_min_blad: int = 30
    lr_c: float = 1.0

    binnen_folds: int = 5
    scoring_folds: int = 5

    cv_folds: int = 3
    groep_folds: int = 5
    k_waarden: list = field(default_factory=lambda: [50, 100, 250, 500])
    permutatie_steekproef: int = 20_000
    backtest_jaren: int = 2

    excel_max_adressen: int = 0  # 0 = alle adressen (tot de Excel-limiet)
    klasse_a_aandeel: float = 0.10
    klasse_b_aandeel: float = 0.20

    cbs: dict = field(default_factory=dict)
    # Alleen de cache in data/cbs gebruiken, nooit het internet op (handig voor tests).
    cbs_offline: bool = False


def laad_config(pad=None):
    """Leest config.yaml (of het opgegeven pad) over de standaardwaarden heen."""
    pad = Path(pad) if pad else STANDAARD_CONFIG
    waarden = {}
    if pad.exists():
        waarden = yaml.safe_load(pad.read_text(encoding="utf-8")) or {}
    bekend = {f.name for f in fields(Config)}
    onbekend = set(waarden) - bekend
    if onbekend:
        raise ValueError(f"Onbekende instelling(en) in {pad}: {sorted(onbekend)}")
    return Config(**waarden)
