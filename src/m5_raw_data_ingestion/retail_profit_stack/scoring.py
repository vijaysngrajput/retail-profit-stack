"""Scoring an agent: the confusion matrix, kappa, and the cost of mistakes.

Implements LLD section 9 (Scoring). Every function here is plain arithmetic on answers that
have already been given. None of them needs a model or Langfuse.
"""

import pandas as pd

from retail_profit_stack.evaluation import CaseScore, EvalCase
from retail_profit_stack.schemas import AnalystRun

# The level of an answer, from most trusting to least. "declined" means no answer was given.
LEVELS = ["high", "medium", "low", "declined"]
CONFIDENCE_LEVELS = ["high", "medium", "low"]

# What each kind of mistake costs the business, in US dollars (BRD section 6). Fictional.
MISTAKE_COSTS = {
    "none": 0,
    "answered_when_it_should_decline": 5000,
    "no_answer": 200,
    "stopped_by_verifier": 200,
    "wrong_figure": 10000,
    "too_confident": 5000,
    "warning_left_out": 1000,
    "not_confident_enough": 200,
    "other_check_failed": 100,
}

WARNING_CHECKS = {"expected_flags", "flags_mentioned"}


def right_level(case: EvalCase) -> str | None:
    """The level a correct answer has. None when the question does not test the level."""
    if case.expected_status == "declined":
        return "declined"
    return case.expected_confidence


def answer_level(run: AnalystRun) -> str:
    """The level of the answer the analyst gave."""
    if run.answer is None or run.answer.status == "declined":
        return "declined"
    if run.answer.confidence is None:
        return "high"  # an answer with no word of doubt is read as fully trusted
    return run.answer.confidence.level


def mistake(case: EvalCase, run: AnalystRun, score: CaseScore) -> str:
    """The name of the mistake an answer is charged for, or "none". The first match wins.

    An answer the verifier rejects never reaches the leader: a person answers instead. So it
    costs what a missing answer costs. The large costs are for mistakes the verifier let through.
    """
    right = right_level(case)
    level = answer_level(run)
    failed = {check.name for check in score.checks if not check.passed}

    if right == "declined" and level != "declined":
        return "answered_when_it_should_decline"
    if level == "declined" and right != "declined":
        return "no_answer"
    if run.verification is not None and not run.verification.passed:
        return "stopped_by_verifier"
    if "expected_figures" in failed:
        return "wrong_figure"
    # LEVELS runs from most confident to least, so a smaller position is more confident.
    if right in CONFIDENCE_LEVELS and LEVELS.index(level) < LEVELS.index(right):
        return "too_confident"
    if failed & WARNING_CHECKS:
        return "warning_left_out"
    if right in CONFIDENCE_LEVELS and LEVELS.index(level) > LEVELS.index(right):
        return "not_confident_enough"
    if failed:
        return "other_check_failed"
    return "none"


def score_row(case: EvalCase, run: AnalystRun, score: CaseScore) -> dict:
    """One row of the score table: one question, the answer it got, and what that cost."""
    name = mistake(case, run, score)
    return {
        "case_id": case.case_id,
        "right_level": right_level(case),
        "level": answer_level(run),
        "right": score.passed,
        "mistake": name,
        "mistake_cost": MISTAKE_COSTS[name],
        "verified": bool(run.verification and run.verification.passed),
        "model_cost": run.cost,
        "seconds": run.seconds,
    }


def score_table(rows: list[dict]) -> pd.DataFrame:
    """The score rows as a table, in question order."""
    return pd.DataFrame(rows)


def confusion_matrix(table: pd.DataFrame) -> pd.DataFrame:
    """Rows: the right level. Columns: the level the analyst gave. Each cell counts answers.

    Questions that do not test the level are left out.
    """
    tested = table[table["right_level"].notna()]
    matrix = pd.crosstab(tested["right_level"], tested["level"])
    matrix = matrix.reindex(index=LEVELS, columns=LEVELS, fill_value=0)
    matrix.index.name = "right level"
    matrix.columns.name = "analyst said"
    return matrix


def tested_levels(table: pd.DataFrame) -> list[tuple[str, str]]:
    """(right level, analyst's level) for each question that tests the level."""
    pairs = []
    for row in table.to_dict(orient="records"):
        if isinstance(row["right_level"], str):  # a question with no right level has None or NaN
            pairs.append((row["right_level"], row["level"]))
    return pairs


def kappa(table: pd.DataFrame) -> float:
    """Cohen's kappa: how much better than chance the analyst agrees with the right levels.

    1 is perfect agreement. 0 is no better than chance.
    """
    pairs = tested_levels(table)
    if not pairs:
        return 0.0
    count = len(pairs)
    observed = sum(right == said for right, said in pairs) / count
    by_chance = 0.0
    for level in LEVELS:
        right_share = sum(right == level for right, _ in pairs) / count
        analyst_share = sum(said == level for _, said in pairs) / count
        by_chance += right_share * analyst_share
    if by_chance == 1:
        return 1.0
    return (observed - by_chance) / (1 - by_chance)


def run_scores(table: pd.DataFrame) -> dict[str, float]:
    """The scores of a whole experiment."""
    rows = table.to_dict(orient="records")
    pairs = tested_levels(table)
    count = len(rows)
    return {
        "accuracy": round(sum(bool(row["right"]) for row in rows) / count, 3),
        "level_accuracy": round(
            sum(right == said for right, said in pairs) / max(len(pairs), 1), 3
        ),
        "kappa": round(kappa(table), 3),
        "cost_of_mistakes": float(sum(row["mistake_cost"] for row in rows)),
        "verified_rate": round(sum(bool(row["verified"]) for row in rows) / count, 3),
        "model_cost": round(sum(row["model_cost"] for row in rows), 4),
        "seconds": round(sum(row["seconds"] for row in rows), 1),
    }
