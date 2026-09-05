from __future__ import annotations

from app.scoring.models import ActionCandidate, BioTarget, IncompleteCandidate, MiningTarget, RejectedCandidate
from app.scoring.pipeline import CandidatePipelineResult
from app.scoring.ranking import (
    ALL_BELOW_CONFIDENCE_REASON,
    ALTERNATIVES_LIMIT,
    MIN_ACTION_CONFIDENCE,
    NO_CANDIDATES_REASON,
    assemble_next_action_response,
    build_alternatives,
    build_score_rejections,
    rank_candidates,
    select_recommendation,
    target_id,
)


def _mining_target(**overrides) -> MiningTarget:
    defaults = dict(
        station_name="", system_name="Deciat", parent_body_name=None, station_type="Outpost",
        arrival_dist_from_star_ls=None,
    )
    defaults.update(overrides)
    return MiningTarget(**defaults)


def _candidate(
    action: str = "mining_sell",
    station_id: int | None = 1,
    system_name: str = "Deciat",
    expected_value: float = 1000.0,
    action_horizon_seconds: float = 3600.0,
    score_per_hour: float = 1000.0,
    confidence: float = 0.85,
) -> ActionCandidate:
    target = _mining_target(station_id=station_id, system_name=system_name)
    return ActionCandidate(
        action=action, target=target, expected_value=expected_value,
        action_horizon_seconds=action_horizon_seconds, horizon_components={}, horizon_complete=True,
        score_per_hour=score_per_hour, confidence=confidence, reason="",
    )


class TestTargetId:
    def test_mining_target_with_station_id(self):
        assert target_id("mining_sell", _mining_target(station_id=100)) == "mining_sell:station:100"

    def test_mining_target_without_station_id_is_a_ring(self):
        assert target_id("mining_continue", _mining_target(station_id=None, system_name="Deciat")) == (
            "mining_continue:ring:Deciat"
        )

    def test_bio_target(self):
        bio = BioTarget(body_name="Deciat 2 a", system_name="Deciat", body_suffix="a", arrival_dist_from_star_ls=None)
        assert target_id("bio_current_body", bio) == "bio_current_body:body:Deciat:Deciat 2 a"


class TestConfidenceThreshold:
    def test_excludes_below_threshold_without_reordering_the_rest(self):
        a = _candidate(station_id=1, score_per_hour=100.0, confidence=0.55)
        b = _candidate(station_id=2, score_per_hour=98.0, confidence=0.95)
        c = _candidate(station_id=3, score_per_hour=99.0, confidence=0.30)  # highest of the two survivors' neighbor

        eligible, below_threshold = rank_candidates([a, b, c])

        assert [cand.action_horizon_seconds for cand in eligible] == [3600.0, 3600.0]  # sanity: both present
        assert [id(cand) for cand in eligible] == [id(a), id(b)]  # a (100) still ranks above b (98)
        assert below_threshold == [c]

    def test_exactly_at_threshold_is_included(self):
        a = _candidate(confidence=MIN_ACTION_CONFIDENCE)
        eligible, below_threshold = rank_candidates([a])
        assert eligible == [a]
        assert below_threshold == []


class TestTieBreak:
    def test_ties_break_on_expected_value_then_horizon_then_target_id(self):
        # All three share score_per_hour -- expected_value must decide first.
        higher_value = _candidate(station_id=2, expected_value=2000.0, score_per_hour=100.0)
        lower_value = _candidate(station_id=1, expected_value=1000.0, score_per_hour=100.0)
        eligible, _ = rank_candidates([lower_value, higher_value])
        assert eligible == [higher_value, lower_value]

    def test_ties_on_score_and_value_break_on_shorter_horizon(self):
        shorter = _candidate(station_id=2, action_horizon_seconds=1800.0, score_per_hour=100.0, expected_value=1000.0)
        longer = _candidate(station_id=1, action_horizon_seconds=3600.0, score_per_hour=100.0, expected_value=1000.0)
        eligible, _ = rank_candidates([longer, shorter])
        assert eligible == [shorter, longer]

    def test_full_tie_breaks_on_target_id_deterministically(self):
        station_2 = _candidate(station_id=2)
        station_1 = _candidate(station_id=1)
        # Feed in "wrong" order -- target_id ("...:station:1" < "...:station:2") must still win.
        eligible, _ = rank_candidates([station_2, station_1])
        assert eligible == [station_1, station_2]
        # And it's stable regardless of input order.
        eligible_again, _ = rank_candidates([station_1, station_2])
        assert eligible_again == [station_1, station_2]


class TestSelectRecommendationAndAlternatives:
    def test_no_floor_beyond_confidence_gate(self):
        tiny = _candidate(score_per_hour=0.01, confidence=0.51)
        eligible, _ = rank_candidates([tiny])
        assert select_recommendation(eligible).action == "mining_sell"

    def test_empty_eligible_list_has_no_recommendation(self):
        assert select_recommendation([]) is None

    def test_alternatives_capped_at_limit_but_rejections_keep_everyone(self):
        candidates = [_candidate(station_id=i, score_per_hour=100.0 - i) for i in range(1, 7)]  # 6 candidates
        eligible, below_threshold = rank_candidates(candidates)

        alternatives = build_alternatives(eligible)
        assert len(alternatives) == ALTERNATIVES_LIMIT
        assert [a.action for a in alternatives] == ["mining_sell"] * ALTERNATIVES_LIMIT

        rejections = build_score_rejections(eligible, below_threshold)
        assert len(rejections) == 5  # every non-winner (6 candidates - 1 winner), not just the 3 alternatives
        assert all(r.reason_code == "lower_score" for r in rejections)
        assert all(r.comparison == eligible[0].score_per_hour for r in rejections)


class TestBelowThresholdRejection:
    def test_becomes_a_score_rejection_with_confidence_comparison(self):
        winner = _candidate(station_id=1, score_per_hour=100.0, confidence=0.85)
        loser = _candidate(station_id=2, score_per_hour=200.0, confidence=0.30)  # would win on score alone
        eligible, below_threshold = rank_candidates([winner, loser])

        assert eligible == [winner]  # loser excluded despite a higher raw score_per_hour
        rejections = build_score_rejections(eligible, below_threshold)
        assert len(rejections) == 1
        assert rejections[0].reason_code == "confidence_below_threshold"
        assert rejections[0].value == 0.30
        assert rejections[0].comparison == MIN_ACTION_CONFIDENCE


class TestAssembleNextActionResponse:
    def test_no_candidates_at_all(self):
        result = CandidatePipelineResult(complete=[], incomplete=[], rejected=[])
        response = assemble_next_action_response(result)
        assert response.recommendation is None
        assert response.next_action is None
        assert response.reason == NO_CANDIDATES_REASON

    def test_candidates_exist_but_all_below_confidence_threshold(self):
        low = _candidate(confidence=0.10)
        result = CandidatePipelineResult(complete=[low], incomplete=[], rejected=[])
        response = assemble_next_action_response(result)
        assert response.recommendation is None
        assert response.next_action is None
        assert response.reason == ALL_BELOW_CONFIDENCE_REASON
        assert len(response.rejected) == 1
        assert response.rejected[0].reason_code == "confidence_below_threshold"

    def test_incomplete_candidates_pass_through_untouched(self):
        incomplete = [
            IncompleteCandidate(
                action="bio_next_system", target=BioTarget(body_name="", system_name="X", body_suffix="",
                                                            arrival_dist_from_star_ls=None),
                breakdown={}, blocking_segments=["supercruise"], reason="...",
            )
        ]
        result = CandidatePipelineResult(complete=[], incomplete=incomplete, rejected=[])
        response = assemble_next_action_response(result)
        assert response.incomplete is incomplete

    def test_rejected_is_filter_rejections_then_score_rejections(self):
        filter_rejection = RejectedCandidate(
            category="filter", action="mining_start", target_id="mining_start:ring:X",
            reason_code="jump_range_insufficient",
        )
        winner = _candidate(station_id=1, score_per_hour=100.0)
        loser = _candidate(station_id=2, score_per_hour=50.0)
        result = CandidatePipelineResult(complete=[winner, loser], incomplete=[], rejected=[filter_rejection])

        response = assemble_next_action_response(result)

        assert response.rejected[0] is filter_rejection
        assert response.rejected[1].category == "score"
        assert response.rejected[1].reason_code == "lower_score"

    def test_recommendation_rejected_field_always_empty_in_phase_2_4(self):
        winner = _candidate(station_id=1, score_per_hour=100.0)
        loser = _candidate(station_id=2, score_per_hour=50.0)
        result = CandidatePipelineResult(complete=[winner, loser], incomplete=[], rejected=[])

        response = assemble_next_action_response(result)

        assert response.recommendation.rejected == []
        assert response.alternatives[0].rejected == []

    def test_full_success_path(self):
        winner = _candidate(station_id=1, score_per_hour=100.0, expected_value=44586.0)
        alt = _candidate(station_id=2, score_per_hour=90.0, expected_value=40000.0)
        result = CandidatePipelineResult(complete=[winner, alt], incomplete=[], rejected=[])

        response = assemble_next_action_response(result)

        assert response.next_action == "mining_sell"
        assert response.recommendation.score_per_hour == 100.0
        assert len(response.alternatives) == 1
        assert response.alternatives[0].score_per_hour == 90.0
        assert response.reason is None
