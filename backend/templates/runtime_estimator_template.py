"""
Template for training and serving a runtime prediction model.

This file is intentionally standalone so it can be copied into an experiment
folder, notebook workflow, or future service module with minimal changes.

Expected training columns:
- runtime_seconds
- data_size_gb
- read_count_millions
- sample_count
- selected_tools
- input_formats
- pod_cpu_cores
- pod_memory_gb
- pod_ephemeral_storage_gb
- requested_threads
- estimated_flops
- cpu_core_seconds
- cloud_provider
- instance_family
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler


TARGET_COLUMN = "runtime_seconds"


@dataclass
class RuntimePredictionRequest:
    data_size_gb: float
    read_count_millions: float
    sample_count: int
    selected_tools: Sequence[str]
    input_formats: Sequence[str]
    pod_cpu_cores: float
    pod_memory_gb: float
    pod_ephemeral_storage_gb: float
    requested_threads: int
    cloud_provider: str
    instance_family: str
    estimated_flops: float = 0.0
    cpu_core_seconds: float = 0.0

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "data_size_gb": self.data_size_gb,
                    "read_count_millions": self.read_count_millions,
                    "sample_count": self.sample_count,
                    "selected_tools": ",".join(sorted(self.selected_tools)),
                    "input_formats": ",".join(sorted(self.input_formats)),
                    "pod_cpu_cores": self.pod_cpu_cores,
                    "pod_memory_gb": self.pod_memory_gb,
                    "pod_ephemeral_storage_gb": self.pod_ephemeral_storage_gb,
                    "requested_threads": self.requested_threads,
                    "estimated_flops": self.estimated_flops,
                    "cpu_core_seconds": self.cpu_core_seconds,
                    "cloud_provider": self.cloud_provider,
                    "instance_family": self.instance_family,
                }
            ]
        )


def _build_pipeline() -> Pipeline:
    numeric_features = [
        "data_size_gb",
        "read_count_millions",
        "sample_count",
        "pod_cpu_cores",
        "pod_memory_gb",
        "pod_ephemeral_storage_gb",
        "requested_threads",
        "estimated_flops",
        "cpu_core_seconds",
    ]
    categorical_features = [
        "selected_tools",
        "input_formats",
        "cloud_provider",
        "instance_family",
    ]

    numeric_pipeline = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical_pipeline = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="most_frequent")),
            ("one_hot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )

    features = ColumnTransformer(
        transformers=[
            ("numeric", numeric_pipeline, numeric_features),
            ("categorical", categorical_pipeline, categorical_features),
        ]
    )

    model = HistGradientBoostingRegressor(
        loss="absolute_error",
        learning_rate=0.05,
        max_depth=8,
        max_iter=300,
        random_state=42,
    )

    return Pipeline(
        steps=[
            ("features", features),
            # Predict log-runtime to reduce sensitivity to very long runs.
            ("target_model", model),
        ]
    )


def train_runtime_model(training_frame: pd.DataFrame) -> tuple[Pipeline, dict[str, float]]:
    frame = training_frame.copy()
    required_columns = {
        TARGET_COLUMN,
        "data_size_gb",
        "read_count_millions",
        "sample_count",
        "selected_tools",
        "input_formats",
        "pod_cpu_cores",
        "pod_memory_gb",
        "pod_ephemeral_storage_gb",
        "requested_threads",
        "estimated_flops",
        "cpu_core_seconds",
        "cloud_provider",
        "instance_family",
    }

    missing_columns = sorted(required_columns - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Training data is missing required columns: {missing_columns}")

    X = frame.drop(columns=[TARGET_COLUMN])
    y = np.log1p(frame[TARGET_COLUMN].astype(float))

    X_train, X_valid, y_train, y_valid = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42,
    )

    pipeline = _build_pipeline()
    pipeline.fit(X_train, y_train)

    valid_predictions = np.expm1(pipeline.predict(X_valid))
    valid_actuals = np.expm1(y_valid)

    metrics = {
        "mae_seconds": float(mean_absolute_error(valid_actuals, valid_predictions)),
        "mape": float(mean_absolute_percentage_error(valid_actuals, valid_predictions)),
        "r2": float(r2_score(valid_actuals, valid_predictions)),
    }
    return pipeline, metrics


def predict_runtime_seconds(model: Pipeline, request: RuntimePredictionRequest) -> float:
    prediction = model.predict(request.to_frame())[0]
    return float(np.expm1(prediction))


def save_model(model: Pipeline, output_path: str | Path) -> None:
    joblib.dump(model, output_path)


def load_model(model_path: str | Path) -> Pipeline:
    return joblib.load(model_path)


if __name__ == "__main__":
    example_rows = pd.DataFrame(
        [
            {
                "runtime_seconds": 1800,
                "data_size_gb": 4.2,
                "read_count_millions": 35,
                "sample_count": 1,
                "selected_tools": "FASTQC,SPADES",
                "input_formats": "fastq",
                "pod_cpu_cores": 4,
                "pod_memory_gb": 16,
                "pod_ephemeral_storage_gb": 40,
                "requested_threads": 4,
                "estimated_flops": 2.88e13,
                "cpu_core_seconds": 7200,
                "cloud_provider": "local",
                "instance_family": "docker-desktop",
            },
            {
                "runtime_seconds": 4200,
                "data_size_gb": 12.5,
                "read_count_millions": 90,
                "sample_count": 1,
                "selected_tools": "FASTQC,SPADES,QUAST",
                "input_formats": "fastq,fasta",
                "pod_cpu_cores": 8,
                "pod_memory_gb": 32,
                "pod_ephemeral_storage_gb": 120,
                "requested_threads": 8,
                "estimated_flops": 1.344e14,
                "cpu_core_seconds": 33600,
                "cloud_provider": "aws",
                "instance_family": "c6i",
            },
            {
                "runtime_seconds": 900,
                "data_size_gb": 1.8,
                "read_count_millions": 12,
                "sample_count": 1,
                "selected_tools": "FASTQC",
                "input_formats": "fastq",
                "pod_cpu_cores": 2,
                "pod_memory_gb": 8,
                "pod_ephemeral_storage_gb": 20,
                "requested_threads": 2,
                "estimated_flops": 7.2e12,
                "cpu_core_seconds": 1800,
                "cloud_provider": "local",
                "instance_family": "docker-desktop",
            },
            {
                "runtime_seconds": 2500,
                "data_size_gb": 6.4,
                "read_count_millions": 48,
                "sample_count": 1,
                "selected_tools": "FASTQC,GENOMESCOPE2",
                "input_formats": "fastq",
                "pod_cpu_cores": 4,
                "pod_memory_gb": 12,
                "pod_ephemeral_storage_gb": 40,
                "requested_threads": 4,
                "estimated_flops": 4.0e13,
                "cpu_core_seconds": 10000,
                "cloud_provider": "gcp",
                "instance_family": "e2-standard",
            },
            {
                "runtime_seconds": 5600,
                "data_size_gb": 15.0,
                "read_count_millions": 120,
                "sample_count": 2,
                "selected_tools": "FASTQC,SPADES,QUAST",
                "input_formats": "fastq,fasta",
                "pod_cpu_cores": 8,
                "pod_memory_gb": 32,
                "pod_ephemeral_storage_gb": 150,
                "requested_threads": 8,
                "estimated_flops": 1.792e14,
                "cpu_core_seconds": 44800,
                "cloud_provider": "azure",
                "instance_family": "dsv5",
            },
        ]
    )

    trained_model, validation_metrics = train_runtime_model(example_rows)
    print("Validation metrics:", validation_metrics)

    example_request = RuntimePredictionRequest(
        data_size_gb=8.5,
        read_count_millions=60,
        sample_count=1,
        selected_tools=["FASTQC", "SPADES", "QUAST"],
        input_formats=["fastq", "fasta"],
        pod_cpu_cores=8,
        pod_memory_gb=24,
        pod_ephemeral_storage_gb=100,
        requested_threads=8,
        cloud_provider="aws",
        instance_family="c6i",
    )
    print("Predicted runtime (seconds):", predict_runtime_seconds(trained_model, example_request))
