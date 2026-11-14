"""Tracing: keep a record of every step the analyst takes.

Implements LLD section 7 (Tracing). A trace is a list of steps, each with a start, an end, an
input, and an output. StepRecorder keeps that list in memory for every run. When tracing is
switched on, Langfuse's handler also sends the steps to Langfuse, where they can be opened
later.

Both are "callback handlers": objects with methods that LangChain calls when a model call or a
tool call starts and ends.
"""

import os
import time

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler

from retail_profit_stack.config import MILESTONE_DIR

ENV_FILE = MILESTONE_DIR.parent.parent / ".env"
LANGFUSE_SETTINGS = ["LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_BASE_URL"]


class StepRecorder(BaseCallbackHandler):
    """Records each model call and each tool call of one agent run, in order."""

    def __init__(self):
        self.steps: list[dict] = []
        self.cost = 0.0
        self._started: dict = {}  # the step's id -> the time it started

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._started[run_id] = time.time()

    def on_llm_end(self, response, *, run_id, **kwargs):
        message = response.generations[0][0].message
        usage = message.response_metadata.get("token_usage") or {}
        cost = usage.get("cost") or 0.0
        self.cost += cost
        asked_for = [call["name"] for call in message.tool_calls]
        self.steps.append({
            "step": "model",
            "name": "model call",
            "detail": f"asked for: {', '.join(asked_for)}" if asked_for else "wrote text",
            "seconds": self._seconds_since_start(run_id),
            "tokens": usage.get("total_tokens", 0),
            "cost": cost,
        })  # fmt: skip

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self._started[run_id] = time.time()
        self.steps.append({
            "step": "tool", "name": serialized.get("name", "tool"), "detail": str(input_str)[:120],
            "seconds": 0.0, "tokens": 0, "cost": 0.0, "_id": run_id,
        })  # fmt: skip

    def on_tool_end(self, output, *, run_id, **kwargs):
        for step in self.steps:
            if step.get("_id") == run_id:
                step["seconds"] = self._seconds_since_start(run_id)
                del step["_id"]

    def _seconds_since_start(self, run_id) -> float:
        return round(time.time() - self._started.pop(run_id, time.time()), 2)


def langfuse_ready() -> bool:
    """True when the three Langfuse settings are present in the .env file."""
    load_dotenv(ENV_FILE)
    return all(os.getenv(name) for name in LANGFUSE_SETTINGS)


def langfuse_handler():
    """Langfuse's own callback handler. It sends every step to Langfuse."""
    if not langfuse_ready():
        raise RuntimeError(
            f"Tracing needs {', '.join(LANGFUSE_SETTINGS)} in {ENV_FILE}. "
            "The milestone's README says how to get them."
        )
    from langfuse.langchain import CallbackHandler  # imported here so offline use needs nothing

    return CallbackHandler()


def trace_labels(run_id: str, name: str) -> dict:
    """Labels Langfuse shows on the trace, so a trace can be found by its pipeline run."""
    return {"langfuse_trace_name": name, "langfuse_tags": [run_id, "milestone-4"]}
