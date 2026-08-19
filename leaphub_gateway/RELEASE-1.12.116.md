# Leap Hub Gateway 1.12.116 - Window Diagnostics Per Vehicle

Published 1.12.115 base: `ee77a67d3a1db6b1893a5b0940ca1bdfe6444635`.
D1 merged into main: `6a601c35212e460d9ae1b8e7eda76d98614eb93c`.
D1 feature head: `533ee61fe800bbbe43b0770d66b4590f92f4c562`.
Functional PR: #17.

## Goal

Separate window telemetry diagnostics by vehicle so field logs can attribute
each snapshot to the correct vehicle/account without exposing the raw vehicle
identifier.

## Functional change

- `WINDOW_TELEMETRY_DIAG` includes `vehicle=veh_<hash>`;
- the token is stable for the same identifier and does not log the raw value;
- diagnostic deduplication is per vehicle instead of global;
- legacy `log_window_telemetry_diag(positions, states, raw)` remains supported;
- production passes `vehicle_key=remote_id or vin`;
- the 1.12.115 proximity regression test now derives runtime release metadata
  from `RELEASE_TARGET` instead of pinning the previous version number. Its
  proximity and physical-safety assertions are unchanged.

## Frozen contracts

- physical command payloads and native C10 window scale;
- ACK_FIRST and SAFE_STATE_RETRY;
- climate_off transmission ceiling;
- mechanical serialization fence for windows/sunshade;
- FAST confirmation behavior and cadence;
- realtime proximity safety from 1.12.115;
- Trips, OCPP, maintenance and SQLite writer;
- one Leapmotor client/session architecture.

## Publication

This release uses the existing two-phase flow:

1. RELEASE_TARGET becomes 1.12.116 while config.yaml remains 1.12.115.
2. GitHub Actions validates the staged repository.
3. GitHub Actions builds ghcr.io/jorgemartim/leaphub-gateway:1.12.116.
4. The exact image is smoke-tested.
5. Anonymous GHCR access is verified.
6. Only then publish_release.py promotes config.yaml to 1.12.116 and commits
   the [gateway-published] metadata.
7. Home Assistant can then detect the 1.12.116 update.

## Field goal after installation

Repeat window/sunshade tests and collect the new `vehicle=veh_*` diagnostics.
Measure library dispatch duration separately from the time until physical state
confirmation. This release does not accelerate or change the vehicle mechanism.
