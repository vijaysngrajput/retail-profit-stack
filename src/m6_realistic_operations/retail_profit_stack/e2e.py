"""The end-to-end evaluation: from generated files to scored answers.

Implements LLD section 6 (The end-to-end evaluation). Earlier evaluations started from data
that was already built. This one starts from nothing: it writes the files, loads them, runs
the pipeline to month-end close, loads the late files, runs again, and only then asks.

Some questions are asked at close and some after the late files, so there are two stores.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from langchain_core.runnables import RunnableConfig

from retail_profit_stack import source_data, tools
from retail_profit_stack.agent import run_analyst
from retail_profit_stack.analyst_versions import version_one
from retail_profit_stack.config import MAPPINGS_FILE
from retail_profit_stack.evaluation import EvalCase, score_case
from retail_profit_stack.ingest.dispatch import Batch, build_dispatcher, load_batch
from retail_profit_stack.ingest.feeds import Places
from retail_profit_stack.judge import GRADES, grade_explanation, reference_reason
from retail_profit_stack.make_history import apply_late_files, make_history
from retail_profit_stack.scoring import score_row
from retail_profit_stack.store import Store

STAGE_RUN = {"close": "RUN-0002", "late": "RUN-0003"}


@dataclass
class Workspace:
    """A folder holding one complete build of the system, from files to runs."""

    folder: Path
    places: Places
    warehouse: Path
    late: Path


def build_close(folder: Path) -> Workspace:
    """Build the system from nothing up to month-end close: files, loading, RUN-0001, RUN-0002."""
    if folder.exists():
        shutil.rmtree(folder)
    places = Places(
        landing=folder / "landing",
        loaded=folder / "loaded",
        state_file=folder / "loader_state.sqlite",
        mappings_file=folder / "approved_mappings.json",
    )
    workspace = Workspace(folder, places, folder / "warehouse", folder / "landing_late")
    # 1. Generate the files: the fifty that arrive on time, and the three that arrive late.
    source_data.write_landing_files(places.landing)
    source_data.write_late_files(workspace.late)
    shutil.copy(MAPPINGS_FILE, places.mappings_file)
    # 2. Load the first wave, and run to month-end close: RUN-0001 and RUN-0002.
    load_batch(places=places)
    make_history(workspace.warehouse, places.loaded)
    return workspace


def build_everything(folder: Path) -> Workspace:
    """Build the whole system from nothing in one folder. Takes about a second, with no model."""
    workspace = build_close(folder)
    # 3. Load the late files, and run only what they touch: RUN-0003.
    apply_late_files(workspace.places, workspace.warehouse, workspace.late)
    return workspace


def open_stores(workspace: Workspace) -> dict[str, Store]:
    """One store per stage: the run a question of that stage must be answered from."""
    stores = {}
    for stage, run_id in STAGE_RUN.items():
        stores[stage] = Store(
            source_dir=workspace.places.loaded,
            warehouse_dir=workspace.warehouse,
            run_id=run_id,
            state_file=workspace.places.state_file,
        )
    return stores


def answer_and_score(case: EvalCase, config: dict | None, stores: dict[str, Store], judge=None,
                     callbacks: list | None = None) -> dict:  # fmt: skip
    """Ask one question in its stage, score the answer, and have the judge grade the reason."""
    store = stores[case.stage]
    run = run_analyst(case.question, store=store, config=config, callbacks=callbacks)
    score = score_case(case, run.answer, run.tool_log, run.error)
    row = score_row(case, run, score)
    row["stage"] = case.stage
    row["question"] = case.question
    row["headline"] = run.answer.headline if run.answer else (run.error or "")
    row["failed_checks"] = [check.name for check in score.checks if not check.passed]
    row["grade"], row["letter"], row["judge_says"] = None, "", ""
    # Only "why did it change" questions have a reference, and only they are judged.
    if judge is not None and case.reference is not None:
        row["letter"], row["grade"] = "F", 0  # no answer, or a refusal, gives no reason at all
        if run.answer is not None and run.answer.status == "answered":
            comparison = tools.compare_runs(**case.reference, store=store)
            explanation = f"{run.answer.headline} {run.answer.narrative}"
            verdict, cost = grade_explanation(
                judge, case.question, reference_reason(comparison), explanation
            )
            row["letter"], row["grade"], row["judge_says"] = (
                verdict.grade,
                GRADES[verdict.grade],
                verdict.why,
            )
            row["model_cost"] += cost
    return row


def evaluate(cases: list[EvalCase], workspace: Workspace, config: dict | None = None, judge=None,
             at_once: int = 5, callbacks: list | None = None,
             run_name: str = "End-to-end evaluation") -> pd.DataFrame:  # fmt: skip
    """Ask every question, several at once, and return one scored row per question."""
    stores = open_stores(workspace)
    config = config or version_one()
    by_id = {case.case_id: case for case in cases}

    def work(case_id: str):
        return {"results": [answer_and_score(by_id[case_id], config, stores, judge, callbacks)]}

    batch: Batch = {"files": list(by_id), "results": []}
    settings: RunnableConfig = {
        "max_concurrency": at_once,
        "callbacks": callbacks or [],
        "run_name": run_name,
    }
    result = build_dispatcher(work).invoke(batch, settings)
    table = pd.DataFrame(result["results"])
    order = {case_id: position for position, case_id in enumerate(by_id)}
    return table.sort_values("case_id", key=lambda ids: ids.map(order)).reset_index(drop=True)


def summary(table: pd.DataFrame) -> dict[str, float]:
    """The scores of one evaluation: how right, how well explained, and what it cost."""
    rows = table.to_dict(orient="records")
    grades = [
        row["grade"] for row in rows if row["grade"] is not None and not pd.isna(row["grade"])
    ]
    count = len(rows)
    return {
        "accuracy": round(sum(bool(row["right"]) for row in rows) / count, 3),
        "grade": round(sum(grades) / len(grades), 2) if grades else 0.0,
        "cost_of_mistakes": float(sum(row["mistake_cost"] for row in rows)),
        "cost_per_question": round(sum(row["model_cost"] for row in rows) / count, 5),
        "seconds_per_question": round(sum(row["seconds"] for row in rows) / count, 1),
        "spent": round(sum(row["model_cost"] for row in rows), 4),
    }
