# EDpj Screen Capture / Mission OCR — Implementation Phases

**Version:** 0.1  
**Status:** Implementation plan  
**Date:** 2026-09-05  
**Specification:** `SCREEN_CAPTURE_SPECIFICATION_V0.1.md`  
**Effectiveness validation:** `docs/MISSION_OCR_EFFECTIVENESS_TEST_SPEC_V0.1.md`

## Phase A — Static OCR

- capture a Mission Board ROI
- preprocessing
- OCR
- line splitting / bounding boxes
- mission structure extraction
- fingerprint generation
- raw text retention

**Exit:** deterministic OCR/parser test fixtures pass.

## Phase B — Scroll Tracking / Change Detection

- 30fps target tracking loop
- vertical strip extraction
- phase correlation/template matching
- `dy` estimation
- change-triggered recognition
- one-deep recognition queue
- partial-row exclusion
- deduplication

**Exit:** static screen causes no repeated OCR; scrolling does not create stale or duplicate observations.

## Phase C — Overlay

- per-line opaque overlay
- click-through topmost window
- Windows layered/transparent window behavior
- hide during scrolling
- restore 100–200ms after scroll stop
- normalized-text translation cache

**Exit:** overlay remains aligned and never exceeds the source row; no input is captured by the overlay.

## Phase D — Mission Parsing Accuracy

- mission type
- destination raw text
- commodity
- count
- reward
- faction
- validation and parse-failure handling
- no guessing

**Exit:** parser accuracy meets the functional gates in the effectiveness specification on controlled fixtures.

## Phase E — Destination Resolution

- exact match
- edit-distance candidate handling
- ED prefix normalization
- digit-length filtering
- `unresolved` vs `resolved_no_data`
- unresolved destinations excluded from money-making distance/scoring

**Exit:** resolution tests pass and incorrect fuzzy matches are not silently confirmed.

## Phase F — MissionAccepted Cross-Validation

- correlate OCR observations with accepted missions
- compare OCR fields against `MissionAccepted`
- calculate field-level accuracy
- classify failures by pipeline stage
- collect at least 100 matched missions for effectiveness validation

**Exit:** validation dataset is complete enough for Phase G. F does not itself authorize optimizer integration.

## Phase G — Operational Effectiveness Validation

This is a mandatory implementation phase, not merely a documentation review.

Execute the tests defined in `docs/MISSION_OCR_EFFECTIVENESS_TEST_SPEC_V0.1.md`:

1. collect >=100 real matched missions
2. measure Reward / Count / Destination / major-field accuracy
3. measure extraction recall and resolution rate
4. measure duplicate registration and partial-row false positives
5. measure failure distribution by pipeline stage
6. perform a real Mission Board session test
7. measure stale-overlay and scroll behavior
8. evaluate whether OCR errors can materially alter mission ranking
9. where measurable, compare estimated Cr/h with actual mission outcome
10. issue an explicit GO / NO-GO decision

**Exit:** Phase G passes all mandatory gates. A failed gate requires correction and retest; thresholds must not be weakened merely to obtain PASS.

## Phase H — Money-Making Optimizer Integration

Only after Phase G = GO:

- expose validated mission candidates to EDpj
- use resolved destination/reward/count as optimizer inputs
- preserve estimated/measured provenance
- prevent unresolved or stale observations from entering ranking
- integrate mission ranking with existing money-making evaluation

**Exit:** optimizer can consume validated OCR data without bypassing confidence, freshness, resolution, or validation status.

## Phase ordering

```text
A Static OCR
    ↓
B Scroll / Change Detection
    ↓
C Overlay
    ↓
D Mission Parsing
    ↓
E Destination Resolution
    ↓
F Journal Cross-Validation
    ↓
G Effectiveness Validation
    ↓
   GO / NO-GO
    ↓ GO
H Money-Making Optimizer Integration
```

## Explicit policy

Passing automated tests in Phases A-F is not equivalent to demonstrating real-world usefulness. Phase G is the acceptance gate for operational validity. Phase H must not be treated as complete unless Phase G has produced a documented GO decision.
