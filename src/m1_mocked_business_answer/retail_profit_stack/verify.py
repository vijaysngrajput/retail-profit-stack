"""The answer verifier: code that checks an answer before anyone relies on it.

Implements LLD section 8 (Verifier checks). The verifier compares the answer
with the tool log from the same run. It never asks a model for an opinion.
"""

import re

from retail_profit_stack.config import METRIC_VERSION
from retail_profit_stack.schemas import (
    ALL_TERMS,
    AnalystAnswer,
    CheckResult,
    Figure,
    ToolCall,
    VerificationReport,
)

CONFIDENCE_ORDER = ["high", "medium", "low"]
VALUE_TOLERANCE = 0.005
SMALL_COUNT = 12  # ranks and counts up to the size of the catalogue need no source

_NOT_FIGURES = [
    re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b"),  # months and dates
    re.compile(r"\b\d+\.\d+\.\d+\b"),  # version numbers
    re.compile(r"\b[A-Za-z]+-?\d+(?:-[\w-]+)?\b"),  # identifiers such as QF-001, P001, ORD-20401
]
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")

FactKey = tuple[str, str, str, str]  # metric, kind, month, entity_id


def build_fact_index(tool_log: list[ToolCall]) -> dict[FactKey, list[float | None]]:
    """Every figure the tools returned in this run, keyed by what it measures."""
    facts: dict[FactKey, list[float | None]] = {}

    def add(metric, kind, month, entity_id, value):
        facts.setdefault((metric, kind, month, entity_id), []).append(value)

    for call in tool_log:
        result = call.result
        if result is None:
            continue
        if call.name == "query_profit":
            for row in result["rows"]:
                for term in ALL_TERMS:
                    add(term, "value", row["month"], row["entity_id"], row[term])
        elif call.name == "compare_profit":
            metric = result["metric"]
            for row in result["rows"]:
                entity_id = row["entity_id"]
                add(metric, "value", result["month"], entity_id, row["current"])
                add(metric, "value", result["previous_month"], entity_id, row["previous"])
                add(metric, "change", result["month"], entity_id, row["change"])
                add(metric, "pct_change", result["month"], entity_id, row["pct_change"])
    return facts


def same_value(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(left - right) <= VALUE_TOLERANCE


def figure_is_supported(figure: Figure, facts: dict[FactKey, list[float | None]]) -> bool:
    values = facts.get((figure.metric, figure.kind, figure.month, figure.entity_id), [])
    return any(same_value(figure.value, value) for value in values)


def numbers_in_text(text: str) -> list[tuple[float, int]]:
    """Numbers written in prose, each with its count of decimal places. Dates and IDs are skipped."""
    for pattern in _NOT_FIGURES:
        text = pattern.sub(" ", text)
    found = []
    for match in _NUMBER.findall(text):
        cleaned = match.replace(",", "").rstrip(".")
        decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
        found.append((float(cleaned), decimals))
    return found


def _numbers_in_results(value) -> list[float]:
    """Every number anywhere in the tool results, including numbers inside text fields."""
    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [abs(float(value))]
    if isinstance(value, str):
        return [number for number, _ in numbers_in_text(value)]
    if isinstance(value, dict):
        return [number for item in value.values() for number in _numbers_in_results(item)]
    if isinstance(value, list):
        return [number for item in value for number in _numbers_in_results(item)]
    return []


def _quality_results(tool_log: list[ToolCall]) -> list[dict]:
    return [call.result for call in tool_log if call.name == "get_quality_flags" and call.result]


def _check_figures(answer, tool_log) -> CheckResult:
    facts = build_fact_index(tool_log)
    unsupported = [
        figure.label for figure in answer.figures if not figure_is_supported(figure, facts)
    ]
    return CheckResult(
        name="figures_match_tools",
        passed=not unsupported,
        detail=f"No tool returned: {unsupported}"
        if unsupported
        else f"{len(answer.figures)} figures match tool results",
    )


def _check_prose_numbers(answer, tool_log) -> CheckResult:
    known = _numbers_in_results([call.result for call in tool_log])
    known += [abs(figure.value) for figure in answer.figures if figure.value is not None]
    unsupported = []
    for number, decimals in numbers_in_text(f"{answer.headline} {answer.narrative}"):
        if decimals == 0 and number <= SMALL_COUNT:
            continue
        tolerance = 0.5 * 10 ** (-decimals) + 1e-9
        if not any(abs(number - value) <= tolerance for value in known):
            unsupported.append(number)
    return CheckResult(
        name="no_unsupported_numbers",
        passed=not unsupported,
        detail=f"Numbers in the text that no tool returned: {unsupported}"
        if unsupported
        else "Every number in the text comes from a tool result",
    )


def _check_sources(answer, tool_log) -> CheckResult:
    if answer.status == "declined":
        return CheckResult(name="sources_cited", passed=True, detail="Not required when declined")
    read = {
        source["table"].lower().removesuffix(".csv")
        for call in tool_log
        if call.result
        for source in call.result.get("sources", [])
    }
    cited = {source.table.lower().removesuffix(".csv") for source in answer.sources}
    unknown = sorted(cited - read)
    if not cited:
        return CheckResult(name="sources_cited", passed=False, detail="The answer cites no source")
    return CheckResult(
        name="sources_cited",
        passed=not unknown,
        detail=f"Cited but never read: {unknown}" if unknown else f"Cites {sorted(cited)}",
    )


def _check_definitions(answer) -> CheckResult:
    stated = {(ref.metric, ref.version) for ref in answer.definitions_used}
    needed = sorted({figure.metric for figure in answer.figures if figure.metric in ALL_TERMS})
    missing = [metric for metric in needed if (metric, METRIC_VERSION) not in stated]
    return CheckResult(
        name="definitions_stated",
        passed=not missing,
        detail=f"No definition at version {METRIC_VERSION} stated for: {missing}"
        if missing
        else "Every metric used has its definition and version stated",
    )


def _check_confidence(answer, tool_log) -> CheckResult:
    name = "confidence_matches_rule"
    if answer.status == "declined" or not answer.figures:
        return CheckResult(name=name, passed=True, detail="Not required without figures")
    results = _quality_results(tool_log)
    if not results:
        return CheckResult(name=name, passed=False, detail="get_quality_flags was never called")
    expected = max((result["confidence_level"] for result in results), key=CONFIDENCE_ORDER.index)
    actual = answer.confidence.level if answer.confidence else None
    return CheckResult(
        name=name,
        passed=actual == expected,
        detail=f"Answer says {actual}; the rule gives {expected}",
    )


def _check_flags(answer, tool_log) -> CheckResult:
    returned = {
        flag["flag_id"] for result in _quality_results(tool_log) for flag in result["flags"]
    }
    caveat_text = " ".join(f"{caveat.flag_id or ''} {caveat.text}" for caveat in answer.caveats)
    missing = sorted(flag_id for flag_id in returned if flag_id not in caveat_text)
    return CheckResult(
        name="flags_mentioned",
        passed=not missing,
        detail=f"Flags returned but not in the caveats: {missing}"
        if missing
        else f"All {len(returned)} returned flags are in the caveats",
    )


def _check_decline(answer) -> CheckResult:
    name = "decline_is_clean"
    if answer.status != "declined":
        return CheckResult(name=name, passed=True, detail="Not a declined answer")
    clean = not answer.figures and bool(answer.decline_reason and answer.decline_reason.strip())
    return CheckResult(
        name=name,
        passed=clean,
        detail="Declined with a reason and no figures"
        if clean
        else "A declined answer must give a reason and no figures",
    )


def verify_answer(answer: AnalystAnswer, tool_log: list[ToolCall]) -> VerificationReport:
    """Run every LLD section 8 check on one answer."""
    checks = [
        _check_figures(answer, tool_log),
        _check_prose_numbers(answer, tool_log),
        _check_sources(answer, tool_log),
        _check_definitions(answer),
        _check_confidence(answer, tool_log),
        _check_flags(answer, tool_log),
        _check_decline(answer),
    ]
    return VerificationReport(passed=all(check.passed for check in checks), checks=checks)
