# ML methodology

PlantShift's failure-risk model is trained only on **SYNTHETIC** simulator telemetry. The simulator's internal `wear` / degradation state is ground truth and is used only to create/evaluate labels; it is not a deployable feature.

Observable model features are vibration, temperature, load, RPM, power, cycle count, rolling vibration mean/std, rolling temperature mean/trend and rolling energy mean. Feature engineering sorts by timestamp and groups rolling calculations by both `run_id` and `machine_id`, preventing independent simulation runs from sharing rolling state.

A row is labeled positive when a known injected failure occurs within the next five events for the same run and machine. Simulation runs are ordered by each `run_id`'s earliest UTC timestamp and **whole runs** are assigned approximately 60/10/30 to train/validation/test. No `run_id` appears in more than one partition. The classification threshold is selected only on validation runs.

`python -m scripts.train_ml` writes:

- `ml/artifacts/failure_risk.joblib`
- `ml/artifacts/evaluation.json`

The FastAPI lifespan loads the Joblib bundle once. `FailureRiskService` keeps only a bounded three-event observable history per machine and returns a probability, operational health band, model version and explanation. The digital twin consumes that output; it does not infer health from hidden `wear` when runtime ML is available.

Current executed metrics are stored in `ml/artifacts/evaluation.json`; no score is hardcoded into model code.

## Separation of maintenance policy and predictive ML

The simulator's condition-based maintenance policy is intentionally transparent: it keeps a bounded history of observable vibration, temperature, RPM, energy and load, normalizes those signals into a condition score, and triggers planned maintenance from that score. It does **not** read hidden `wear`. Runtime predictive maintenance remains a separate learned Random Forest path: observable telemetry → persisted model → digital-twin failure risk. Hidden `wear` remains simulator physics / synthetic ground truth only.
