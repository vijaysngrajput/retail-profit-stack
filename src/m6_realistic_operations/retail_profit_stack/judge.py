"""A judge with a reference answer: grade an explanation against the true reason.

Implements LLD section 7 (The judge). Code can check a figure. It cannot check whether an
explanation gives the right reason: that is a judgement, so a model makes it. A judge is far
more reliable when it has a reference to compare against. Here code writes the reference from
the run comparison, and the judge only compares.

The judge is a different model from the analyst it grades.
"""

import os
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr

from retail_profit_stack.config import OPENROUTER_BASE_URL
from retail_profit_stack.schemas import RunComparison
from retail_profit_stack.tracing import ENV_FILE

JUDGE_MODEL = "google/gemma-4-31b-it"  # chosen by a live trial; see LLD section 7
GRADES = {"F": 0, "C": 1, "B": 2, "A": 3}

RUBRIC = """Grade the explanation against the reference. The reference is the true reason.
A: gives the same specific reason as the reference: which file, setting, or records. Wording \
may differ. Extra true detail is fine.
B: gives the right kind of reason without the specific cause, or leaves out one part of it.
C: vague, or only partly the reference's reason.
F: gives a different reason, contradicts the reference, or gives no reason.
Judge only the reason given. Do not reward length. Do not check the arithmetic."""


class Grade(BaseModel):
    """The judge's verdict on one explanation."""

    why: str = Field(description="One sentence: how the explanation compares with the reference")
    grade: Literal["A", "B", "C", "F"]


def make_judge(timeout: int = 60) -> ChatOpenAI:
    """The judge model, reached through OpenRouter. JUDGE_MODEL_NAME in .env overrides it."""
    load_dotenv(ENV_FILE)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(f"No OPENROUTER_API_KEY found. Add it to {ENV_FILE}")
    return ChatOpenAI(
        model=os.getenv("JUDGE_MODEL_NAME", JUDGE_MODEL),
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(api_key),
        timeout=timeout,
        max_retries=3,
        temperature=0,
        extra_body={"usage": {"include": True}},
    )


def reference_reason(comparison: RunComparison) -> str:
    """The true reason a figure did or did not change, written by code from the run comparison."""
    if not comparison.figures_changed:
        return (
            f"The figure did not change between {comparison.earlier_run} and "
            f"{comparison.later_run}. Nothing that feeds it was different."
        )
    parts = []
    for setting in comparison.settings_changed:
        if setting["name"] == "quarantine":
            parts.append("duplicated records are now set aside and no longer counted")
        else:
            parts.append(f"the setting {setting['name']} changed")
    if comparison.files_added:
        parts.append(f"files arrived late and were loaded: {', '.join(comparison.files_added)}")
    if comparison.files_corrected:
        parts.append(
            "a corrected file replaced the earlier version: "
            + ", ".join(comparison.files_corrected)
        )
    for record in comparison.records_changed:
        gone, new = record["only_in_earlier"], record["only_in_later"]
        if record.get("changed"):
            parts.append(f"{record['changed']} {record['source_table']} records were corrected")
        if gone:
            parts.append(f"{gone} {record['source_table']} records are no longer counted")
        if new:
            parts.append(f"{new} new {record['source_table']} records are now counted")
    figure = comparison.figures_changed[0]
    moved = f"The figure changed from {figure.earlier} to {figure.later}"
    return f"{moved} because " + "; ".join(parts) + "."


def grade_explanation(
    judge, question: str, reference: str, explanation: str
) -> tuple[Grade, float]:
    """Ask the judge to grade one explanation. Returns its verdict and what the call cost."""
    prompt = (
        f"Question: {question}\n\nReference (the true reason): {reference}\n\n"
        f"Explanation to grade: {explanation}"
    )
    structured = judge.with_structured_output(Grade, method="function_calling", include_raw=True)
    reply = structured.invoke([("system", RUBRIC), ("user", prompt)])
    usage = getattr(reply["raw"], "response_metadata", {}).get("token_usage") or {}
    verdict = reply["parsed"]
    if verdict is None:
        raise RuntimeError("The judge returned no usable grade")
    return verdict, float(usage.get("cost") or 0.0)
