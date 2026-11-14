"""LLD section 6: the agent records its tool calls and returns a verified answer."""

from helpers import MAIN_QUESTION, MAIN_TOOL_CALLS, main_answer, scripted_model
from retail_profit_stack.agent import make_tools, run_analyst
from retail_profit_stack.schemas import AnalystAnswer


def test_run_records_the_tool_log_and_verifies_the_answer():
    run = run_analyst(MAIN_QUESTION, model=scripted_model(MAIN_TOOL_CALLS, main_answer()))
    assert run.error is None
    assert [call.name for call in run.tool_log] == [name for name, _ in MAIN_TOOL_CALLS]
    assert run.answer.status == "answered"
    assert run.verification.passed
    assert run.tool_log[2].result["rows"][0]["entity_id"] == "P001"


def test_an_invented_figure_fails_verification():
    answer = main_answer()
    answer.figures[0].value = 9999.99
    run = run_analyst(MAIN_QUESTION, model=scripted_model(MAIN_TOOL_CALLS, answer))
    assert not run.verification.passed
    failed = [check.name for check in run.verification.checks if not check.passed]
    assert failed == ["figures_match_tools"]


def test_a_bad_tool_call_is_logged_as_an_error_and_the_run_continues():
    calls = [("query_profit", {"month": "2026-12", "group_by": "product"}), *MAIN_TOOL_CALLS]
    run = run_analyst(MAIN_QUESTION, model=scripted_model(calls, main_answer()))
    assert "Valid values" in run.tool_log[0].error and run.tool_log[0].result is None
    assert run.verification.passed


def test_a_declined_question_needs_no_tools():
    declined = AnalystAnswer(
        status="declined",
        headline="I can't forecast profit.",
        narrative="",
        decline_reason="Forecasts are outside the approved metrics.",
    )
    run = run_analyst("What will profit be next quarter?", model=scripted_model([], declined))
    assert run.tool_log == [] and run.verification.passed


def test_a_model_failure_is_reported_not_raised():
    run = run_analyst(
        MAIN_QUESTION, model=scripted_model([], main_answer()).__class__(messages=iter([]))
    )
    assert run.answer is None and run.error


def test_the_agent_is_given_exactly_the_six_tools():
    names = [tool.name for tool in make_tools([])]
    assert names == [
        "get_reporting_period",
        "get_metric_definition",
        "query_profit",
        "compare_profit",
        "get_evidence",
        "get_quality_flags",
    ]
