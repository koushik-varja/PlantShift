# Brownfield current-state architecture

```mermaid
flowchart LR
  A[Legacy A / local signals] --> P[Paper/manual downtime]
  B[Legacy B / incompatible schema] --> P
  C[PLC-enabled C] --> X[Fragmented local data]
  D[Legacy D] --> P
  Q[Manual quality] --> X
  S[Excel scheduling] --> X
  X --> ERP[Batch ERP updates]
```

The starting plant deliberately lacks unified telemetry, shared machine-health inference and coordinated transformation planning. PlantShift's edge adapters model the normalization work required before legacy machines can participate in a canonical MQTT/event pipeline.
