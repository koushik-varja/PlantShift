from ml.training import FEATURES, build_training_frame


def test_ml_features_and_labels_are_constructed_from_simulator():
    df = build_training_frame(runs=3, duration_hours=3)
    assert set(FEATURES).issubset(df.columns)
    assert "future_failure" in df.columns
    assert set(df["future_failure"].unique()).issubset({0, 1})
