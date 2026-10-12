# Simulation assumptions

PlantShift is a student-scale operational discrete-event twin, not a physics-grade plant model.

## Time and demand

The simulator uses minutes internally and treats minute 0 as a 06:00 shift start. The default configurable daily demand profile is HIGH from 06:00–14:00 (minute 0–480), MEDIUM from 14:00–22:00 (480–960) and LOW from 22:00–06:00 (960–1440), with multipliers applied to the base demand rate. The same `demand_seed` can be reused across baseline and transformed cases.

## Maintenance

Scheduled maintenance is represented by explicit simulator events. `MAINTENANCE_NOW`, `NEXT_SHIFT`, and `LOW_DEMAND_WINDOW` place downtime at different timestamps. If a machine is busy when a planned window begins, maintenance starts when its current job releases; the machine then remains unavailable for the planned duration. `RUN_TO_FAILURE` is used only as the no-planned-maintenance comparison policy, not as a `maintenance_window` intervention. Condition-triggered maintenance is a separate `condition_maintenance` intervention driven by a bounded observable-sensor condition score (vibration, temperature, RPM, energy and load); hidden simulator `wear` is not read by the maintenance decision.

Maintenance-policy comparison holds IoT observability, duration, stochastic seed and demand seed constant so differences are attributable to maintenance policy rather than visibility.

No final KPI is directly edited to simulate a maintenance benefit.

## OEE

Availability = 1 - (planned downtime + unplanned downtime) / available machine-capacity minutes.

Performance = ideal busy-cycle minutes / actual busy minutes, capped at 1.

Quality = good finished units / (finished + scrap).

OEE = Availability × Performance × Quality.

## Energy

Per-machine kWh accumulates from modeled power and processing duration. Total energy and energy per finished unit are reported. No carbon/emissions claim is made because no emissions factor is assumed.
