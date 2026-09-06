# EDpj Phase — Destination Station Distance / Approximate ETA

**Version:** 0.1  
**Date:** 2026-09-06  
**Status:** Planned  
**Parent:** `DESTINATION_ETA_SPEC_V0.1.md`

## 1. Goal

Allow the user to select a station and receive, after the relevant FSD jump, the station's static distance and an approximate Supercruise travel time.

The feature is navigation assistance only. It does not control the ship and does not become a scoring truth before validation.

## 2. Phase placement

This feature is implemented after the existing Phase 0-C Action Horizon Foundation and before any future use of candidate-specific Supercruise duration in Unified Scoring.

It is split into the following gates so that external static data and ETA estimation are independently verifiable.

### Phase DETA-1 — Destination data ingestion

Tasks:

- add EDSM destination lookup client
- support system + station resolution
- store `distanceToArrival`
- record external source and observation/update timestamp
- add Spansh fallback path for static destination resolution
- implement `NO_DATA` / `STALE` handling
- add cache keyed by system + station

Exit criteria:

- known stations resolve correctly
- `distanceToArrival` is persisted without unit conversion errors
- ambiguous/stale records never silently resolve to another station
- repeated requests use cache and do not continuously poll EDSM

### Phase DETA-2 — Approximate ETA estimator

Tasks:

- define `SupercruiseEtaEstimator` interface
- implement initial distance-to-ETA heuristic
- use piecewise/log-distance interpolation rather than constant `distance / 2001c`
- return `eta_seconds`, `eta_label`, `eta_source`, and confidence
- keep ETA estimation independent from Action Horizon scoring

Exit criteria:

- short, medium, and long destination distances produce plausible estimates
- estimator returns `unavailable` rather than fabricating a value when distance is missing
- ETA is explicitly labelled heuristic/approximate
- estimator can be replaced by a calibrated model without changing the API contract

### Phase DETA-3 — In-game validation

Tasks:

- collect multiple real Supercruise runs
- include short, medium, and long distances
- compare predicted ETA against actual elapsed Supercruise time
- calculate absolute and relative error
- record cases where stellar-body gravity, route geometry, or other conditions cause large error
- determine whether the heuristic requires revised coefficients/buckets

Exit criteria:

- validation report exists
- error characteristics are documented
- distance feature passes independently even if ETA accuracy is insufficient
- model remains marked `heuristic` unless validation supports promotion

### Phase DETA-4 — Destination UI/API integration

Tasks:

- destination station selector
- destination summary
- display system / station / distance / approximate ETA
- expose `NO_DATA` / `STALE` states
- display source/confidence where useful for debugging

Exit criteria:

- user can select a station without manual coordinate entry
- after FSD jump, the selected destination resolves automatically
- distance and approximate ETA are shown without requiring game input automation
- failure of external lookup does not stop the main EDpj process

## 3. Scoring boundary

The feature **must not change Phase 0-C's current scoring contract**.

Until DETA-3 validation and a separate scoring decision are completed:

```text
Navigation ETA
    ↓
UI / navigation assistance only

Action Horizon Estimator
    ↓
supercruise = unavailable
```

A future phase may promote the validated ETA model to `estimated` for scoring, but that is a separate gate and must not happen implicitly.

## 4. Required tests

- EDSM station lookup success
- EDSM missing station
- stale cached station
- ambiguous station resolution
- Spansh fallback
- distance unit handling (Ls)
- ETA interpolation boundaries
- extremely short distance
- long-distance station
- missing distance
- ETA model replacement without API break
- FSD jump → destination resolution integration
- UI display of approximate ETA

## 5. Deliverables

- destination data adapter
- destination cache/storage
- `SupercruiseEtaEstimator`
- API response model
- CLI/debug output for station distance and ETA
- automated tests
- validation report from real Supercruise samples
- implementation notes documenting the exact EDSM/Spansh fields used
