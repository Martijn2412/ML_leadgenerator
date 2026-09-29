import pytest

from leadgenerator.config import Config
from leadgenerator.demodata import schrijf_demodata


@pytest.fixture
def cfg():
    return Config(
        cbs={}, cbs_offline=True, rf_bomen=30, binnen_folds=3, scoring_folds=3, cv_folds=3,
        groep_folds=3, k_waarden=[10, 50], permutatie_steekproef=500, backtest_jaren=2,
        excel_max_adressen=100,
    )


@pytest.fixture
def bestanden(tmp_path):
    return schrijf_demodata(tmp_path)
