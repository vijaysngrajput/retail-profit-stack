"""LLD section 9: the evaluation cases are correct and the runner scores answers correctly."""

from helpers import MAIN_TOOL_CALLS, main_answer, main_tool_log, scripted_model
from retail_profit_stack.agent import run_analyst
from retail_profit_stack.evaluation import (
    full_tool_log,
    load_cases,
    run_evaluation,
    score_case,
    summarise,
)
from retail_profit_stack.schemas import AnalystAnswer
from retail_profit_stack.verify import build_fact_index, same_value


def case(case_id):
    return next(item for item in load_cases() if item.case_id == case_id)


def test_seven_cases_three_of_them_tiny():
    assert [item.case_id for item in load_cases()] == ["E1", "E2", "E3", "E4", "E5", "E6", "E7"]
    assert [item.case_id for item in load_cases(tiny=True)] == ["E1", "E2", "E6"]


def test_expected_figures_agree_with_the_tools():
    facts = build_fact_index(full_tool_log())
    for item in load_cases():
        for expected in item.expected_figures:
            values = facts[(expected.metric, expected.kind, expected.month, expected.entity_id)]
            assert any(same_value(expected.value, value) for value in values), expected


def test_correct_answer_passes_the_main_case():
    score = score_case(case("E1"), main_answer(), main_tool_log())
    assert score.passed, [check for check in score.checks if not check.passed]


def test_the_same_answer_passes_against_the_full_tool_log():
    score = score_case(case("E1"), main_answer(), full_tool_log(), log_is_from_run=False)
    assert score.passed, [check for check in score.checks if not check.passed]
    assert "flags_mentioned" not in [check.name for check in score.checks]


def test_missing_expected_figure_fails_the_case():
    answer = main_answer()
    answer.figures = [figure for figure in answer.figures if figure.entity_id != "P008"]
    score = score_case(case("E1"), answer, main_tool_log())
    assert [check.name for check in score.checks if not check.passed] == ["expected_figures"]


def test_answering_a_question_that_should_be_declined_fails():
    score = score_case(case("E6"), main_answer(), main_tool_log())
    assert not score.passed
    assert not next(check for check in score.checks if check.name == "status_correct").passed


def test_no_answer_fails_with_the_error():
    score = score_case(case("E1"), None, [], error="TimeoutError: model did not reply")
    assert not score.passed and "TimeoutError" in score.checks[0].detail


def test_runner_and_summary_with_a_scripted_model():
    declined = AnalystAnswer(
        status="declined",
        headline="I can't forecast profit.",
        narrative="",
        decline_reason="Forecasts are outside the approved metrics.",
    )
    scripts = {
        case("E1").question: lambda: scripted_model(MAIN_TOOL_CALLS, main_answer()),
        case("E6").question: lambda: scripted_model([], declined),
    }
    cases = [case("E1"), case("E6")]
    scores = run_evaluation(
        lambda question: run_analyst(question, model=scripts[question]()), cases
    )
    assert [score.passed for score in scores] == [True, True]
    summary = summarise(scores)
    assert summary["cases_passed"] == "2 / 2" and summary["figures_match_tools"] == "2 / 2"
