"""LLD section 9: the level of an answer, the cost of mistakes, kappa, and the run scores."""

import pandas as pd
import pytest

from retail_profit_stack.evaluation import CaseScore, load_cases
from retail_profit_stack.schemas import (
    AnalystAnswer,
    AnalystRun,
    CheckResult,
    Confidence,
    VerificationReport,
)
from retail_profit_stack.scoring import (
    MISTAKE_COSTS,
    answer_level,
    confusion_matrix,
    kappa,
    mistake,
    right_level,
    run_scores,
    score_row,
)


def case(case_id):
    return next(item for item in load_cases() if item.case_id == case_id)


def a_run(level=None, declined=False, answered=True) -> AnalystRun:
    """A run whose answer has the given confidence level, or is declined, or is missing."""
    run = AnalystRun(question="q", model="fake", cost=0.01, seconds=2.0)
    if not answered:
        return run
    run.answer = AnalystAnswer(
        status="declined" if declined else "answered",
        headline="h",
        narrative="n",
        confidence=Confidence(level=level, reasons=[]) if level else None,
    )
    run.verification = VerificationReport(passed=True, checks=[])
    return run


def a_score(*failed_checks) -> CaseScore:
    checks = [CheckResult(name=name, passed=False) for name in failed_checks]
    return CaseScore(case_id="E", passed=not failed_checks, checks=checks)


def test_right_level_comes_from_the_case():
    assert right_level(case("E6")) == "declined"
    assert right_level(case("E9")) == "medium"
    assert right_level(case("E3")) is None  # this question does not test the level


def test_answer_level():
    assert answer_level(a_run("low")) == "low"
    assert answer_level(a_run(declined=True)) == "declined"
    assert answer_level(a_run(answered=False)) == "declined"
    assert answer_level(a_run()) == "high"  # no word of doubt reads as fully trusted


@pytest.mark.parametrize(
    ("case_id", "run", "failed", "expected"),
    [
        ("E9", a_run("medium"), [], "none"),
        ("E6", a_run("high"), [], "answered_when_it_should_decline"),
        ("E9", a_run(declined=True), ["expected_figures"], "no_answer"),
        ("E9", a_run(answered=False), [], "no_answer"),
        ("E9", a_run("medium"), ["expected_figures"], "wrong_figure"),
        ("E9", a_run("high"), ["expected_confidence"], "too_confident"),
        ("E9", a_run("medium"), ["expected_flags"], "warning_left_out"),
        ("E9", a_run("low"), ["expected_confidence"], "not_confident_enough"),
        ("E9", a_run("medium"), ["expected_tools"], "other_check_failed"),
        ("E9", a_run("high"), ["expected_figures"], "wrong_figure"),  # the first match wins
    ],
)
def test_each_kind_of_mistake(case_id, run, failed, expected):
    assert mistake(case(case_id), run, a_score(*failed)) == expected


def test_an_answer_the_verifier_rejects_costs_what_a_missing_answer_costs():
    run = a_run("high")
    run.verification = VerificationReport(passed=False, checks=[])
    name = mistake(case("E9"), run, a_score("expected_figures", "figures_listed"))
    assert name == "stopped_by_verifier"
    assert MISTAKE_COSTS[name] == MISTAKE_COSTS["no_answer"] == 200


def test_too_confident_costs_more_than_not_confident_enough():
    assert MISTAKE_COSTS["too_confident"] > MISTAKE_COSTS["not_confident_enough"]
    row = score_row(case("E9"), a_run("high"), a_score("expected_confidence"))
    assert (row["mistake"], row["mistake_cost"], row["right"]) == ("too_confident", 5000, False)


def table_for(levels: dict[str, str]) -> pd.DataFrame:
    """A score table where each question got the given level."""
    rows = []
    for item in load_cases():
        level = levels.get(item.case_id, right_level(item) or "high")
        run = a_run(declined=True) if level == "declined" else a_run(level)
        failed = [] if level == (right_level(item) or level) else ["expected_confidence"]
        rows.append(score_row(item, run, a_score(*failed)))
    return pd.DataFrame(rows)


def test_a_perfect_analyst_has_kappa_one_and_no_cost():
    table = table_for({})
    scores = run_scores(table)
    assert kappa(table) == 1.0
    assert (scores["accuracy"], scores["level_accuracy"], scores["cost_of_mistakes"]) == (1, 1, 0)
    matrix = confusion_matrix(table)
    assert matrix.loc["high", "high"] == 4 and matrix.to_numpy().sum() == 10


def test_an_analyst_that_always_says_high_has_kappa_zero():
    always_high = table_for({item.case_id: "high" for item in load_cases()})
    assert kappa(always_high) == pytest.approx(0.0)
    scores = run_scores(always_high)
    assert scores["level_accuracy"] == 0.4  # right on the four questions whose level is high
    # two medium and two low questions are too confident; two declines were answered
    assert scores["cost_of_mistakes"] == 6 * 5000


def test_an_analyst_that_always_declines_is_cheap_but_useless():
    always_declines = table_for({item.case_id: "declined" for item in load_cases()})
    scores = run_scores(always_declines)
    assert scores["cost_of_mistakes"] == 12 * 200  # every answerable question goes to a person
    assert kappa(always_declines) == pytest.approx(0.0)
