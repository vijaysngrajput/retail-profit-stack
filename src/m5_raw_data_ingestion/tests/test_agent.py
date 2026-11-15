"""LLD section 6: the agent records its tool calls and returns a verified answer."""

from helpers import (
    CHANGE_QUESTION,
    CHANGE_TOOL_CALLS,
    MAIN_QUESTION,
    MAIN_TOOL_CALLS,
    change_answer,
    main_answer,
    scripted_model,
)
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


def test_the_agent_is_given_seven_tools_or_six_without_the_run_tool():
    assert [tool.name for tool in make_tools([])][-1] == "compare_runs"
    names = [tool.name for tool in make_tools([], run_tool=False)]
    assert names == [
        "get_reporting_period",
        "get_metric_definition",
        "query_profit",
        "compare_profit",
        "get_evidence",
        "get_quality_flags",
    ]


# ---- New in milestone 4 ----


def test_a_run_records_its_steps_its_pipeline_run_and_sends_nothing_when_tracing_is_off():
    run = run_analyst(MAIN_QUESTION, model=scripted_model(MAIN_TOOL_CALLS, main_answer()))
    assert run.run_id == "RUN-0002" and run.trace_id == ""
    tool_steps = [step["name"] for step in run.steps if step["step"] == "tool"]
    assert tool_steps == [name for name, _ in MAIN_TOOL_CALLS]
    assert sum(step["step"] == "model" for step in run.steps) == len(MAIN_TOOL_CALLS) + 1
    assert run.cost == 0.0  # the fake model costs nothing


def test_a_change_between_runs_is_answered_from_compare_runs():
    run = run_analyst(CHANGE_QUESTION, model=scripted_model(CHANGE_TOOL_CALLS, change_answer()))
    assert run.verification.passed, run.verification.checks
    assert run.tool_log[0].name == "compare_runs"


def test_without_the_run_tool_a_call_to_it_is_not_possible():
    model = scripted_model(CHANGE_TOOL_CALLS, change_answer())
    run = run_analyst(CHANGE_QUESTION, model=model, run_tool=False)
    assert "compare_runs" not in [call.name for call in run.tool_log]


def test_code_fills_in_a_missing_run_id_but_a_wrong_one_still_fails():
    answer = main_answer()
    answer.run_id = None
    run = run_analyst(MAIN_QUESTION, model=scripted_model(MAIN_TOOL_CALLS, answer))
    assert run.answer.run_id == "RUN-0002" and run.verification.passed
    answer.run_id = "RUN-0001"
    run = run_analyst(MAIN_QUESTION, model=scripted_model(MAIN_TOOL_CALLS, answer))
    failed = [check.name for check in run.verification.checks if not check.passed]
    assert failed == ["run_cited"]
