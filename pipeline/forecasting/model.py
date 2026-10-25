"""
RideIntel XGBoost Demand Forecasting Model.

Implements regression model training, validation evaluation, prediction,
and artifact serialization.
"""

import os
import json
from typing import List, Dict, Optional, Tuple, Any
import numpy as np
import pandas as pd
import xgboost as xgb

from pipeline.forecasting.features import FEATURE_COLUMNS


DEFAULT_MODEL_PARAMS = {
    "n_estimators": 120,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "objective": "reg:squarederror",
    "n_jobs": 4
}


class DemandXGBoostModel:
    """
    XGBoost Regressor for forward 30-minute demand prediction per H3 zone.
    """

    def __init__(
        self,
        params: Optional[Dict[str, Any]] = None,
        feature_columns: Optional[List[str]] = None,
        model_name: str = "xgboost",
        model_version: str = "v1.0.0"
    ):
        self.params = params or DEFAULT_MODEL_PARAMS.copy()
        self.feature_columns = feature_columns or FEATURE_COLUMNS.copy()
        self.model_name = model_name
        self.model_version = model_version
        self._model: Optional[xgb.XGBRegressor] = None

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        verbose: bool = False
    ) -> "DemandXGBoostModel":
        """
        Fits XGBoost Regressor on training features and targets.
        If validation set is provided, monitors validation loss.
        """
        X_tr = X_train[self.feature_columns].copy()
        self._model = xgb.XGBRegressor(**self.params)

        if X_val is not None and y_val is not None:
            X_v = X_val[self.feature_columns].copy()
            self._model.fit(
                X_tr,
                y_train,
                eval_set=[(X_v, y_val)],
                verbose=verbose
            )
        else:
            self._model.fit(X_tr, y_train, verbose=verbose)

        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """
        Generates predictions for feature matrix X.
        Clips predictions to be non-negative (demand cannot be negative).
        """
        if self._model is None:
            raise RuntimeError("Model must be fitted before calling predict().")

        X_in = X[self.feature_columns].copy()
        raw_preds = self._model.predict(X_in)
        # Demand count is non-negative
        return np.clip(raw_preds, 0.0, None)

    def save_model(self, file_path: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Saves XGBoost model artifact in JSON format along with feature metadata.
        """
        if self._model is None:
            raise RuntimeError("Cannot save an unfitted model.")

        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        # Native XGBoost save
        self._model.save_model(file_path)

        # Save metadata sidecar
        meta_path = file_path + ".meta.json"
        meta = {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "feature_columns": self.feature_columns,
            "params": self.params,
            "custom_metadata": metadata or {}
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load_model(cls, file_path: str) -> "DemandXGBoostModel":
        """
        Loads XGBoost model from serialized JSON artifact.
        """
        meta_path = file_path + ".meta.json"
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            inst = cls(
                params=meta.get("params"),
                feature_columns=meta.get("feature_columns"),
                model_name=meta.get("model_name", "xgboost"),
                model_version=meta.get("model_version", "v1.0.0")
            )
        else:
            inst = cls()

        inst._model = xgb.XGBRegressor()
        inst._model.load_model(file_path)
        return inst

