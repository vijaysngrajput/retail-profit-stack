"""Run the evaluation set: known questions with known correct answers.

Implements LLD section 9 (Evaluation set). A case passes only when the answer
has the expected content and also passes every verifier check.
"""

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from retail_profit_stack import tools
from retail_profit_stack.config import EVALS_DIR
from retail_profit_stack.schemas import (
    ALL_TERMS,
    AnalystAnswer,
    AnalystRun,
    CheckResult,
    ToolCall,
)
from retail_profit_stack.store import Store, get_store
from retail_profit_stack.verify import same_value, verify_answer

CASES_FILE = EVALS_DIR / "m1_cases.json"


class ExpectedFigure(BaseModel):
    metric: str
    kind: str
    month: str
    entity_id: str
    value: float | None


class EvalCase(BaseModel):
    case_id: str
    question: str
    tiny: bool = False
    expected_status: str
    expected_figures: list[ExpectedFigure] = []
    expected_flags: list[str] = []
    expected_definitions: list[str] = []
    expected_confidence: str | None = None
    tests: str = ""


class CaseScore(BaseModel):
    case_id: str
    passed: bool
    checks: list[CheckResult]
    error: str | None = None


def load_cases(path: Path = CASES_FILE, tiny: bool = False) -> list[EvalCase]:
    cases = [EvalCase(**item) for item in json.loads(path.read_text("utf-8"))]
    return [case for case in cases if case.tiny] if tiny else cases


def full_tool_log(store: Store | None = None) -> list[ToolCall]:
    """Every fact the tools can return, as if all of them had been called.

    Used to check an answer that was produced without tools (the single model call in the
    notebook), where there is no tool log from the run itself.
    """
    store = store or get_store()
    log = []

    def call(name, function, **arguments):
        result = function(**arguments, store=store)
        log.append(ToolCall(name=name, arguments=arguments, result=result.model_dump()))

    months = store.months()
    call("get_reporting_period", tools.get_reporting_period)
    for term in ALL_TERMS:
        call("get_metric_definition", tools.get_metric_definition, metric=term)
    for group_by in ("product", "category"):
        for month in months:
            call("query_profit", tools.query_profit, month=month, group_by=group_by)
        for term in ALL_TERMS:
            call(
                "compare_profit",
                tools.compare_profit,
                month=months[-1],
                previous_month=months[0],
                group_by=group_by,
                metric=term,
            )
    for month in months:
        call("get_quality_flags", tools.get_quality_flags, month=month)
    return log


# These two checks compare the answer with what the run itself fetched, so they only make
# sense when the tool log comes from that run.
RUN_ONLY_CHECKS = {"confidence_matches_rule", "flags_mentioned"}


def score_case(
    case: EvalCase,
    answer: AnalystAnswer | None,
    tool_log: list[ToolCall],
    error: str | None = None,
    log_is_from_run: bool = True,
) -> CaseScore:
    """Check one answer against its case.

    tool_log is normally the log of the run that produced the answer. For an answer produced
    without tools, pass full_tool_log() and log_is_from_run=False.
    """
    if answer is None:
        failed = CheckResult(name="answer_returned", passed=False, detail=error or "No answer")
        return CaseScore(case_id=case.case_id, passed=False, checks=[failed], error=error)

    checks = [
        CheckResult(
            name="status_correct",
            passed=answer.status == case.expected_status,
            detail=f"Expected {case.expected_status}, got {answer.status}",
        )
    ]

    missing = [
        f"{expected.entity_id} {expected.metric} {expected.kind} {expected.month}"
        for expected in case.expected_figures
        if not any(
            (figure.metric, figure.kind, figure.month, figure.entity_id)
            == (expected.metric, expected.kind, expected.month, expected.entity_id)
            and same_value(figure.value, expected.value)
            for figure in answer.figures
        )
    ]
    checks.append(
        CheckResult(
            name="expected_figures",
            passed=not missing,
            detail=f"Missing or wrong: {missing}"
            if missing
            else f"All {len(case.expected_figures)} expected figures are present and correct",
        )
    )

    caveat_text = " ".join(f"{caveat.flag_id or ''} {caveat.text}" for caveat in answer.caveats)
    missing_flags = [flag_id for flag_id in case.expected_flags if flag_id not in caveat_text]
    checks.append(
        CheckResult(
            name="expected_flags",
            passed=not missing_flags,
            detail=f"Not mentioned: {missing_flags}"
            if missing_flags
            else "Expected flags mentioned",
        )
    )

    stated = {ref.metric for ref in answer.definitions_used}
    missing_definitions = [metric for metric in case.expected_definitions if metric not in stated]
    checks.append(
        CheckResult(
            name="expected_definitions",
            passed=not missing_definitions,
            detail=f"Not stated: {missing_definitions}"
            if missing_definitions
            else "Expected definitions stated",
        )
    )

    if case.expected_confidence is not None:
        actual = answer.confidence.level if answer.confidence else None
        checks.append(
            CheckResult(
                name="expected_confidence",
                passed=actual == case.expected_confidence,
                detail=f"Expected {case.expected_confidence}, got {actual}",
            )
        )

    checks.extend(
        check
        for check in verify_answer(answer, tool_log).checks
        if log_is_from_run or check.name not in RUN_ONLY_CHECKS
    )
    return CaseScore(
        case_id=case.case_id, passed=all(check.passed for check in checks), checks=checks
    )


def run_evaluation(ask: Callable[[str], AnalystRun], cases: list[EvalCase]) -> list[CaseScore]:
    """Ask every case's question and score the answers. ask is usually run_analyst."""
    scores = []
    for case in cases:
        run = ask(case.question)
        scores.append(score_case(case, run.answer, run.tool_log, run.error))
    return scores


def summarise(scores: list[CaseScore]) -> dict[str, str]:
    """Pass counts per check across all cases, plus the count of fully passing cases."""
    totals: dict[str, list[int]] = {}
    for score in scores:
        for check in score.checks:
            passed, count = totals.setdefault(check.name, [0, 0])
            totals[check.name] = [passed + check.passed, count + 1]
    summary = {name: f"{passed} / {count}" for name, (passed, count) in totals.items()}
    summary["cases_passed"] = f"{sum(score.passed for score in scores)} / {len(scores)}"
    return summary
