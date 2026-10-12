from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

_ml_module = importlib.import_module("ml")
load_model = _ml_module.load_model
train_and_evaluate = _ml_module.train_and_evaluate

MODEL_NAME = "failure_risk.joblib"
EVALUATION_NAME = "evaluation.json"
REQUIRED_EVALUATION_KEYS = {
    "precision",
    "recall",
    "f1",
    "roc_auc",
    "pr_auc",
    "features",
    "model_version",
}


def artifacts_ready(output_dir: str | Path) -> bool:
    """Return True only when both the model and usable evaluation metadata exist."""
    out = Path(output_dir)
    model_path = out / MODEL_NAME
    evaluation_path = out / EVALUATION_NAME

    if not model_path.is_file() or not evaluation_path.is_file():
        return False

    try:
        metadata = json.loads(evaluation_path.read_text(encoding="utf-8"))
        bundle = load_model(model_path)
    except Exception:
        return False

    if not REQUIRED_EVALUATION_KEYS.issubset(metadata):
        return False

    if not isinstance(bundle, dict):
        return False

    required_bundle_keys = {"model", "features", "threshold", "model_version"}
    return required_bundle_keys.issubset(bundle)


def ensure_ml_artifacts(
    output_dir: str | Path = "ml/artifacts",
    *,
    if_missing: bool = False,
    force: bool = False,
    runs: int = 18,
    duration_hours: float = 12.0,
) -> dict[str, Any]:
    """Train once when required; preserve the historical train-now behavior without flags."""
    out = Path(output_dir)

    if if_missing and not force and artifacts_ready(out):
        metadata = json.loads((out / EVALUATION_NAME).read_text(encoding="utf-8"))
        return {
            "status": "skipped_existing",
            "model_path": str(out / MODEL_NAME),
            "evaluation_path": str(out / EVALUATION_NAME),
            "model_version": metadata.get("model_version"),
        }

    metrics = train_and_evaluate(
        out,
        runs=runs,
        duration_hours=duration_hours,
    )

    return {
        "status": "trained",
        "model_path": str(out / MODEL_NAME),
        "evaluation_path": str(out / EVALUATION_NAME),
        "metrics": metrics,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train PlantShift synthetic failure-risk model.")
    parser.add_argument(
        "--if-missing",
        action="store_true",
        help=("Train only when the model or required evaluation metadata is missing/invalid."),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Retrain even when artifacts already exist.",
    )
    parser.add_argument(
        "--output-dir",
        default="ml/artifacts",
        help="Artifact directory (default: ml/artifacts).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=18,
        help="Synthetic training simulation runs.",
    )
    parser.add_argument(
        "--duration-hours",
        type=float,
        default=12.0,
        help="Hours per synthetic training run.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = ensure_ml_artifacts(
        args.output_dir,
        if_missing=args.if_missing,
        force=args.force,
        runs=args.runs,
        duration_hours=args.duration_hours,
    )
    print(json.dumps(result, indent=2))
