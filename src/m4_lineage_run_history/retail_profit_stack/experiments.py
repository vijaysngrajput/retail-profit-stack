"""Experiments: run the analyst on every evaluation question, in Langfuse.

Implements LLD section 10 (Experiments). A Langfuse dataset holds the questions and their
correct answers. An experiment runs one version of the analyst on every question, scores each
answer, and scores the whole run. Langfuse keeps every experiment, so two can be compared.

This is the only file that talks to Langfuse about datasets and experiments.
"""

import pandas as pd
from dotenv import load_dotenv

from retail_profit_stack.agent import run_analyst
from retail_profit_stack.evaluation import EvalCase, score_case
from retail_profit_stack.scoring import right_level, run_scores, score_row, score_table
from retail_profit_stack.tracing import ENV_FILE, langfuse_ready

DATASET = "profit-questions"


def langfuse_client():
    """The connection to Langfuse, made from the three settings in the .env file."""
    if not langfuse_ready():
        raise RuntimeError(f"Experiments need the three Langfuse settings in {ENV_FILE}.")
    load_dotenv(ENV_FILE)
    from langfuse import get_client  # imported here so offline use needs nothing

    return get_client()


def upload_questions(cases: list[EvalCase]) -> None:
    """Store the questions in Langfuse as a dataset.

    Each item's id comes from the question's id, so uploading again updates the items in
    place and adds none.
    """
    client = langfuse_client()
    client.create_dataset(
        name=DATASET, description="Profit questions with their correct answers (fictional data)"
    )
    for case in cases:
        client.create_dataset_item(
            dataset_name=DATASET,
            id=f"profit-question-{case.case_id}",
            input={"question": case.question},
            expected_output={
                "status": case.expected_status,
                "level": right_level(case),
                "figures": [figure.model_dump() for figure in case.expected_figures],
                "flags": case.expected_flags,
            },
            metadata={"case_id": case.case_id, "tiny": case.tiny},
        )
    client.flush()


def answer_and_score(case: EvalCase, run_tool: bool, trace: bool = True) -> dict:
    """Ask the analyst one question and score the answer. Returns one row of the score table."""
    run = run_analyst(case.question, trace=trace, run_tool=run_tool)
    score = score_case(case, run.answer, run.tool_log, run.error)
    row = score_row(case, run, score)
    row["headline"] = run.answer.headline if run.answer else (run.error or "")
    row["failed_checks"] = [check.name for check in score.checks if not check.passed]
    return row


def run_experiment(
    name: str, description: str, cases: list[EvalCase], run_tool: bool, times: int = 1
) -> pd.DataFrame:
    """Run one version of the analyst on every question, `times` times. Returns the score table."""
    from langfuse import Evaluation

    client = langfuse_client()
    case_by_id = {case.case_id: case for case in cases}
    dataset = client.get_dataset(DATASET)
    items = [item for item in dataset.items if item.metadata["case_id"] in case_by_id]

    def task(*, item, **kwargs):
        """What Langfuse runs for each question."""
        return answer_and_score(case_by_id[item.metadata["case_id"]], run_tool)

    def score_one_answer(*, output, **kwargs):
        """Item evaluator: the scores Langfuse attaches to one answer."""
        return [
            Evaluation(name="right", value=int(output["right"])),
            Evaluation(
                name="mistake_cost", value=output["mistake_cost"], comment=output["mistake"]
            ),
        ]

    def score_whole_run(*, item_results, **kwargs):
        """Run evaluator: the scores Langfuse attaches to the whole experiment."""
        table = score_table([result.output for result in item_results])
        return [Evaluation(name=key, value=value) for key, value in run_scores(table).items()]

    tables = []
    for repeat in range(1, times + 1):
        result = client.run_experiment(
            name=name,
            description=description,
            data=items,
            task=task,
            evaluators=[score_one_answer],
            run_evaluators=[score_whole_run],
            max_concurrency=1,
        )
        table = score_table([item_result.output for item_result in result.item_results])
        tables.append(table.sort_values("case_id", key=_question_order).assign(repeat=repeat))
    client.flush()
    return pd.concat(tables, ignore_index=True)


def _question_order(case_ids: pd.Series) -> pd.Series:
    """Sort E2 before E10: by the number after the letter."""
    return case_ids.str[1:].astype(int)
