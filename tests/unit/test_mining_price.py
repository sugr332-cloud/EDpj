from __future__ import annotations

import pytest

from app.mining.price import demand_penalty, effective_price


def test_low_ratio_has_no_penalty():
    assert demand_penalty(cargo=10, demand=1000) == pytest.approx(1.00)


def test_ratio_at_low_boundary_has_no_penalty():
    assert demand_penalty(cargo=25, demand=100) == pytest.approx(1.00)  # r = 0.25 exactly


def test_high_ratio_has_max_penalty():
    assert demand_penalty(cargo=100, demand=100) == pytest.approx(0.45)  # r = 1.0


def test_ratio_at_high_boundary_has_max_penalty():
    assert demand_penalty(cargo=80, demand=100) == pytest.approx(0.45)  # r = 0.80 exactly


def test_midpoint_ratio_interpolates_linearly():
    assert demand_penalty(cargo=52.5, demand=100) == pytest.approx(0.725)  # r = 0.525, midpoint of [0.25, 0.80]


def test_effective_price_applies_penalty_to_listed_price():
    assert effective_price(listed_price=1000, cargo=10, demand=1000) == pytest.approx(1000.0)
    assert effective_price(listed_price=1000, cargo=100, demand=100) == pytest.approx(450.0)
