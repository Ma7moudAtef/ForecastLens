"""M7: every selection and rejection produces planner-readable language."""
from core.explain import engine as ex

META = {"n_reliable": 18, "trend_strength": 0.1, "seasonality_strength": 0.1,
        "is_orphan": 0, "mode": "relative", "mode_source": "inferred",
        "line": "a", "output_type": "x"}


def _sel(**kw):
    base = {"model_name": "SES", "window": None, "mase": 0.8, "n_origins": 8,
            "reason_code": "competition_winner", "route": "compete",
            "winner_explain": "Stable consumption with no clear direction."}
    base.update(kw)
    return base


def test_competition_winner_text_mentions_windows_and_history():
    text = ex.selection_reason(_sel(), META)
    assert "8 test windows" in text
    assert "18 periods" in text
    assert "MASE" not in text


def test_cold_start_standard_rate_text():
    text = ex.selection_reason(
        _sel(model_name="StandardRateAnchor",
             reason_code="cold_start_standard_rate"),
        {**META, "n_reliable": 2})
    assert "standard" in text.lower()
    assert "2 period" in text


def test_cold_start_category_prior_text():
    text = ex.selection_reason(
        _sel(model_name="CategoryPrior", reason_code="cold_start_category_prior",
             winner_explain="Using the average behaviour of 14 similar "
                            "item(s) in category 'x'."),
        {**META, "n_reliable": 3})
    assert "14 similar item" in text
    assert "3 period" in text
    assert text.count("period(s)") == 1     # history stated exactly once


def test_routed_texts():
    assert "routed" in ex.selection_reason(
        _sel(model_name="SBA", reason_code="routed_sba"), META)
    tsb = ex.selection_reason(
        _sel(model_name="TSB", reason_code="routed_tsb_obsolescence"), META)
    assert "decays toward zero" in tsb


def test_override_text():
    text = ex.selection_reason(
        _sel(reason_code="planner_override", model_name="Drift"), META)
    assert "planner override" in text.lower()
    assert "locked" in text


def test_rejection_failed_and_skipped():
    failed = ex.rejection_reason(
        {"model_name": "HoltWinters", "status": "failed"}, {"mase": 0.5}, META)
    assert "disqualified" in failed
    skipped = ex.rejection_reason(
        {"model_name": "Theta", "status": "skipped"}, {"mase": 0.5}, META)
    assert "too little history" in skipped


def test_rejection_worse_error_with_behaviour_hint():
    text = ex.rejection_reason(
        {"model_name": "Holt", "status": "ok", "mase": 1.0},
        {"mase": 0.5}, META)   # trend model on a trendless series
    assert "100% higher" in text
    assert "does not sustain" in text

    text2 = ex.rejection_reason(
        {"model_name": "Mean", "status": "ok", "mase": 0.9},
        {"mase": 0.5}, {**META, "trend_strength": 0.9})
    assert "could not track" in text2


def test_tiebreak_loser_text():
    text = ex.rejection_reason(
        {"model_name": "SES", "status": "ok", "mase": 0.5},
        {"mase": 0.5}, META)
    assert "tie-break" in text


def test_special_case_caveats():
    orphan = ex.orphan_caveat("a", "C")
    assert "denominator does not exist" in orphan
    assert "line 'a'" in orphan
    assert "output 'C'" in orphan

    declared = ex.declared_mode_note("absolute", "declared_ui")
    assert "planner override" in declared

    low = ex.low_driver_note(3)
    assert "3 period" in low

    bias = ex.smoothing_bias_caveat(0.97)
    assert "0.97" in bias and "cross-check" in bias
