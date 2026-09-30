"""Het ensemble (logistic regression + RandomForest) en het out-of-fold scoren."""

import logging

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .kenmerken import met_regio

log = logging.getLogger(__name__)


def _voorbewerking(numeriek, categorisch, schalen):
    stappen = [("opvullen", SimpleImputer(strategy="median"))]
    if schalen:
        # Logistic regression heeft kenmerken op dezelfde schaal nodig: zonder schaling
        # domineert WOZ (~300.000) alle 0/1-kenmerken en convergeert het model slecht.
        stappen.append(("schalen", StandardScaler()))
    return ColumnTransformer([
        ("numeriek", Pipeline(stappen), numeriek),
        ("categorisch", Pipeline([
            ("opvullen", SimpleImputer(strategy="constant", fill_value="onbekend")),
            ("one_hot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), categorisch),
    ])


class Ensemble:
    """Gemiddelde kans van logistic regression en RandomForest. Beide krijgen extra gewicht
    op klanten (class_weight), omdat er maar weinig klanten zijn."""

    def __init__(self, numeriek, categorisch, cfg):
        self.numeriek, self.categorisch = list(numeriek), list(categorisch)
        self.kenmerken = self.numeriek + self.categorisch
        self.log_model = Pipeline([
            ("prep", _voorbewerking(numeriek, categorisch, schalen=True)),
            ("clf", LogisticRegression(max_iter=2000, C=cfg.lr_c, class_weight="balanced")),
        ])
        self.rf_model = Pipeline([
            ("prep", _voorbewerking(numeriek, categorisch, schalen=False)),
            ("clf", RandomForestClassifier(
                n_estimators=cfg.rf_bomen, max_depth=cfg.rf_max_diepte,
                min_samples_leaf=cfg.rf_min_blad, class_weight="balanced_subsample",
                random_state=cfg.random_state, n_jobs=-1,
            )),
        ])

    def fit(self, X, y):
        X = X[self.kenmerken]
        self.log_model.fit(X, y)
        self.rf_model.fit(X, y)
        return self

    def predict_proba(self, X):
        """Kans op klant (1-dimensionaal). Vooral bedoeld om te rangschikken."""
        X = X[self.kenmerken]
        return (self.log_model.predict_proba(X)[:, 1] + self.rf_model.predict_proba(X)[:, 1]) / 2


def train_en_voorspel(data, y, train_pos, test_pos, numeriek, categorisch, cfg):
    """Traint op train_pos (met buurteffect zonder spieken) en voorspelt test_pos."""
    fold_data = met_regio(data, y, train_pos, test_pos, cfg)
    y = np.asarray(y)
    model = Ensemble(numeriek, categorisch, cfg).fit(fold_data.iloc[train_pos], y[train_pos])
    return model, model.predict_proba(fold_data.iloc[test_pos]), fold_data


def scoor_out_of_fold(data, y, numeriek, categorisch, cfg):
    """Scoort elk adres met een model dat dat adres níet in de training had.

    De niet-klanten in de leadlijst zijn dezelfde adressen waarop het model leert (als
    "geen klant"). Zou je die met het model scoren dat ze al gezien heeft, dan drukt het
    model hun score omlaag. Out-of-fold scoren voorkomt dat."""
    y = np.asarray(y)
    kans = np.full(len(data), np.nan)
    cv = StratifiedKFold(n_splits=cfg.scoring_folds, shuffle=True, random_state=cfg.random_state)
    for fold, (train_pos, test_pos) in enumerate(cv.split(data, y), start=1):
        _, kans[test_pos], _ = train_en_voorspel(
            data, y, train_pos, test_pos, numeriek, categorisch, cfg
        )
        log.info("Scoren: deel %d/%d klaar.", fold, cfg.scoring_folds)
    return kans
