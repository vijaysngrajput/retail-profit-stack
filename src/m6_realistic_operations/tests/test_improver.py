"""LLD sections 6 to 9: question sets, the judge, the end-to-end evaluation, and the improver."""

import pandas as pd
import pytest
from langchain_core.messages import AIMessage

from retail_profit_stack import tools
from retail_profit_stack.analyst_versions import (
    current_version,
    read_versions,
    save_version,
    set_current,
    version_one,
)
from retail_profit_stack.e2e import STAGE_RUN, build_everything, open_stores, summary
from retail_profit_stack.evaluation import load_set
from retail_profit_stack.improver import (
    ALLOWED_MODELS,
    NOISE,
    OBJECTIVES,
    Session,
    compare_scores,
    make_tools,
    verdict,
)
from retail_profit_stack.judge import GRADES, Grade, grade_explanation, reference_reason
from retail_profit_stack.verify import build_fact_index, same_value


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    """The whole system built from nothing: files, close, late files. No model is needed."""
    return build_everything(tmp_path_factory.mktemp("e2e") / "workspace")


@pytest.fixture(scope="module")
def stores(workspace):
    return open_stores(workspace)


# ---- The end-to-end build and the question sets (LLD section 6) ----


def test_the_build_goes_from_files_to_three_runs(workspace, stores):
    assert len(list(workspace.places.landing.glob("*.csv"))) == 50
    assert len(list(workspace.late.glob("*.csv"))) == 3
    assert {stage: store.run_id for stage, store in stores.items()} == STAGE_RUN


def test_the_two_question_sets():
    evaluation, held_out = load_set("evaluation"), load_set("held-out")
    assert (len(evaluation), len(held_out)) == (18, 10)
    assert [case.case_id for case in evaluation if case.stage == "late"] == [
        "E15",
        "E16",
        "E17",
        "E18",
    ]
    assert [case.case_id for case in held_out if case.stage == "late"] == ["H9", "H10"]
    assert not {case.question for case in evaluation} & {case.question for case in held_out}
    assert len(load_set("held-out", tiny=True)) == 5


@pytest.mark.parametrize("set_name", ["evaluation", "held-out"])
def test_every_expected_figure_agrees_with_the_tools_in_its_stage(stores, set_name):
    for case in load_set(set_name):
        store = stores[case.stage]
        log = []
        for metric in {figure.metric for figure in case.expected_figures}:
            for group in ("product", "category"):
                for month in store.months():
                    result = tools.query_profit(month, group, metric, store=store)
                    log.append(_call("query_profit", result))
                months = store.months()
                changed = tools.compare_profit(months[-1], months[0], group, metric, store=store)
                log.append(_call("compare_profit", changed))
            log.append(_call("compare_runs", tools.compare_runs(metric=metric, store=store)))
            unchanged = [f for f in case.expected_figures if f.kind == "value"]
            for figure in unchanged:
                if figure.entity_id.startswith("P0"):
                    result = tools.compare_runs(figure.month, figure.entity_id, metric, store=store)
                    log.append(_call("compare_runs", result))
        facts = build_fact_index(log)
        for expected in case.expected_figures:
            values = facts[(expected.metric, expected.kind, expected.month, expected.entity_id)]
            assert any(same_value(expected.value, value) for value in values), (
                case.case_id,
                expected,
            )


def _call(name, result):
    from retail_profit_stack.schemas import ToolCall

    return ToolCall(name=name, arguments={}, result=result.model_dump())


# ---- The judge (LLD section 7) ----


class FakeJudge:
    """A judge that always gives one grade, with no network."""

    def __init__(self, grade):
        self.grade = grade

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, messages):
        raw = AIMessage(content="", response_metadata={"token_usage": {"cost": 0.0001}})
        return {"raw": raw, "parsed": Grade(why="as told", grade=self.grade)}


def test_the_reference_names_the_real_reason_in_each_stage(stores):
    close = reference_reason(tools.compare_runs("2026-10", "P001", store=stores["close"]))
    assert "duplicated records are now set aside" in close and "5188.2" in close
    late = reference_reason(tools.compare_runs("2026-09", "P012", store=stores["late"]))
    assert "refunds_2026-11-09.csv" in late and "1 new refunds records" in late
    corrected = reference_reason(tools.compare_runs("2026-10", "P001", store=stores["late"]))
    assert "corrected file" in corrected and "shipments_2026-10-19.csv" in corrected
    same = reference_reason(tools.compare_runs("2026-10", "P008", store=stores["late"]))
    assert same.startswith("The figure did not change")


def test_a_grade_is_a_letter_a_number_and_a_cost():
    verdict_, cost = grade_explanation(FakeJudge("B"), "why?", "the reason", "an explanation")
    assert (verdict_.grade, GRADES[verdict_.grade], cost) == ("B", 2, 0.0001)
    assert GRADES == {"F": 0, "C": 1, "B": 2, "A": 3}


def test_summary_averages_only_the_judged_questions():
    table = pd.DataFrame([
        {"right": True, "grade": 3, "mistake_cost": 0, "model_cost": 0.002, "seconds": 4.0},
        {"right": False, "grade": None, "mistake_cost": 200, "model_cost": 0.002, "seconds": 6.0},
        {"right": True, "grade": 1, "mistake_cost": 0, "model_cost": 0.002, "seconds": 5.0},
    ])  # fmt: skip
    scores = summary(table)
    assert (scores["accuracy"], scores["grade"], scores["cost_of_mistakes"]) == (0.667, 2.0, 200.0)
    assert (scores["cost_per_question"], scores["seconds_per_question"]) == (0.002, 5.0)


# ---- Analyst versions (LLD section 8) ----


def test_versions_are_added_made_current_and_rolled_back(tmp_path):
    file = tmp_path / "versions.json"
    assert current_version(file) == version_one() and len(read_versions(file)) == 1
    saved = save_version("new instructions", ALLOWED_MODELS[0], "a test", file)
    assert saved["version"] == 2 and current_version(file)["version"] == 1  # not in use yet
    set_current(2, file)
    assert current_version(file)["instructions"] == "new instructions"
    set_current(1, file)  # a rollback
    assert current_version(file) == version_one()
    with pytest.raises(ValueError, match="no version 9"):
        set_current(9, file)


# ---- The improver's rules: code decides (LLD section 9) ----

BASE = {"accuracy": 0.9, "grade": 2.5, "cost_per_question": 0.002, "seconds_per_question": 6.0}


@pytest.mark.parametrize(
    ("change", "kept", "word"),
    [
        ({}, False, "no score improved"),
        ({"accuracy": 0.95}, False, "no score improved"),  # inside the noise
        ({"accuracy": 1.0 + 0.01}, True, "better on accuracy"),
        ({"cost_per_question": 0.0015}, True, "better on cost_per_question"),
        ({"seconds_per_question": 4.0}, False, "no score improved"),  # time has a wide margin
        ({"seconds_per_question": 2.5}, True, "better on seconds_per_question"),
        ({"cost_per_question": 0.0015, "accuracy": 0.75}, False, "clearly worse on accuracy"),
        ({"cost_per_question": 0.001, "accuracy": 0.6, "grade": 3.0}, False, "below the business objective"),
    ],
)  # fmt: skip
def test_the_verdict(change, kept, word):
    decided, why = verdict({**BASE, **change}, BASE)
    assert decided is kept and word in why, why


def test_noise_and_objectives_are_what_the_documents_say():
    assert compare_scores(BASE, BASE) == ([], [])
    assert NOISE["seconds_per_question"] > NOISE["cost_per_question"]
    assert OBJECTIVES == {"accuracy": 0.7, "grade": 2.0}


def a_session(scores_by_version, budget=0.6):
    """A session whose evaluations are scripted: each version always gets the given scores."""

    def evaluate(config, set_name):
        scores = {**scores_by_version[config["version"]], "cost_of_mistakes": 0.0, "spent": 0.05}
        table = pd.DataFrame([{
            "question": "q", "headline": "h", "right": False, "grade": None, "letter": "",
            "judge_says": "", "mistake": "stopped_by_verifier", "failed_checks": ["figures_listed"],
        }])  # fmt: skip
        return scores, table

    session = Session(evaluate=evaluate, versions=[version_one()], budget=budget)
    session.measure(1, "evaluation")
    session.measure(1, "held-out")
    session.measure(1, "held-out")
    return session


def tool(session, name):
    return next(item for item in make_tools(session) if item.name == name)


def test_a_better_version_is_kept_and_a_worse_one_is_rolled_back():
    better = {**BASE, "accuracy": 1.0 + 0.01}
    session = a_session({1: BASE, 2: better, 3: {**BASE, "accuracy": 0.5}})
    assert "no new version" in tool(session, "run_evaluation").invoke({})
    args = {"instructions": "v2", "model": ALLOWED_MODELS[0], "reason": "r"}
    assert "version 2" in tool(session, "propose_change").invoke(args)
    assert session.current == 1  # proposing does not put a version into use
    assert "Kept" in tool(session, "run_evaluation").invoke({})
    assert session.current == 2 and session.rounds[0]["kept"] is True
    tool(session, "propose_change").invoke({**args, "instructions": "v3"})
    assert "Rolled back" in tool(session, "run_evaluation").invoke({})
    assert session.current == 2 and session.rounds[1]["kept"] is False
    assert len(session.scoreboard) == 9  # three runs per version, each counted


def test_a_model_that_is_not_allowed_is_refused_and_the_budget_stops_evaluations():
    session = a_session({1: BASE, 2: BASE}, budget=0.1)  # the baseline already cost 0.15
    args = {"instructions": "v2", "model": "some/expensive-model", "reason": "r"}
    assert "is not allowed" in tool(session, "propose_change").invoke(args)
    tool(session, "propose_change").invoke({**args, "model": ALLOWED_MODELS[1]})
    assert "budget" in tool(session, "run_evaluation").invoke({}) and session.current == 1
    assert len(session.scoreboard) == 3  # nothing more was run


def test_the_improver_reads_mistakes_from_the_evaluation_set_only():
    import json

    session = a_session({1: BASE})
    report = json.loads(tool(session, "read_results").invoke({}))
    assert report["mistakes_on_evaluation_set"][0]["failed_checks"] == ["figures_listed"]
    assert "held_out" not in json.dumps(report["mistakes_on_evaluation_set"])
    assert set(report) >= {"objectives", "budget_left", "models_allowed", "scores_on_held_out_set"}
    tool(session, "propose_recipe").invoke({"recipe": "a new recipe", "reason": "r"})
    assert session.recipes[-1] == "a new recipe"
