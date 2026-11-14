"""LLD sections 7 and 8: the rulebook, the desk, the reports, and the investigator agent."""

import json

import pytest
from langchain_core.messages import AIMessage

from helpers import ScriptedChatModel
from retail_profit_stack.config import RULEBOOK_FILE
from retail_profit_stack.quality.checks import CHECKS
from retail_profit_stack.quality.desk import (
    CAUSES,
    INVESTIGATION_CASES_FILE,
    build_desk,
    read_reports,
    score_reports,
)
from retail_profit_stack.quality.investigate import (
    HELPER_INSTRUCTIONS,
    MAIN_INSTRUCTIONS,
    build_investigator,
    describe_step,
    run_investigator,
)

GOOD_REPORT = {
    "finding_id": "QF-001",
    "likely_cause": "single_record_resent",
    "evidence": "Only one refund is duplicated.",
    "suggested_action": "Ask why the refund system sent it twice.",
}


def write_report(desk, finding_id, content):
    text = (
        content if isinstance(content, str) else json.dumps({**content, "finding_id": finding_id})
    )
    (desk / "reports" / f"{finding_id}.json").write_text(text, encoding="utf-8")


def test_the_rulebook_lists_every_check_and_every_cause():
    rulebook = RULEBOOK_FILE.read_text(encoding="utf-8")
    assert set(CAUSES) == {check.name for check in CHECKS}
    for check_name, causes in CAUSES.items():
        assert f"## {check_name}" in rulebook
        for cause in causes:
            assert f"`{cause}`" in rulebook, cause


def test_the_planted_causes_match_the_findings(calculated_tables):
    cases = json.loads(INVESTIGATION_CASES_FILE.read_text(encoding="utf-8"))
    findings = calculated_tables.findings
    key = ["finding_id", "check_name", "month", "product_id"]
    assert [[case[name] for name in key] for case in cases] == findings[key].values.tolist()
    for case in cases:
        assert case["planted_cause"] in CAUSES[case["check_name"]]


def test_the_desk_has_a_file_for_every_finding_with_its_related_records(tmp_path):
    desk = tmp_path / "desk"
    assert build_desk(desk) == [f"QF-00{number}" for number in range(1, 8)]
    assert sorted(path.name for path in desk.iterdir()) == ["findings", "reports", "rulebook.md"]
    assert list((desk / "reports").iterdir()) == []

    batch = json.loads((desk / "findings" / "QF-003.json").read_text(encoding="utf-8"))
    assert len(batch["bad_records"]) == 12
    assert {order["order_date"] for order in batch["related_records"]["orders"]} == {"2026-10-05"}

    no_cost = json.loads((desk / "findings" / "QF-004.json").read_text(encoding="utf-8"))
    costs = no_cost["related_records"]["product_costs_for_this_product"]
    assert [cost["month"] for cost in costs] == ["2026-09"]  # the sign of monthly_cost_not_updated

    for path in (desk / "findings").iterdir():
        assert "planted_cause" not in path.read_text(
            encoding="utf-8"
        )  # the answer is not on the desk


def test_the_cap_limits_how_many_findings_go_on_the_desk(tmp_path):
    desk = tmp_path / "desk"
    assert build_desk(desk, max_findings=2) == ["QF-001", "QF-002"]
    assert len(list((desk / "findings").iterdir())) == 2
    assert len(build_desk(desk)) == 7  # building again replaces the desk


def test_a_folder_that_is_not_a_desk_is_never_replaced(tmp_path):
    (tmp_path / "my_work.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ValueError, match="not a desk folder"):
        build_desk(tmp_path)
    assert (tmp_path / "my_work.txt").exists()


def test_reports_are_scored_right_wrong_or_left_for_a_person(tmp_path):
    desk = tmp_path / "desk"
    build_desk(desk)
    write_report(desk, "QF-001", GOOD_REPORT)  # right
    write_report(desk, "QF-002", {**GOOD_REPORT, "likely_cause": "batch_loaded_twice"})  # wrong
    write_report(desk, "QF-003", "I think it was a retry.")  # not JSON
    write_report(desk, "QF-004", {**GOOD_REPORT, "likely_cause": "cosmic_rays"})  # not in rulebook
    write_report(desk, "QF-005", {"likely_cause": "order_recorded_late"})  # fields missing
    write_report(desk, "QF-006", "[1, 2, 3]")  # JSON, but not a report
    # QF-007: no report at all

    scored = score_reports(read_reports(desk))
    assert dict(zip(scored["finding_id"], scored["result"], strict=True)) == {
        "QF-001": "right", "QF-002": "wrong", "QF-003": "left for a person",
        "QF-004": "left for a person", "QF-005": "left for a person",
        "QF-006": "left for a person", "QF-007": "left for a person",
    }  # fmt: skip
    problems = dict(zip(scored["finding_id"], scored["problem"], strict=True))
    assert problems["QF-003"] == "The report is not valid JSON."
    assert "cosmic_rays" in problems["QF-004"]
    assert problems["QF-007"] == "No report was written."
    assert problems["QF-001"] == ""


def test_the_instructions_keep_the_agent_to_notes():
    assert "reports/<finding id>.json" in MAIN_INSTRUCTIONS  # without this, helpers invent a format
    assert "cannot change the data or the outcome" in MAIN_INSTRUCTIONS
    for field in ("finding_id", "likely_cause", "evidence", "suggested_action"):
        assert field in HELPER_INSTRUCTIONS


def test_steps_are_described_in_one_line():
    todos = [{"content": "Investigate QF-001", "status": "pending"}]
    assert describe_step({"name": "write_todos", "args": {"todos": todos}}) == (
        "write_todos: Investigate QF-001 (pending)"
    )
    assert describe_step({"name": "read_file", "args": {"file_path": "/rulebook.md"}}) == (
        "read_file /rulebook.md"
    )
    assert (
        describe_step({"name": "task", "args": {"description": "QF-001\nmore"}}) == "task: QF-001"
    )


def scripted(*tool_calls):
    """A fake model that makes each tool call in turn, then says it has finished."""
    messages = [
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{number}"}])
        for number, (name, args) in enumerate(tool_calls)
    ]
    return ScriptedChatModel(messages=iter([*messages, AIMessage(content="All findings done.")]))


def test_the_agent_writes_on_the_desk_and_cannot_write_outside_it(tmp_path):
    desk = tmp_path / "desk"
    build_desk(desk, max_findings=1)
    report = json.dumps(GOOD_REPORT)
    model = scripted(
        ("write_file", {"file_path": "/reports/QF-001.json", "content": report}),
        ("write_file", {"file_path": "/../escaped.txt", "content": "outside the desk"}),
        ("execute", {"command": "touch escaped_by_command.txt"}),
    )
    run = run_investigator(build_investigator(model, desk), show=None)

    assert run.error == "" and run.final_message == "All findings done."
    assert run.steps[0] == "write_file /reports/QF-001.json" and run.model_calls == 4
    scored = score_reports(read_reports(desk))
    assert scored["result"].tolist() == ["right"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["desk"]  # nothing escaped
    assert not list(desk.rglob("escaped*"))


def test_a_model_failure_is_recorded_not_raised(tmp_path):
    desk = tmp_path / "desk"
    build_desk(desk, max_findings=1)
    model = ScriptedChatModel(messages=iter([]))  # fails on its first reply
    run = run_investigator(build_investigator(model, desk), show=None)
    assert run.error != "" and run.steps == []
