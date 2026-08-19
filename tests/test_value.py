"""The business reading of a measurement: gap closed, cost per success, savings."""

import pytest

from prompt_playoff.domain import ModelProfile
from prompt_playoff.evals import Scorecard, _cost_usd
from prompt_playoff.value import HARDWARE, TOKENS, UNKNOWN, ValueCell, ValueReport, cost_basis


def card(quality, *, cost=None, latency=1.0, reliability=1.0):
    return Scorecard(
        quality=quality,
        reliability=reliability,
        contract_pass_rate=1.0,
        stability=1.0,
        mean_latency_seconds=latency,
        p95_latency_seconds=latency,
        mean_total_tokens=100,
        mean_prompt_tokens=60,
        mean_completion_tokens=40,
        mean_calls=1,
        mean_cost_usd=cost,
    )


def hosted(price=1.0):
    return ModelProfile(
        model_id="big-hosted",
        local=False,
        input_cost_per_million_usd=price,
        output_cost_per_million_usd=price,
    )


def self_hosted(rate=None):
    return ModelProfile(model_id="small-local", hardware_cost_per_hour_usd=rate)


def report(
    *, base=0.72, opt=0.89, ref: float | None = 0.92, costs=(0.0001, 0.0002, 0.0091), **kwargs
):
    base_cost, opt_cost, ref_cost = costs
    return ValueReport(
        dataset="support-tickets",
        examples=50,
        repeats=3,
        baseline=ValueCell.from_scorecard("baseline", self_hosted(1.2), card(base, cost=base_cost)),
        optimized=ValueCell.from_scorecard(
            "optimized", self_hosted(1.2), card(opt, cost=opt_cost), technique_id="few-shot"
        ),
        reference=(
            None
            if ref is None
            else ValueCell.from_scorecard("reference", hosted(), card(ref, cost=ref_cost))
        ),
        **kwargs,
    )


# --- cost, by whichever meter the model is on -------------------------------


def test_hosted_model_is_priced_per_token():
    cost = _cost_usd(1_000_000, 1_000_000, latency_seconds=99.0, model=hosted(price=2.0))
    assert cost == pytest.approx(4.0)


def test_self_hosted_model_is_priced_by_the_hour_it_occupied():
    cost = _cost_usd(1_000_000, 1_000_000, latency_seconds=3600.0, model=self_hosted(rate=1.5))
    assert cost == pytest.approx(1.5)


def test_token_rates_win_over_the_hourly_rate_when_both_are_set():
    both = ModelProfile(
        model_id="rented",
        input_cost_per_million_usd=1.0,
        output_cost_per_million_usd=1.0,
        hardware_cost_per_hour_usd=100.0,
    )
    assert _cost_usd(1_000_000, 0, latency_seconds=3600.0, model=both) == pytest.approx(1.0)


def test_a_model_with_no_rate_at_all_costs_unknown_not_zero():
    assert _cost_usd(1_000, 1_000, latency_seconds=1.0, model=self_hosted(rate=None)) is None
    assert cost_basis(self_hosted(rate=None)) == UNKNOWN
    assert cost_basis(self_hosted(rate=2.0)) == HARDWARE
    assert cost_basis(hosted()) == TOKENS


# --- gap closed --------------------------------------------------------------


def test_gap_closed_is_the_share_of_the_distance_the_prompt_covered():
    assert report(base=0.72, opt=0.89, ref=0.92).gap_closed == pytest.approx(0.85)


def test_gap_closed_is_absent_without_a_reference_run():
    card_ = report(ref=None)
    assert card_.gap_closed is None
    assert any("No reference model" in note for note in card_.warnings())


def test_gap_closed_is_absent_when_the_reference_is_no_better_than_the_baseline():
    """Dividing by a hair of headroom turns noise into a headline, so it refuses."""
    card_ = report(base=0.90, opt=0.93, ref=0.902)
    assert card_.gap_closed is None
    assert any("no real headroom" in note for note in card_.warnings())


def test_overtaking_the_reference_is_reported_as_measured_not_capped():
    assert report(base=0.70, opt=0.95, ref=0.90).gap_closed == pytest.approx(1.25)


def test_quality_gain_is_stated_in_percentage_points():
    assert report(base=0.72, opt=0.89).quality_gain_pp == pytest.approx(17.0)


# --- cost per success and savings -------------------------------------------


def test_cost_per_success_divides_by_the_answers_that_were_right():
    cell = ValueCell.from_scorecard("optimized", self_hosted(1.0), card(0.5, cost=0.001))
    assert cell.cost_per_success_usd == pytest.approx(0.002)


def test_cost_per_success_is_unknown_when_the_model_has_no_price():
    cell = ValueCell.from_scorecard("optimized", self_hosted(None), card(0.9, cost=None))
    assert cell.cost_per_success_usd is None


def test_monthly_saving_compares_the_two_bills_at_the_stated_volume():
    card_ = report(costs=(0.0001, 0.0002, 0.0091), tasks_per_month=100_000, target_quality=0.85)
    summary = card_.summary()
    assert summary["monthly_optimized_usd"] == pytest.approx(20.0)
    assert summary["monthly_reference_usd"] == pytest.approx(910.0)
    assert summary["monthly_saving_usd"] == pytest.approx(890.0)


def test_no_saving_is_offered_when_the_small_model_misses_the_target():
    """A cheaper bill bought with wrong answers is a worse service, not a saving."""
    card_ = report(opt=0.80, target_quality=0.90)
    assert card_.meets_target is False
    assert card_.monthly_saving_usd is None
    assert any("below the 0.90" in note for note in card_.warnings())


def test_cheapest_meeting_target_is_the_products_actual_answer():
    card_ = report(base=0.72, opt=0.89, ref=0.92, target_quality=0.85)
    cheapest = card_.cheapest_meeting_target
    assert cheapest is not None
    assert cheapest.role == "optimized"


def test_when_nothing_clears_the_bar_there_is_no_recommendation():
    assert report(base=0.5, opt=0.6, ref=0.7, target_quality=0.95).cheapest_meeting_target is None


def test_reference_that_is_the_same_model_as_the_baseline_is_called_out():
    same = report()
    same.reference = ValueCell.from_scorecard("reference", self_hosted(1.2), card(0.92, cost=0.001))
    assert any("against itself" in note for note in same.warnings())


def test_an_unpriced_cell_says_so_rather_than_reporting_a_free_run():
    card_ = report(costs=(None, None, 0.0091))
    summary = card_.summary()
    assert summary["optimized_cost_per_success_usd"] is None
    assert any("No price for" in note for note in summary["notes"])
