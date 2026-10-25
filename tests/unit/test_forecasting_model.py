"""
Unit tests for XGBoost demand forecasting model.
"""

import os
import pytest
import numpy as np
import pandas as pd

from pipeline.forecasting.model import DemandXGBoostModel
from pipeline.forecasting.features import FEATURE_COLUMNS


def test_xgboost_fit_and_predict(tmp_path):
    np.random.seed(42)
    n_samples = 100

    # Synthetic features
    data = {col: np.random.randn(n_samples) for col in FEATURE_COLUMNS}
    X = pd.DataFrame(data)
    # Synthetic target correlated with lag_15m
    y = np.maximum(0.0, X["lag_15m"] * 2.5 + np.random.randn(n_samples) * 0.5)

    model = DemandXGBoostModel(params={"n_estimators": 10, "max_depth": 3, "random_state": 42})
    model.fit(X, y)

    preds = model.predict(X)
    assert len(preds) == n_samples
    assert (preds >= 0.0).all()  # Non-negativity assertion

    # Test serialization
    save_file = str(tmp_path / "model.json")
    model.save_model(save_file, metadata={"test": "fixture"})
    assert os.path.exists(save_file)
    assert os.path.exists(save_file + ".meta.json")

    # Test loading
    loaded_model = DemandXGBoostModel.load_model(save_file)
    loaded_preds = loaded_model.predict(X)
    np.testing.assert_allclose(preds, loaded_preds, rtol=1e-5)


def test_xgboost_unfitted_error():
    model = DemandXGBoostModel()
    with pytest.raises(RuntimeError):
        model.predict(pd.DataFrame({"lag_15m": [1.0]}))

