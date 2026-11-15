"""The file workflow: a graph that loads one file, and can wait for a person.

Implements LLD sections 2 and 7. The workflow is a LangGraph graph. Each node is a plain
function that reads the state and returns the parts it changes. The state is saved to a
SQLite file after every node, so a file can wait hours for approval, and can carry on after a
crash. Each file runs on its own thread, and the thread's id is the file's name.

To answer the waiting files in a terminal:  uv run python -m retail_profit_stack.ingest.workflow
"""

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import pyarrow.parquet as pq
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from retail_profit_stack.ingest import ledger
from retail_profit_stack.ingest.feeds import Places, expected_columns, feed_of, piece_path
from retail_profit_stack.ingest.mapping import (
    mapping_problem,
    read_approved_mappings,
    read_file,
    save_approved_mapping,
    suggest_mapping,
)
from retail_profit_stack.ingest.rules import inspect_file
from retail_profit_stack.transform.contracts import ContractError


class FileState(TypedDict):
    """What the workflow keeps for one file."""

    file_name: str
    feed: str
    inspection: dict  # what inspect_file found
    suggestion: dict  # the model's suggestion; empty when no model was asked
    mapping: dict  # the mapping to apply; empty for none
    approved_by: str
    outcome: str  # loaded, skipped, rejected, already_loaded
    reason: str
    rows_loaded: int
    model_cost: float


def open_saver(state_file: Path) -> SqliteSaver:
    """The checkpointer: it saves every workflow's state in the SQLite file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(state_file, check_same_thread=False, timeout=30)
    saver = SqliteSaver(connection)
    saver.setup()
    return saver


def build_file_workflow(places: Places | None = None, model=None, saver: SqliteSaver | None = None):
    """Build the workflow for one file. model may be None: then no suggestion is made."""
    places = places or Places()
    saver = saver or open_saver(places.state_file)

    def inspect(state: FileState):
        """Fingerprint the file, compare its columns with the contract, and choose the rule."""
        file_name = state["file_name"]
        feed = feed_of(file_name)
        loaded = ledger.loaded_fingerprints(places.state_file)
        # The fingerprint each file name was last loaded with (the latest wins).
        names = {entry["file_name"]: entry["fingerprint"]
                 for entry in ledger.files_seen(places.state_file) if entry["outcome"] == "loaded"}  # fmt: skip
        approved = read_approved_mappings(places.mappings_file).get(feed, [])
        found = inspect_file(
            places.landing / file_name, expected_columns(feed), loaded, approved, names
        )
        return {
            "feed": feed, "inspection": found.as_dict(), "mapping": found.mapping,
            "outcome": found.outcome, "reason": found.reason, "rows_loaded": 0,
            "suggestion": {}, "approved_by": "", "model_cost": 0.0,
        }  # fmt: skip

    def suggest(state: FileState):
        """Ask the model what the unknown columns mean. It suggests; it decides nothing."""
        if model is None:
            return {"suggestion": {}}
        found = state["inspection"]
        suggestion, cost = suggest_mapping(
            model, state["feed"], places.landing / state["file_name"],
            found["missing"], found["unknown"], places,
        )  # fmt: skip
        return {"suggestion": suggestion.model_dump(), "model_cost": cost}

    def approval(state: FileState):
        """Pause until a person approves or refuses the mapping.

        On resume this node runs again from the top, so nothing before interrupt() may be
        something that would be wrong to do twice. Writing "waiting" twice is harmless.
        """
        found = state["inspection"]
        ledger.record_file(
            places.state_file, state["file_name"], state["feed"], found["fingerprint"],
            "waiting", found["rule"], found["reason"],
        )  # fmt: skip
        suggested = {
            guess["file_column"]: guess["expected_column"]
            for guess in state["suggestion"].get("columns", [])
            if guess["expected_column"] != "none"
        }
        answer = interrupt({
            "file_name": state["file_name"], "missing": found["missing"],
            "unknown": found["unknown"], "suggested_mapping": suggested,
            "suggestion": state["suggestion"],
        })  # fmt: skip

        person = answer.get("person", "")
        if not answer.get("approved"):
            return {"outcome": "rejected", "reason": f"The mapping was refused by {person}.",
                    "approved_by": person}  # fmt: skip
        mapping = answer.get("mapping") or suggested
        problem = mapping_problem(mapping, state["feed"], found["missing"], found["unknown"])
        if problem:
            return {"outcome": "rejected", "reason": f"The approved mapping cannot be used: {problem}.",
                    "approved_by": person}  # fmt: skip
        save_approved_mapping(places.mappings_file, state["feed"], mapping)
        return {"outcome": "load", "mapping": mapping, "approved_by": person,
                "reason": f"Loaded with a mapping approved by {person}: {mapping}."}  # fmt: skip

    def load(state: FileState):
        """Apply the mapping, check the values, and write the file's rows as one piece.

        This node is safe to run twice. The fingerprint can be claimed only once, and writing
        the same piece again changes nothing.
        """
        file_name = state["file_name"]
        try:
            table = read_file(places.landing / file_name, state["feed"], state["mapping"])
        except ContractError as error:
            return {"outcome": "rejected", "reason": f"The values do not fit the contract: {error}"}
        owner = ledger.claim_content(
            places.state_file, state["inspection"]["fingerprint"], file_name
        )
        if owner != file_name:
            return {"outcome": "skipped",
                    "reason": f"The same content was already loaded from {owner}."}  # fmt: skip
        piece = piece_path(places, file_name)
        piece.parent.mkdir(parents=True, exist_ok=True)
        # New in milestone 6: a correction overwrites the piece, and the old version is noted.
        if state["inspection"].get("correction"):
            earlier = [entry for entry in ledger.files_seen(places.state_file)
                       if entry["file_name"] == file_name]  # fmt: skip
            if earlier and earlier[0]["fingerprint"] != state["inspection"]["fingerprint"]:
                ledger.record_replaced(places.state_file, file_name, earlier[0]["fingerprint"])
        pq.write_table(table, piece)
        return {"outcome": "loaded", "rows_loaded": table.num_rows}

    def finish(state: FileState):
        """Write the file's final outcome to the load record."""
        if state["outcome"] == "already_loaded":
            return {}  # its row already says "loaded"; leave it alone
        found = state["inspection"]
        ledger.record_file(
            places.state_file, state["file_name"], state["feed"], found["fingerprint"],
            state["outcome"], found["rule"], state["reason"], state["rows_loaded"],
            state["mapping"], state["approved_by"],
        )  # fmt: skip
        return {}

    def after_inspect(state: FileState) -> str:
        """Choose the next node from the rule's outcome."""
        if state["outcome"] == "load":
            return "load"
        if state["outcome"] == "needs_mapping":
            return "suggest"
        return "finish"

    def after_approval(state: FileState) -> str:
        return "load" if state["outcome"] == "load" else "finish"

    builder = StateGraph(FileState)
    builder.add_node("inspect", inspect)
    builder.add_node("suggest", suggest)
    builder.add_node("approval", approval)
    builder.add_node("load", load)
    builder.add_node("finish", finish)
    builder.add_edge(START, "inspect")
    builder.add_conditional_edges("inspect", after_inspect, ["load", "suggest", "finish"])
    builder.add_edge("suggest", "approval")
    builder.add_conditional_edges("approval", after_approval, ["load", "finish"])
    builder.add_edge("load", "finish")
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=saver)


def thread(file_name: str) -> RunnableConfig:
    """The config that names a file's own thread."""
    return {"configurable": {"thread_id": file_name}}


def run_file(workflow, file_name: str, callbacks: list | None = None) -> dict:
    """Run the workflow for one file. Returns its name, outcome, reason, seconds, and cost.

    A file that paused for approval comes back with the outcome "waiting".
    """
    start = time.time()
    started = datetime.now()
    config: RunnableConfig = {
        "configurable": {"thread_id": file_name},
        "callbacks": callbacks or [],
    }
    state = workflow.invoke({"file_name": file_name}, config, durability="sync")
    waiting = "__interrupt__" in state
    return {
        "file_name": file_name,
        "feed": state.get("feed", ""),
        "outcome": "waiting" if waiting else state["outcome"],
        "reason": state.get("reason", ""),
        "rows_loaded": state.get("rows_loaded", 0),
        "suggestion": state.get("suggestion", {}),
        "model_cost": state.get("model_cost", 0.0),
        "seconds": round(time.time() - start, 2),
        "started": started,
        "finished": datetime.now(),
    }


def waiting_files(workflow, places: Places | None = None) -> list[dict]:
    """Every file that is paused for approval, with what it is waiting on."""
    places = places or Places()
    waiting = []
    for entry in ledger.files_seen(places.state_file):
        if entry["outcome"] != "waiting":
            continue
        state = workflow.get_state(thread(entry["file_name"]))
        if state.interrupts:
            waiting.append(state.interrupts[0].value)
    return waiting


def answer(workflow, file_name: str, approved: bool, person: str,
           mapping: dict[str, str] | None = None) -> dict:  # fmt: skip
    """Give a person's answer to a waiting file, and let its workflow carry on."""
    reply = {"approved": approved, "person": person, "mapping": mapping}
    state = workflow.invoke(Command(resume=reply), thread(file_name), durability="sync")
    return {"file_name": file_name, "outcome": state["outcome"], "reason": state["reason"],
            "rows_loaded": state["rows_loaded"]}  # fmt: skip


if __name__ == "__main__":
    the_workflow = build_file_workflow()
    for question in waiting_files(the_workflow):
        print(f"\n{question['file_name']}")
        print(f"  missing: {question['missing']}   unknown: {question['unknown']}")
        print(f"  suggested mapping: {question['suggested_mapping']}")
        reply = input("  Approve this mapping? (y/n) ").strip().lower()
        name = input("  Your name: ").strip()
        print(" ", answer(the_workflow, question["file_name"], reply == "y", name))
    print("\nNo more files are waiting.")
