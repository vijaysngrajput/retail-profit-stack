"""The dispatcher: load many files side by side.

Implements LLD section 8. The dispatcher is a second, smaller graph with no model in it. It
starts one file workflow for each file, runs up to max_concurrency of them at once, and runs
a failed one again. Each file runs on its own thread, so one file can wait for a person while
the others finish.

Run it with:  uv run python -m retail_profit_stack.ingest.dispatch
"""

import operator
import shutil
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from retail_profit_stack.ingest import ledger
from retail_profit_stack.ingest.feeds import Places, landing_files
from retail_profit_stack.ingest.workflow import build_file_workflow, run_file


class Batch(TypedDict):
    """What the dispatcher keeps for one batch of files."""

    files: list[str]
    # Each worker returns a list with its own result. operator.add joins the lists together.
    results: Annotated[list, operator.add]


def build_dispatcher(work_file):
    """A graph that runs work_file once for every file in the batch."""

    def fan_out(state: Batch):
        """Send each file to its own worker."""
        return [Send("work_file", file_name) for file_name in state["files"]]

    builder = StateGraph(Batch)
    # A worker that fails, for example because the model is busy, is run again: up to 3 tries.
    retry = RetryPolicy(max_attempts=3, initial_interval=0.5, retry_on=Exception)
    builder.add_node("work_file", work_file, retry_policy=retry)
    builder.add_conditional_edges(START, fan_out, ["work_file"])
    builder.add_edge("work_file", END)
    return builder.compile()


def load_batch(
    files: list[str] | None = None,
    max_concurrency: int = 5,
    model=None,
    places: Places | None = None,
    callbacks: list | None = None,
    run_name: str = "Load batch",
) -> list[dict]:
    """Load a batch of landing files. Returns one result per file, in file-name order.

    With files=None every file in the landing folder is loaded. model may be None: then a
    file that needs a mapping waits without a suggestion. A file already loaded is left alone.
    """
    places = places or Places()
    workflow = build_file_workflow(places, model)

    def work_file(file_name: str):
        """Run the file workflow for one file, on that file's own thread."""
        return {"results": [run_file(workflow, file_name, callbacks)]}

    dispatcher = build_dispatcher(work_file)
    batch: Batch = {"files": files if files is not None else landing_files(places), "results": []}
    config: RunnableConfig = {
        "max_concurrency": max_concurrency,
        "callbacks": callbacks or [],
        "run_name": run_name,
    }
    result = dispatcher.invoke(batch, config)
    return sorted(result["results"], key=lambda item: item["file_name"])


def clear_loaded(places: Places | None = None) -> None:
    """Forget everything that was loaded: the pieces, the load record, and the saved workflows.

    The landing files and the approved mappings are kept.
    """
    places = places or Places()
    if places.loaded.exists():
        shutil.rmtree(places.loaded)
    for suffix in ("", "-wal", "-shm"):
        state_file = places.state_file.with_name(places.state_file.name + suffix)
        if state_file.exists():
            state_file.unlink()


if __name__ == "__main__":
    for item in load_batch():
        print(f"{item['outcome']:15} {item['file_name']:40} {item['reason']}")
    print(ledger.outcome_counts(Places().state_file))
