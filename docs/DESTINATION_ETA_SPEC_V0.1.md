# EDpj Destination ETA Specification

**Version:** 0.1  
**Status:** Approved feature specification  
**Date:** 2026-09-06  
**Scope:** Station destination distance and approximate Supercruise ETA

## 1. Purpose

After an FSD jump, provide the commander with an approximate indication of:

- selected station distance from the system arrival point (`distanceToArrival`)
- approximate Supercruise travel time to that station
- selected station name and system

The feature is intended for **navigation assistance only**. It is not required to provide exact in-game ETA.

## 2. User experience

The user selects a destination station.

Example display:

```text
Destination: Hutton Orbital
System: Alpha Centauri
Distance: 6,397,000 Ls
Approx. SC ETA: ~1h 25m
```

After an FSD jump into the destination system, the application resolves the selected station and displays the static distance and approximate ETA.

If the destination cannot be resolved, the UI must show `NO_DATA` rather than inventing a value.

## 3. Distance source

### 3.1 Primary source

Use EDSM system/body/station data where available.

The relevant station/body record is expected to provide `distanceToArrival`. EDSM's public data model exposes this field for system bodies, and station data exposed through EDSM-compatible clients also contains `distanceToArrival`.

### 3.2 Secondary source

Spansh static dumps may be used as a secondary source for system/station/body resolution.

The source must be stored with the observation so that EDSM and Spansh data are not treated as indistinguishable authoritative values.

### 3.3 Meaning of distance

`distanceToArrival` is a static destination-distance value associated with the system arrival point. It is **not** the distance already travelled by the ship in Supercruise and must not be described as such.

## 4. Approximate ETA

### 4.1 Accuracy requirement

Exact ETA is explicitly out of scope.

The requirement is:

> Produce a useful practical approximation that allows the commander to know whether the trip is tens of seconds, a few minutes, tens of minutes, or exceptionally long.

### 4.2 Model

Initial ETA is a heuristic model derived from distance in Ls and known Supercruise travel behaviour.

The model must not assume constant maximum Supercruise speed because Supercruise acceleration/deceleration and stellar-body gravity effects make `distance / 2001c` an invalid practical ETA calculation.

Initial implementation should use a piecewise or log-distance interpolation over validated community/reference travel-time samples. The model must be isolated behind an estimator interface so that later calibration can replace the heuristic without changing the UI/API contract.

```text
station_distance_ls
        ↓
Supercruise ETA estimator
        ↓
eta_seconds
confidence = heuristic
```

### 4.3 Important separation from scoring

This ETA is a **navigation estimate** and must not automatically become an Action Horizon Estimator input.

Until the model is validated against the project's own telemetry, `eta_seconds` must not be used as a calibrated candidate-specific SC duration for Unified Scoring.

This preserves the current Phase 0-C decision that candidate-specific SC timing is `unavailable` for scoring.

## 5. Destination resolution

A destination is identified by at least:

```text
system name / system identifier
station name / station identifier
```

Preferred resolution order:

1. stable station/system identifier when available
2. exact system + station name
3. fallback external-data lookup

Ambiguous or stale destination records must produce `NO_DATA` / `STALE` rather than silently selecting a different station.

## 6. API contract

The destination ETA service should expose data equivalent to:

```json
{
  "system": "Alpha Centauri",
  "station": "Hutton Orbital",
  "distance_ls": 6397000,
  "eta_seconds": 5100,
  "eta_label": "~1h 25m",
  "distance_source": "edsm",
  "eta_source": "heuristic",
  "confidence": "low"
}
```

`eta_seconds` is nullable.

If distance is known but ETA cannot be estimated:

```json
{
  "distance_ls": 6397000,
  "eta_seconds": null,
  "eta_source": "unavailable"
}
```

## 7. Refresh policy

Static station distance does not need to be queried every frame.

- resolve/cache by system + station
- refresh when destination changes
- refresh when cached data is stale according to the external-source freshness policy
- do not poll EDSM continuously during flight

## 8. Validation

Before the feature is considered complete:

1. resolve a known station from EDSM
2. confirm `distanceToArrival` is populated and plausible
3. compare estimated ETA with multiple real Supercruise runs
4. include short, medium, and long distances
5. measure absolute and relative ETA error
6. ensure the feature remains labelled as approximate when error is large

A failed ETA validation must not invalidate the distance feature itself.

## 9. Non-goals

- exact real-time ETA matching the game's countdown
- automatic throttle control
- automatic FSD control
- automatic docking
- using the heuristic ETA as a scoring truth without validation
- maintaining a complete galaxy-wide station database locally

## 10. References

- EDSM system/body API and public data model
- Elite Dangerous Journal / Status data
- Elite Dangerous in-game Supercruise travel behaviour

The implementation must record the actual external source and model version used for every ETA result.
