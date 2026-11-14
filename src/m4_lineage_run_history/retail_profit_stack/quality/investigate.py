"""The investigator: an AI agent that works through the findings on its own.

Implements LLD section 8 (The investigator agent). It is built with Deep Agents, a ready-made
harness: file tools limited to the desk folder, a to-do list, and a helper for each finding.
We write no tools. The agent explains; it never decides an outcome.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

MAIN_INSTRUCTIONS = """You are a data engineer at Kestrel Ridge Outfitters. The quality checks \
found problems in the business's records, and you are working through them on your own.

Everything you need is in this folder:
- findings/ has one file for each finding
- rulebook.md is the data quality rulebook
- reports/ is where the reports go

Investigate every finding in findings/. Keep a to-do list with one item for each finding, and \
give each finding to the investigator subagent. Tell it only the finding id. It already knows \
how to investigate a finding, and it writes the report to reports/<finding id>.json.
When every finding has a .json report, write handover.md at the top of this folder: a short note for \
the data engineer. Group the findings that have the same cause, and say what to do first.
You cannot change the data or the outcome of a check. You only write notes.
"""

HELPER_INSTRUCTIONS = """You are a data engineer at Kestrel Ridge Outfitters. Investigate the \
one finding you are given.

Read the finding's file in findings/. Read rulebook.md for the rules of its check.
Look at the records in the file and choose the one cause whose sign matches them.

Write your report to reports/<finding id>.json with exactly these fields:
- finding_id
- likely_cause: one cause name, exactly as the rulebook writes it
- evidence: one or two sentences saying what in the records points to that cause
- suggested_action: one sentence for the data engineer

Then reply with one line: the finding id and the cause.
"""

MAX_STEPS = 200  # the run stops if the agent takes more steps than this


@dataclass
class InvestigationRun:
    """What one run of the investigator did."""

    steps: list[str] = field(default_factory=list)  # one line per tool call, helpers indented
    model_calls: int = 0
    cost: float = 0.0  # US dollars, as reported by OpenRouter
    seconds: float = 0.0
    final_message: str = ""
    error: str = ""


def build_investigator(model, desk_folder: Path):
    """Build the agent. Its file tools can reach the desk folder and nothing else."""
    from deepagents import SubAgent, create_deep_agent  # imported here: a large library
    from deepagents.backends import FilesystemBackend
    from langchain.agents.middleware import TodoListMiddleware

    helper: SubAgent = {
        "name": "investigator",
        "description": "Investigates one finding and writes its report file. Give it the finding id.",
        "system_prompt": HELPER_INSTRUCTIONS,
    }
    return create_deep_agent(
        model=model,
        system_prompt=MAIN_INSTRUCTIONS,
        subagents=[helper],
        middleware=[TodoListMiddleware()],
        backend=FilesystemBackend(root_dir=Path(desk_folder), virtual_mode=True),
    )


def describe_step(tool_call: dict) -> str:
    """A short line about one tool call, for printing."""
    name, args = tool_call["name"], tool_call["args"]
    if not isinstance(args, dict):
        return name
    if name == "write_todos":
        todos = [f"{todo['content'][:40]} ({todo['status']})" for todo in args.get("todos", [])]
        return "write_todos: " + ", ".join(todos)
    if name == "task":
        return "task: " + str(args.get("description", "")).splitlines()[0][:80]
    if "file_path" in args or "path" in args:
        return f"{name} {args.get('file_path') or args.get('path')}"
    if "pattern" in args:
        return f"{name} {args['pattern']}"
    return name


def run_investigator(agent, show: Callable[[str], None] | None = print) -> InvestigationRun:
    """Run the agent on its desk. Every step is recorded, and printed as it happens.

    A failure of the model or the network is recorded in run.error, not raised, so the steps
    taken so far are never lost.
    """
    run = InvestigationRun()
    start = time.time()
    request = {"messages": [{"role": "user", "content": "Please investigate the findings."}]}
    try:
        stream = agent.stream(
            request, stream_mode="updates", subgraphs=True, config={"recursion_limit": MAX_STEPS}
        )
        for namespace, update in stream:
            if "model" not in update:
                continue  # only the model's replies hold tool calls
            indent = "      " if namespace else ""  # a helper's steps are indented
            for message in update["model"]["messages"]:
                run.model_calls += 1
                usage = (getattr(message, "response_metadata", None) or {}).get("token_usage")
                run.cost += float((usage or {}).get("cost") or 0)
                for tool_call in getattr(message, "tool_calls", []):
                    step = indent + describe_step(tool_call)
                    run.steps.append(step)
                    if show:
                        show(step)
                text = message.text if isinstance(message.text, str) else message.text()
                if not namespace and text.strip():
                    run.final_message = text.strip()
    except Exception as error:  # noqa: BLE001 - a model failure must not lose the steps so far
        run.error = f"{type(error).__name__}: {str(error)[:300]}"
    run.seconds = round(time.time() - start, 1)
    return run
