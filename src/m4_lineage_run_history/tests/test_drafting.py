"""LLD sections 9 to 11: prompts, the limits on running drafts, scoring, and the agent."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from helpers import ScriptedChatModel
from retail_profit_stack.transform import drafting
from retail_profit_stack.transform.engines.base import IMPLEMENTATIONS_DIR
from retail_profit_stack.transform.specs import ALL_IN_ONE, SPECS, TASKS

GOOD_SQL = (IMPLEMENTATIONS_DIR / "sql" / "sales.sql").read_text("utf-8")
GOOD_PANDAS = (IMPLEMENTATIONS_DIR / "pandas" / "sales.py").read_text("utf-8")
# Forgets to leave out cancelled orders
WRONG_SQL = GOOD_SQL.replace("WHERE o.status <> 'cancelled'", "")


def passed(results):
    return [result.passed for result in results]


@pytest.mark.parametrize("task", list(TASKS))
def test_the_reference_implementations_pass_when_run_as_drafts(task):
    sql = (IMPLEMENTATIONS_DIR / "sql" / f"{task}.sql").read_text("utf-8")
    python = (IMPLEMENTATIONS_DIR / "pandas" / f"{task}.py").read_text("utf-8")
    assert all(passed(drafting.run_draft(sql, "sql", TASKS[task])))
    assert all(passed(drafting.run_draft(python, "pandas", TASKS[task])))


def test_a_wrong_draft_fails_the_case_it_gets_wrong_with_a_useful_message():
    results = {
        result.case: result for result in drafting.run_draft(WRONG_SQL, "sql", SPECS["sales"])
    }
    assert not results["a cancelled order is left out"].passed
    assert "units_sold: expected 1, got 4" in results["a cancelled order is left out"].message
    assert results["a plain order"].passed


def test_a_draft_that_joins_detail_to_detail_is_caught():
    fan_out = (
        (IMPLEMENTATIONS_DIR / "sql" / "profit_all_in_one.sql")
        .read_text("utf-8")
        .replace(
            "FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id",
            "FROM order_items AS i JOIN orders AS o ON o.order_id = i.order_id "
            "LEFT JOIN refunds AS x ON x.order_item_id = i.order_item_id",
        )
    )
    results = {result.case: result for result in drafting.run_draft(fan_out, "sql", ALL_IN_ONE)}
    assert not results["everything at once"].passed
    assert "units_sold: expected 2, got 4" in results["everything at once"].message


def test_a_code_fence_around_a_draft_is_removed():
    assert all(passed(drafting.run_draft(f"```sql\n{GOOD_SQL}\n```", "sql", SPECS["sales"])))
    assert all(
        passed(drafting.run_draft(f"```python\n{GOOD_PANDAS}\n```", "pandas", SPECS["sales"]))
    )


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("DROP TABLE orders", "Only a SELECT statement is allowed"),
        ("SELECT 1; SELECT 2", "Expected one SQL statement, found 2"),
        ("COPY orders TO 'out.csv'", "Only a SELECT statement is allowed"),
        ("SELECT * FROM read_csv('/etc/hosts')", "file system operations are disabled"),
        ("SELECT FROM WHERE", "could not be read"),
    ],
)
def test_unsafe_or_unreadable_sql_is_not_trusted(code, reason):
    results = drafting.run_draft(code, "sql", SPECS["sales"])
    assert not any(passed(results)) and reason in results[0].message


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (
            "import os\ndef transform(inputs):\n    return os.getcwd()",
            "Importing 'os' is not allowed",
        ),
        (
            "from subprocess import run\ndef transform(inputs):\n    return 1",
            "Importing 'subprocess'",
        ),
        (
            "import pandas as pd\ndef transform(inputs):\n    return pd.read_csv('x')",
            "'.read_csv' is not allowed",
        ),
        (
            "import pandas as pd\ndef transform(inputs):\n    inputs['orders'].to_csv('x')",
            "'.to_csv' is not allowed",
        ),
        (
            "import pandas as pd\ndef transform(inputs):\n    return open('x')",
            "Calling 'open' is not allowed",
        ),
        (
            "import pandas as pd\ndef transform(inputs):\n    return eval('1')",
            "Calling 'eval' is not allowed",
        ),
        (
            "import pandas as pd\ndef transform(inputs):\n    return pd.__builtins__",
            "'.__builtins__' is not allowed",
        ),
        (
            "import pandas as pd\ndef calculate(inputs):\n    return 1",
            "must define a function named transform",
        ),
        ("def transform(inputs:\n    return 1", "could not be read"),
    ],
)
def test_unsafe_or_unreadable_pandas_code_is_not_run(code, reason):
    results = drafting.run_draft(code, "pandas", SPECS["sales"])
    assert not any(passed(results)) and reason in results[0].message


def test_pandas_code_that_never_finishes_is_stopped(monkeypatch):
    monkeypatch.setattr(drafting, "TIME_LIMIT_SECONDS", 1)
    looping = "import pandas as pd\ndef transform(inputs):\n    while True:\n        pass"
    results = drafting.run_draft(looping, "pandas", SPECS["sales"])
    assert "took too long" in results[0].message


def test_pandas_code_that_raises_fails_its_cases_without_crashing_the_caller():
    broken = "import pandas as pd\ndef transform(inputs):\n    return inputs['no_such_table']"
    results = drafting.run_draft(broken, "pandas", SPECS["sales"])
    assert not any(passed(results)) and "KeyError" in results[0].message


def test_the_trimmed_prompt_describes_only_the_inputs_and_the_full_prompt_describes_everything():
    trimmed = drafting.make_task_prompt(SPECS["product_cost"], "sql")
    full = drafting.make_task_prompt(SPECS["product_cost"], "sql", "full")
    assert "Table sales:" in trimmed and "Table product_costs:" in trimmed
    assert "Table shipments:" not in trimmed and "Table shipments:" in full
    assert len(full) > 2 * len(trimmed)
    assert (
        SPECS["product_cost"].rule in trimmed and "product_cost: decimal, may be missing" in trimmed
    )


def test_the_prompt_changes_with_the_language():
    assert "one SQL SELECT statement" in drafting.make_task_prompt(SPECS["sales"], "sql")
    assert "def transform(inputs" in drafting.make_task_prompt(SPECS["sales"], "pandas")


def stub_client(code, cost=0.0012, fail=False):
    """An OpenRouter client stand-in that returns one fixed draft."""

    def parse(**_):
        if fail:
            raise TimeoutError("the model did not reply")
        parsed = drafting.DraftImplementation(reasoning="Sum then group.", code=code)
        usage = SimpleNamespace(prompt_tokens=400, completion_tokens=90, cost=cost)
        return SimpleNamespace(
            usage=usage, choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))]
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))


def test_a_draft_is_scored_with_its_tokens_and_cost():
    result = drafting.draft_and_score(stub_client(GOOD_SQL), "some/model", SPECS["sales"], "sql")
    assert (result.cases_passed, result.cases_total, result.all_passed) == (5, 5, True)
    assert (result.input_tokens, result.output_tokens, result.cost) == (400, 90, 0.0012)
    assert result.failure == "" and result.code.startswith("-- sales")


def test_a_wrong_draft_is_scored_with_its_first_failure():
    result = drafting.draft_and_score(stub_client(WRONG_SQL), "some/model", SPECS["sales"], "sql")
    assert (result.cases_passed, result.all_passed) == (4, False)
    assert "units_sold" in result.failure


def test_a_model_that_fails_to_answer_scores_zero_and_keeps_the_reason():
    result = drafting.draft_and_score(
        stub_client("", fail=True), "some/model", SPECS["sales"], "sql"
    )
    assert (result.cases_passed, result.cases_total) == (0, 5)
    assert "TimeoutError" in result.error and "TimeoutError" in result.failure


def scripted_agent_model(*codes):
    """A fake model that calls run_tests with each code in turn, then finishes."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"name": "run_tests", "args": {"code": code}, "id": f"call-{index}"}],
        )
        for index, code in enumerate(codes)
    ]
    messages.append(AIMessage(content="Done."))
    return ScriptedChatModel(messages=iter(messages))


def test_the_agent_retries_a_failing_draft_and_the_run_is_recorded():
    run = drafting.run_fix_agent(
        scripted_agent_model(WRONG_SQL, GOOD_SQL), SPECS["sales"], "sql", "fake/model"
    )
    assert [(a.number, a.cases_passed) for a in run.attempts] == [(1, 4), (2, 5)]
    assert run.all_passed and run.final_code == drafting.strip_code_fence(GOOD_SQL)
    assert run.model == "fake/model" and run.error == ""


def test_the_agent_can_be_handed_a_failing_draft_to_repair():
    run = drafting.run_fix_agent(
        scripted_agent_model(GOOD_SQL), SPECS["sales"], "sql", "fake/model", starting_code=WRONG_SQL
    )
    assert [(a.number, a.cases_passed) for a in run.attempts] == [(1, 4), (2, 5)]
    assert run.all_passed and run.final_code == drafting.strip_code_fence(GOOD_SQL)


def test_a_draft_that_already_passes_needs_no_model_call():
    run = drafting.run_fix_agent(
        scripted_agent_model(), SPECS["sales"], "sql", "fake/model", starting_code=GOOD_SQL
    )
    assert len(run.attempts) == 1 and run.all_passed and run.input_tokens == 0


def test_an_agent_that_never_passes_keeps_its_best_attempt_and_stops_at_the_limit():
    codes = [WRONG_SQL] * (drafting.MAX_AGENT_ATTEMPTS + 2)
    run = drafting.run_fix_agent(scripted_agent_model(*codes), SPECS["sales"], "sql")
    assert len(run.attempts) == drafting.MAX_AGENT_ATTEMPTS
    assert not run.all_passed and run.final_code == drafting.strip_code_fence(WRONG_SQL)
