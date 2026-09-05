"""Volatility classification evaluation — Phase 2-6B.

Spec (docs/PHASE_2_6B_VOLATILITY_EVALUATION_IMPLEMENTATION_BASELINE_V0.1.md).
Groups the ReplaySamples produced by app.backtest.replay (2-6A) by
`prediction.volatility_class` and checks whether the current
STABLE/MODERATE/VOLATILE thresholds
(app.market.predictability.STABLE_MEDIAN_PRICE_CHANGE/
MODERATE_MEDIAN_PRICE_CHANGE) actually correlate with forecast error --
without ever repositioning those thresholds itself. Threshold
repositioning is Phase 2-6E's job; this module only produces the
evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.backtest.replay import ReplaySample
from app.calibration.metrics import MAE_THRESHOLD
from app.market.predictability import VolatilityClass
from app.market.volatility import median_and_p95

# A separate concept from app.market.predictability.MIN_SAMPLES_FOR_CLASSIFICATION
# (which gates trusting a *single* volatility classification's price-pair
# count). This gates trusting a *median forecast error comparison across
# classes* -- a different question needing its own sample size. 30 is a
# common minimum-sample rule of thumb, not derived from this project's
# data; §3.1 of the spec revisits it once Phase 2-6E sees real sample
# counts.
MIN_SAMPLES_FOR_EVALUATION = 30


@dataclass(frozen=True)
class ClassForecastErrorStats:
    volatility_class: VolatilityClass
    sample_count: int  # ReplaySamples in this class with forecast_error is not None
    missing_actual_count: int  # ReplaySamples in this class with forecast_error is None
    median_forecast_error: float | None
    p95_forecast_error: float | None


def aggregate_by_volatility_class(samples: list[ReplaySample]) -> dict[VolatilityClass, ClassForecastErrorStats]:
    """Groups by `sample.prediction.volatility_class`. median/p95 reuse
    `app.market.volatility.median_and_p95` unchanged -- this is the same
    "distribution of independent relative errors" shape that function
    already serves for price/demand change ratios in
    app/market/predictability.py, not the "one predicted value vs many
    held-out actuals" shape of app.calibration.metrics.median_absolute_error
    (spec §2), so reusing the latter would misrepresent what's being
    measured here.

    A volatility_class that never appears in `samples` is simply absent
    from the returned dict -- never synthesized as a zero-sample entry,
    which would be indistinguishable from "this class occurred but had
    no error data" (spec §2)."""
    errors_by_class: dict[VolatilityClass, list[float]] = {}
    missing_by_class: dict[VolatilityClass, int] = {}
    for sample in samples:
        volatility_class = sample.prediction.volatility_class
        if sample.forecast_error is None:
            missing_by_class[volatility_class] = missing_by_class.get(volatility_class, 0) + 1
            errors_by_class.setdefault(volatility_class, [])
            continue
        errors_by_class.setdefault(volatility_class, []).append(sample.forecast_error)

    all_classes = set(errors_by_class) | set(missing_by_class)
    result: dict[VolatilityClass, ClassForecastErrorStats] = {}
    for volatility_class in all_classes:
        errors = errors_by_class.get(volatility_class, [])
        median_error, p95_error = median_and_p95(errors)
        result[volatility_class] = ClassForecastErrorStats(
            volatility_class=volatility_class,
            sample_count=len(errors),
            missing_actual_count=missing_by_class.get(volatility_class, 0),
            median_forecast_error=median_error,
            p95_forecast_error=p95_error,
        )
    return result


@dataclass(frozen=True)
class OrderingHypothesisResult:
    class_stats: dict[VolatilityClass, ClassForecastErrorStats]
    ordering_holds: bool | None
    stable_within_mae_threshold: bool | None
    volatile_exceeds_mae_threshold: bool | None


def _sufficient(stats: ClassForecastErrorStats | None) -> bool:
    return stats is not None and stats.sample_count >= MIN_SAMPLES_FOR_EVALUATION


def evaluate_ordering_hypothesis(
    class_stats: dict[VolatilityClass, ClassForecastErrorStats],
) -> OrderingHypothesisResult:
    """Checks docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md
    §4.2's ordering hypothesis (median(STABLE) < median(MODERATE) <
    median(VOLATILE)) and §9.2's MAE_THRESHOLD comparison
    (app.calibration.metrics.MAE_THRESHOLD, currently 0.20), against the
    CURRENT classify() thresholds only -- this function never tries an
    alternative threshold configuration (that repositioning is Phase
    2-6E's job, spec §0).

    Every field is None whenever the classes it depends on don't each
    have `sample_count >= MIN_SAMPLES_FOR_EVALUATION` -- "insufficient
    data to judge" must never collapse into `False` ("hypothesis
    rejected"), the same distinction
    docs/PHASE_2_6_HISTORICAL_BACKTEST_DESIGN_BASELINE_V0.1.md §9.1's
    validation_status pattern makes for calibration."""
    stable = class_stats.get("STABLE")
    moderate = class_stats.get("MODERATE")
    volatile = class_stats.get("VOLATILE")

    ordering_holds = None
    if _sufficient(stable) and _sufficient(moderate) and _sufficient(volatile):
        ordering_holds = stable.median_forecast_error < moderate.median_forecast_error < volatile.median_forecast_error

    stable_within_mae_threshold = None
    if _sufficient(stable):
        stable_within_mae_threshold = stable.median_forecast_error <= MAE_THRESHOLD

    volatile_exceeds_mae_threshold = None
    if _sufficient(volatile):
        volatile_exceeds_mae_threshold = volatile.median_forecast_error > MAE_THRESHOLD

    return OrderingHypothesisResult(
        class_stats=class_stats,
        ordering_holds=ordering_holds,
        stable_within_mae_threshold=stable_within_mae_threshold,
        volatile_exceeds_mae_threshold=volatile_exceeds_mae_threshold,
    )
