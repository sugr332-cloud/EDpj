# EDpj Mission Board OCR — Effectiveness Test Specification

**Version:** 0.1  
**Status:** Design / implementation-phase specification  
**Date:** 2026-09-05  
**Related:** `SCREEN_CAPTURE_SPECIFICATION_V0.1.md`

## 1. Purpose

This document defines the effectiveness validation required before Mission Board OCR results may be connected to EDpj's money-making optimizer.

The objective is not merely to prove that OCR code runs. The objective is to determine, using real Mission Board observations and confirmed `MissionAccepted` Journal events, whether the feature is accurate and reliable enough for operational decision support.

OCR observations are `estimated`. `MissionAccepted` Journal data is the confirmation source (`measured`). No field is guessed when validation fails.

## 2. Test phases

```text
Phase A  Static OCR
Phase B  Scroll tracking / change detection
Phase C  Overlay
Phase D  Mission parsing accuracy
Phase E  Destination resolution
Phase F  MissionAccepted cross-validation
Phase G  Operational effectiveness validation
```

Phase G is mandatory. Passing unit/integration tests in A-F does not constitute effectiveness validation.

## 3. Functional accuracy tests

### 3.1 OCR / parser

Measure separately:

- mission type accuracy
- destination raw-text accuracy
- destination resolved accuracy
- commodity accuracy
- count accuracy
- reward accuracy
- faction accuracy
- complete-row extraction rate
- parse failure rate

Target initial gates:

- Reward accuracy: >= 98%
- Count accuracy: >= 98%
- Destination accuracy: >= 98%
- Major-field complete extraction: >= 95%

These are initial Go/No-Go gates and may only be changed by an explicit validation result; they must not be relaxed merely to obtain a PASS.

### 3.2 Fingerprint / deduplication

Verify:

- reward changes do not change fingerprint
- identical missions observed across frames are deduplicated
- different missions are not collapsed into one fingerprint
- repeated scrolling does not create duplicate registrations

Required:

- reward-independent fingerprint behavior: 100%
- duplicate registration caused by repeated observation: 0%

### 3.3 Boundary and motion behavior

Verify:

- partial top/bottom rows are excluded from parsing and translation
- original partial rows may be shown dimmed
- overlays are hidden while scrolling
- overlays return after scrolling stabilizes
- static frames produce zero OCR requests after the initial recognition
- recognition queue never retains more than one waiting request
- page transitions / low-correlation frames trigger recognition rather than stale overlay reuse

Required: no known data-integrity failure in the above cases.

## 4. MissionAccepted cross-validation

Collect real Mission Board observations and subsequently accept the corresponding missions.

For each matched mission, compare OCR against `MissionAccepted` Journal data:

```text
OCR estimated
    ↓
Mission candidate
    ↓
MissionAccepted Journal
    ↓
measured reference
```

Record at minimum:

- mission type match
- destination system match
- commodity match
- count match
- reward match
- faction match
- fingerprint match
- OCR timestamp
- acceptance timestamp
- parse/resolution status

Minimum validation sample: **100 matched missions**.

If fewer than 100 valid matched missions are available, the result is `INSUFFICIENT_SAMPLE`, not PASS.

## 5. Failure classification

Do not combine all failures into one OCR accuracy number. Each failure must be classified as one of:

```text
CAPTURE_FAILURE
OCR_FAILURE
NORMALIZATION_FAILURE
PARSER_FAILURE
DESTINATION_RESOLUTION_FAILURE
DEDUP_FAILURE
JOURNAL_MATCH_FAILURE
STALE_OBSERVATION
```

This prevents an apparently good aggregate accuracy from hiding a systematic failure in one pipeline stage.

## 6. Real-operation test

After functional validation, run the monitor during an actual Mission Board session.

Record:

- session duration
- frame count
- OCR count
- recognized rows
- unique missions
- duplicate registrations
- missed visible missions
- partial-row false positives
- overlay disappearance/reappearance during scrolling
- stale overlay occurrences
- application errors/crashes

The monitor must remain usable for a normal session without stale or misleading mission information becoming persistent.

## 7. Money-making effectiveness test

Only after MissionAccepted validation passes may the OCR output be evaluated as an input to money-making analysis.

For selected accepted missions, record:

```text
OCR observed reward
OCR observed count
resolved destination
estimated travel / execution cost
estimated Cr/h
        ↓
actual accepted mission
actual reward
actual completion result
actual observed time
actual effective Cr/h where measurable
```

Compare predicted and observed values. Report absolute and relative error.

The purpose is to determine whether OCR-derived mission candidates improve decision quality, not merely whether individual text fields are readable.

A money-making optimizer connection is **No-Go** if OCR errors can materially change mission ranking and the error rate has not been demonstrated to be operationally acceptable.

## 8. Go / No-Go decision

### GO

All of the following are required:

- minimum 100 matched missions
- Reward accuracy >= 98%
- Count accuracy >= 98%
- Destination accuracy >= 98%
- Major-field extraction >= 95%
- duplicate registration = 0%
- no partial-row false registration
- fingerprint reward-independence = 100%
- failure categories are measurable
- real-operation test completes without persistent stale/misleading overlays
- no unresolved systematic failure that materially affects mission ranking

### NO-GO

Any of the following results in NO-GO until corrected and retested:

- sample < 100 matched missions
- any critical field below its gate
- duplicate or stale mission data can materially affect ranking
- partial rows enter mission data
- destination resolution systematically produces wrong systems
- OCR/parser failures cannot be distinguished
- optimizer ranking can be materially changed by unvalidated OCR errors

## 9. Exit artifact

Phase G must produce a validation report containing:

```text
sample_count
field_accuracy
complete_extraction_rate
resolution_rate
duplicate_rate
failure_distribution
real_operation_metrics
money_effectiveness_metrics
Go/No-Go decision
```

The report must be retained so later OCR/normalization changes can be compared against the validated baseline.

## 10. Implementation phase integration

The implementation plan must include Phase G after A-F. Money-making optimizer integration is explicitly downstream of Phase G.

```text
A → B → C → D → E → F → G
                         │
                    GO / NO-GO
                         │
                         └── GO → Money Optimizer integration
```

No optimizer integration is considered complete before Phase G passes.
