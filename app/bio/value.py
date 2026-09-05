"""Bio value calibration — Phase 3 V1.

Spec (docs/PHASE_3_BIO_VALUE_MODEL_V1_DESIGN_BASELINE_V0.1.md §3). Pure
read-only calibration, same shape as app/mining/price.py/
app/mining/yield_model.py -- no session mutation.

The value this module produces is NOT a per-species price.
`SellOrganicData` sale events and `ScanOrganic` (Analyse) scan events
have no field linking a specific sale to a specific scan, so
`total_organic_sale_credits() / total_analysed_sample_count()` cannot
be read as "the price of one species" -- it is this player's own
historical bio revenue realized per completed analysis, applied
prospectively as an estimate. Naming and documentation throughout this
module deliberately avoid "species value"/"unit price" language for
this reason.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.bio.conditions import ANALYSE_SCAN_TYPE, SCAN_ORGANIC, SELL_ORGANIC_DATA
from app.db.models.journal import JournalEvent


def total_organic_sale_credits(session: Session) -> int:
    """Sums Value + Bonus across every BioData entry of every
    SellOrganicData event in this player's whole journal history. FD
    bonus is included, not separated out -- V1 does not implement
    expected_value_best (spec §5), so this is simply "what this player
    has actually realized on average", carrying whatever mix of FD luck
    occurred historically."""
    total = 0
    for event in session.query(JournalEvent).filter_by(event_type=SELL_ORGANIC_DATA).all():
        for entry in event.payload.get("BioData", []):
            total += entry.get("Value", 0) + entry.get("Bonus", 0)
    return total


def total_analysed_sample_count(session: Session) -> int:
    """Count of ScanType == Analyse (species-completing) ScanOrganic
    events across the WHOLE journal history. Distinct from
    app.bio.conditions.detect_unsold_bio_count(), which is deliberately
    scoped to "since the last sale" -- that answers a different
    question (how many completed-but-unsold samples exist right now)
    than this one (how many completed samples has this player ever
    analysed, as the calibration denominator)."""
    return sum(
        1
        for event in session.query(JournalEvent).filter_by(event_type=SCAN_ORGANIC).all()
        if event.payload.get("ScanType") == ANALYSE_SCAN_TYPE
    )


def calibrate_expected_value_per_signal(session: Session) -> float | None:
    """None when there is no calibration data yet -- never fabricated as
    0 or any other guess (same principle as app.calibration's
    validation_status "insufficient"). Two independent conditions must
    both hold, since either one missing makes the ratio meaningless
    rather than merely small:

      - at least one analysed scan exists (the denominator must be
        non-zero to divide at all);
      - at least one SellOrganicData event exists (without any sale
        history, `total_organic_sale_credits()` being 0 means "we have
        never sold anything", not "organics are worth 0 credits" --
        collapsing that into a computed 0.0 would silently make every
        Bio candidate look worthless instead of reporting "insufficient
        sell history").

    The two counts being divided are not guaranteed to correspond 1:1
    (module docstring) -- this function makes no attempt to pair a sale
    with a scan; it is a simple ratio over two independently-counted
    totals, and remains correct even when SellOrganicData's event count
    differs from ScanOrganic(Analyse)'s."""
    denominator = total_analysed_sample_count(session)
    if denominator == 0:
        return None
    if session.query(JournalEvent).filter_by(event_type=SELL_ORGANIC_DATA).first() is None:
        return None
    return total_organic_sale_credits(session) / denominator
