"""The improver: an agent that proposes changes to the analyst, under control.

Implements LLD section 9 (The improver). The improver reads the analyst's results and
proposes a new version of the analyst's instructions or model. A person approves or refuses
each proposal. Code runs the evaluation and keeps the new version or rolls it back.

The settings at the top belong to the business. The improver cannot change them, cannot see
the held-out questions, and cannot touch the tools or the verifier.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from retail_profit_stack.config import DEFAULT_MODEL

# ---- The business's settings. The improver can read them and cannot change them. ----

# A version is only kept if it meets these on the held-out questions.
OBJECTIVES = {"accuracy": 0.7, "grade": 2.0}
# How far a score must improve before we count it. Scores move this much by chance.
# Time gets a wide margin: when the lab was built, the same version took 4.8 and then 10.8
# seconds a question in two runs, because one model call stalled.
NOISE = {"accuracy": 0.1, "grade": 0.3, "cost_per_question": 0.15, "seconds_per_question": 0.5}
# How far a score may get worse in a version that improves another.
TOLERANCE = {"accuracy": 0.1, "grade": 0.3, "cost_per_question": 0.5, "seconds_per_question": 1.0}
BUDGET = 0.60  # US dollars the improver's evaluations may cost in one session
ALLOWED_MODELS = [DEFAULT_MODEL, "google/gemma-4-31b-it"]

FIRST_RECIPE = """1. Call read_results to see how the current version is doing.
2. If the evaluation shows mistakes, find what several of them have in common, and write one \
general rule that would prevent it. Do not write a rule about one named product or question.
3. If there are no mistakes, make the analyst cheaper or faster: shorten its instructions \
without removing any rule, or choose a cheaper model from the models allowed.
4. Call propose_change with the complete new instructions, the model, and your reason. A \
person reviews it. If they refuse, read their reason and propose something different.
5. Call run_evaluation. Code decides whether the version is kept or rolled back.
6. Call propose_recipe with a better version of this recipe, using what this round showed.
7. Reply with two sentences: what you changed, and what happened."""

IMPROVER_INTRO = """You improve the profit analyst of Kestrel Ridge Outfitters, a fictional \
retailer. The analyst is an AI agent whose behaviour is set by its instructions and its model. \
You may change only those two. Follow your recipe exactly, one step at a time.

Your recipe:
"""


@dataclass
class Session:
    """Everything one improvement session keeps: versions, scores, rounds, and what it spent.

    evaluate is a function that runs one version on one question set and returns its scores
    and its table of answers. The lab and the tests pass their own.
    """

    evaluate: Callable[[dict, str], tuple[dict, pd.DataFrame]]
    versions: list[dict]
    current: int = 1
    budget: float = BUDGET
    spent: float = 0.0
    scoreboard: list[dict] = field(default_factory=list)
    tables: dict = field(default_factory=dict)
    rounds: list[dict] = field(default_factory=list)
    recipes: list[str] = field(default_factory=lambda: [FIRST_RECIPE])

    def version(self, number: int) -> dict:
        return next(item for item in self.versions if item["version"] == number)

    def measure(self, number: int, set_name: str) -> dict:
        """Run one version on one set, add the scores to the scoreboard, and count the cost."""
        scores, table = self.evaluate(self.version(number), set_name)
        self.spent += scores["spent"]
        row = {"version": number, "set": set_name, **scores}
        self.scoreboard.append(row)
        self.tables[(number, set_name)] = table
        return row

    def average(self, number: int, set_name: str) -> dict:
        """The average of a version's scores over all its runs on one set."""
        runs = [
            row for row in self.scoreboard if (row["version"], row["set"]) == (number, set_name)
        ]
        names = ["accuracy", "grade", "cost_per_question", "seconds_per_question"]
        return {name: sum(run[name] for run in runs) / len(runs) for name in names}


def compare_scores(new: dict, old: dict) -> tuple[list[str], list[str]]:
    """Which scores got better by more than the noise, and which got worse by more than the tolerance.

    Accuracy and grade are compared as a difference. Cost and time are compared as a share of
    the old value, so 0.15 means 15%.
    """
    better, worse = [], []
    for name in ("accuracy", "grade"):
        if new[name] > old[name] + NOISE[name]:
            better.append(name)
        if new[name] < old[name] - TOLERANCE[name]:
            worse.append(name)
    for name in ("cost_per_question", "seconds_per_question"):
        if new[name] < old[name] * (1 - NOISE[name]):
            better.append(name)
        if new[name] > old[name] * (1 + TOLERANCE[name]):
            worse.append(name)
    return better, worse


def verdict(new: dict, old: dict) -> tuple[bool, str]:
    """Whether a new version is kept, and why, in one sentence. Code decides this."""
    below = [name for name, floor in OBJECTIVES.items() if new[name] < floor]
    if below:
        return False, f"Rolled back: below the business objective for {', '.join(below)}."
    better, worse = compare_scores(new, old)
    if worse:
        return False, f"Rolled back: clearly worse on {', '.join(worse)}."
    if not better:
        return False, "Rolled back: no score improved by more than chance."
    return True, f"Kept: better on {', '.join(better)}, and nothing clearly worse."


def make_tools(session: Session) -> list[StructuredTool]:
    """The improver's four tools. They read results and propose; code does the rest."""

    def read_results() -> str:
        """Read the analyst's current version, its scores, its mistakes on the evaluation set, the earlier rounds, the objectives, the budget, and the models allowed."""
        current = session.version(session.current)
        table = session.tables.get((session.current, "evaluation"))
        mistakes = []
        if table is not None:
            for row in table.to_dict(orient="records"):
                if not row["right"] or (row["grade"] is not None and row["grade"] < 3):
                    mistakes.append({
                        "question": row["question"], "the_analyst_said": row["headline"],
                        "mistake": row["mistake"], "failed_checks": row["failed_checks"],
                        "judge_grade": row["letter"], "judge_says": row["judge_says"],
                    })  # fmt: skip
        report = {
            "current_version": current,
            "scores_on_evaluation_set": session.average(session.current, "evaluation"),
            "scores_on_held_out_set": session.average(session.current, "held-out"),
            "mistakes_on_evaluation_set": mistakes,
            "earlier_rounds": session.rounds,
            "objectives": OBJECTIVES,
            "budget_left": round(session.budget - session.spent, 4),
            "models_allowed": ALLOWED_MODELS,
        }
        return json.dumps(report, indent=1)

    def propose_change(instructions: str, model: str, reason: str) -> str:
        """Propose a new version of the analyst. A person reviews it before it is saved.

        instructions is the analyst's complete new instructions. model is one of the models
        allowed. reason says what you changed and why, in two sentences.
        """
        if model not in ALLOWED_MODELS:
            return f"{model} is not allowed. Choose one of: {', '.join(ALLOWED_MODELS)}"
        number = len(session.versions) + 1
        session.versions.append(
            {"version": number, "instructions": instructions, "model": model, "reason": reason}
        )
        return f"Saved as version {number}. It is not in use yet. Call run_evaluation."

    def run_evaluation() -> str:
        """Run the newest version once on the evaluation set and twice on the held-out set. Code then keeps it or rolls it back."""
        newest = session.versions[-1]["version"]
        if newest == session.current or any(r["version"] == newest for r in session.rounds):
            return "There is no new version to evaluate. Call propose_change first."
        if session.spent >= session.budget:
            return f"The budget of ${session.budget:.2f} is spent. No more evaluations can run."
        session.measure(newest, "evaluation")
        session.measure(newest, "held-out")
        session.measure(newest, "held-out")
        new = session.average(newest, "held-out")
        old = session.average(session.current, "held-out")
        kept, why = verdict(new, old)
        session.rounds.append({
            "round": len(session.rounds) + 1, "version": newest, "kept": kept, "verdict": why,
            "recipe_version": len(session.recipes), "model": session.versions[-1]["model"],
            "held_out_before": old, "held_out_after": new,
        })  # fmt: skip
        if kept:
            session.current = newest
        return json.dumps({
            "verdict": why, "current_version": session.current,
            "held_out_before": old, "held_out_after": new,
            "scores_on_evaluation_set": session.average(newest, "evaluation"),
        })  # fmt: skip

    def propose_recipe(recipe: str, reason: str) -> str:
        """Propose a new version of your own recipe. A person reviews it before it is saved.

        recipe is the complete new recipe. reason says what this round showed and why the new
        recipe should work better.
        """
        session.recipes.append(recipe)
        return f"Saved as recipe {len(session.recipes)}. The next round will use it."

    functions = [read_results, propose_change, run_evaluation, propose_recipe]
    return [StructuredTool.from_function(function) for function in functions]


def make_improver(session: Session, model):
    """The improver agent, with the newest recipe as its instructions.

    HumanInTheLoopMiddleware pauses the agent whenever it calls propose_change or
    propose_recipe, until a person approves or rejects the call. The pause needs a
    checkpointer, as in milestone 5.
    """
    approval = HumanInTheLoopMiddleware(
        interrupt_on={
            "propose_change": {"allowed_decisions": ["approve", "reject"]},
            "propose_recipe": {"allowed_decisions": ["approve", "reject"]},
        }
    )
    return create_agent(
        model=model,
        tools=make_tools(session),
        system_prompt=IMPROVER_INTRO + session.recipes[-1],
        middleware=[approval],
        checkpointer=InMemorySaver(),
    )


def waiting_proposal(result: dict) -> dict | None:
    """The tool call the improver is waiting for approval on, or None if it has finished."""
    interrupts = result.get("__interrupt__")
    if not interrupts:
        return None
    request = interrupts[0].value["action_requests"][0]
    return {"tool": request["name"], "args": request["args"]}
