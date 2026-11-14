"""Ask a model to draft a transformation, run the draft safely, and score it.

Implements LLD section 9 (AI drafting), section 10 (Model comparison), and section 11 (The
agent that fixes its own draft). A draft is code written by a model. It is untrusted: it runs
only under the limits in this module, and it is judged only by the hand-worked test cases.
"""

import ast
import json
import os
import subprocess
import sys
import threading
import time
from typing import Literal

import duckdb
import pyarrow as pa
from pydantic import BaseModel, Field

from retail_profit_stack.config import MILESTONE_DIR
from retail_profit_stack.transform.contracts import ContractError, TransformationSpec, conform
from retail_profit_stack.transform.engines import Implementation
from retail_profit_stack.transform.engines.sql_engine import SqlEngine
from retail_profit_stack.transform.specs import SOURCE_SCHEMAS, TASKS, schema_for
from retail_profit_stack.transform.testing import (
    CaseResult,
    TransformCase,
    case_inputs,
    check_output,
    load_cases,
)

Language = Literal["sql", "pandas"]
Context = Literal["trimmed", "full"]
TIME_LIMIT_SECONDS = 10
MAX_AGENT_ATTEMPTS = 5
# A cap on what a model may write for one draft, so a model that rambles cannot run on and on.
MAX_OUTPUT_TOKENS = 12000

LANGUAGE_INSTRUCTIONS = {
    "sql": (
        "Write one SQL SELECT statement for DuckDB. Refer to the input tables by the names "
        "given. Return only the query, laid out over several lines: no semicolon, no comments, "
        "no other statements."
    ),
    "pandas": (
        "Write a Python function with this exact signature:\n"
        "    def transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame\n"
        "inputs maps each input table's name to a DataFrame. Start with 'import pandas as pd'. "
        "You may import only pandas and numpy. Do not read or write files. Return only the code."
    ),
}
# Added only when an input has a date column, so a task without dates is not told about them.
DATE_HINTS = {
    "sql": "Columns of type date are DATE values; strftime(a_date, '%Y-%m') gives the month as text.",
    "pandas": (
        "Columns of type date are datetime64 values; a_frame['a_date'].dt.strftime('%Y-%m') "
        "gives the month as text."
    ),
}
MONTH_HINT = "Columns of type month are already text like 2026-10. Use them as they are."


# ---- The task prompt --------------------------------------------------------


def describe_table(name: str) -> str:
    """A table's columns and types, as a model should read them."""
    lines = [f"Table {name}:"]
    for column in schema_for(name).columns:
        note = f"  ({column.description})" if column.description else ""
        missing = ", may be missing" if column.nullable else ""
        lines.append(f"  - {column.name}: {column.type}{missing}{note}")
    return "\n".join(lines)


def type_hints(spec: TransformationSpec, language: Language) -> str:
    """A reminder about dates and months, covering only the types this task's inputs use."""
    types = {column.type for name in spec.inputs for column in schema_for(name).columns}
    hints = [DATE_HINTS[language]] if "date" in types else []
    if "month" in types:
        hints.append(MONTH_HINT)
    return " ".join(hints)


def make_task_prompt(
    spec: TransformationSpec, language: Language, context: Context = "trimmed"
) -> str:
    """The prompt that asks for one transformation in one language.

    'trimmed' describes only the tables this transformation reads. 'full' describes every
    table in the system, as a prompt written without thinking about its size would.
    """
    if context == "full":
        others = [
            name for name in [*SOURCE_SCHEMAS, *TASKS] if name not in (*spec.inputs, spec.name)
        ]
        tables = [*spec.inputs, *others]
        note = (
            f"\nOnly these are inputs to this transformation: {', '.join(spec.inputs)}. "
            "The other tables are described for background.\n"
        )
    else:
        tables, note = list(spec.inputs), ""
    described = "\n\n".join(describe_table(name) for name in tables)
    output = "\n".join(
        f"  - {column.name}: {column.type}{', may be missing' if column.nullable else ''}"
        for column in spec.output.columns
    )
    return f"""You are a data engineer at a retailer. Write the transformation "{spec.name}".

# The rule

{spec.rule}

# Input tables

{described}
{note}
# Output

Exactly these columns, with these names:
{output}

One row for each combination of {" and ".join(spec.output.key)}. A month is text like 2026-10.
Amounts are in dollars. A missing value must be null (None or NaN), never zero.

# How to write it

{LANGUAGE_INSTRUCTIONS[language]}
{type_hints(spec, language)}
"""


class DraftImplementation(BaseModel):
    """A model's draft of one transformation."""

    reasoning: str = Field(description="Two or three sentences on the approach")
    code: str = Field(description="Only the SQL query, or only the Python code")


# ---- Running a draft under limits -------------------------------------------


class DraftRejected(ValueError):
    """A draft broke one of the limits and was not run."""


BLOCKED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "help", "memoryview",
}  # fmt: skip
BLOCKED_ATTRIBUTES = {
    "eval", "to_csv", "to_excel", "to_pickle", "to_parquet", "to_sql", "to_hdf", "to_feather",
    "to_json", "to_html", "to_clipboard", "to_latex", "to_stata", "to_xml", "to_orc", "to_gbq",
    "system", "popen", "remove", "unlink", "rmdir",
}  # fmt: skip
ALLOWED_IMPORTS = {"pandas", "numpy"}


def strip_code_fence(code: str) -> str:
    """Models often wrap code in a Markdown fence. Take the fence off."""
    code = code.strip()
    if code.startswith("```"):
        lines = code.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        code = "\n".join(lines).strip()
    return code


def check_sql(code: str) -> str:
    """Accept one SELECT statement and nothing else. Returns the statement to run."""
    code = strip_code_fence(code).rstrip(";").strip()
    try:
        statements = duckdb.extract_statements(code)
    except duckdb.Error as error:
        raise DraftRejected(f"The SQL could not be read: {str(error)[:200]}") from error
    if len(statements) != 1:
        raise DraftRejected(f"Expected one SQL statement, found {len(statements)}")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise DraftRejected("Only a SELECT statement is allowed")
    return code


def check_pandas(code: str) -> str:
    """Accept a transform function that uses only pandas and numpy. Returns the code to run."""
    code = strip_code_fence(code)
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        raise DraftRejected(f"The Python could not be read: {error}") from error
    if not any(
        isinstance(node, ast.FunctionDef) and node.name == "transform" for node in tree.body
    ):
        raise DraftRejected("The code must define a function named transform")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [(node.module or "").split(".")[0]]
        else:
            modules = []
        for module in modules:
            if module not in ALLOWED_IMPORTS:
                raise DraftRejected(
                    f"Importing '{module}' is not allowed. Use only pandas and numpy"
                )
        if isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            raise DraftRejected(f"Calling '{node.id}' is not allowed")
        if isinstance(node, ast.Attribute):
            name = node.attr
            if name.startswith(("__", "read_")) or name in BLOCKED_ATTRIBUTES:
                raise DraftRejected(f"Using '.{name}' is not allowed")
    return code


def _run_sql_draft(
    code: str, spec: TransformationSpec, cases: list[TransformCase]
) -> list[CaseResult]:
    results = []
    for case in cases:
        engine = SqlEngine(allow_external_access=False)
        timer = threading.Timer(TIME_LIMIT_SECONDS, engine.db.interrupt)
        timer.start()
        try:
            for name, table in case_inputs(case).items():
                engine.register(name, table)
            implementation = Implementation(engine="sql", name=spec.name, code=code)
            results.append(check_output(engine.run(spec, implementation), case, spec))
        except ContractError as error:
            results.append(CaseResult(case.name, False, f"Contract: {error}"))
        except Exception as error:  # noqa: BLE001 - any failure of a draft fails the case
            results.append(
                CaseResult(case.name, False, f"{type(error).__name__}: {str(error)[:300]}")
            )
        finally:
            timer.cancel()
    return results


def _run_pandas_draft(
    code: str, spec: TransformationSpec, cases: list[TransformCase]
) -> list[CaseResult]:
    payload = json.dumps({"code": code, "cases": [{"inputs": case.inputs} for case in cases]})
    environment = {**os.environ, "PYTHONPATH": str(MILESTONE_DIR)}
    try:
        finished = subprocess.run(
            [sys.executable, "-m", "retail_profit_stack.transform._pandas_worker"],
            input=payload,
            capture_output=True,
            text=True,
            env=environment,
            timeout=TIME_LIMIT_SECONDS * 2,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [
            CaseResult(case.name, False, "The code took too long and was stopped") for case in cases
        ]
    try:
        outputs = json.loads(finished.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        problem = (finished.stderr or "no output").strip().splitlines()[-1][:300]
        return [CaseResult(case.name, False, f"The code crashed: {problem}") for case in cases]

    results = []
    for case, output in zip(cases, outputs, strict=True):
        if "error" in output:
            results.append(CaseResult(case.name, False, output["error"]))
            continue
        try:
            columns = {
                name: [row.get(name) for row in output["rows"]] for name in output["columns"]
            }
            actual = conform(pa.table(columns), spec.output)
            results.append(check_output(actual, case, spec))
        except ContractError as error:
            results.append(CaseResult(case.name, False, f"Contract: {error}"))
        except (pa.ArrowException, TypeError, ValueError) as error:
            results.append(
                CaseResult(case.name, False, f"{type(error).__name__}: {str(error)[:300]}")
            )
    return results


def run_draft(code: str, language: Language, spec: TransformationSpec) -> list[CaseResult]:
    """Run a model's draft against every hand-worked case for its transformation.

    The draft is checked first, then run with limits: SQL in an in-memory database with file
    and network access switched off; pandas in a separate process. Both have a time limit.
    These limits reduce risk. They are not a perfect sandbox.
    """
    cases = load_cases(spec.name)
    try:
        if language == "sql":
            return _run_sql_draft(check_sql(code), spec, cases)
        return _run_pandas_draft(check_pandas(code), spec, cases)
    except DraftRejected as error:
        return [CaseResult(case.name, False, f"Not run: {error}") for case in cases]


def describe_results(results: list[CaseResult]) -> str:
    """Test results as text a model (or a person) can act on."""
    passed = sum(result.passed for result in results)
    lines = [f"{passed} of {len(results)} test cases passed."]
    lines += [
        f"- FAILED '{result.case}': {result.message}" for result in results if not result.passed
    ]
    return "\n".join(lines)


# ---- Asking a model, and scoring what it returns ----------------------------


class DraftResult(BaseModel):
    """One model's draft of one transformation in one language, and how it scored."""

    model: str
    language: str
    transformation: str
    context: str = "trimmed"
    cases_passed: int = 0
    cases_total: int = 0
    all_passed: bool = False
    failure: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    seconds: float = 0.0
    code: str = ""
    error: str = ""


def draft_and_score(
    client,
    model: str,
    spec: TransformationSpec,
    language: Language,
    context: Context = "trimmed",
    score: bool = True,
) -> DraftResult:
    """Ask one model for one draft, then run it against the hand-worked cases.

    client is an OpenAI client pointed at OpenRouter. A model that fails to answer gets a
    result with zero cases passed and the reason in 'error'.
    """
    total = len(load_cases(spec.name))
    result = DraftResult(
        model=model, language=language, transformation=spec.name, context=context, cases_total=total
    )
    start = time.time()
    try:
        response = client.chat.completions.parse(
            model=model,
            messages=[{"role": "user", "content": make_task_prompt(spec, language, context)}],
            response_format=DraftImplementation,
            max_tokens=MAX_OUTPUT_TOKENS,
            extra_body={"provider": {"require_parameters": True}, "usage": {"include": True}},
        )
        usage = response.usage
        result.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        result.output_tokens = getattr(usage, "completion_tokens", 0) or 0
        result.cost = float(getattr(usage, "cost", 0) or 0)
        draft = response.choices[0].message.parsed
        if draft is None or not draft.code.strip():
            result.error = "The model returned no code"
        else:
            result.code = strip_code_fence(draft.code)
    except Exception as error:  # noqa: BLE001 - a model failure is a result, not a crash
        result.error = f"{type(error).__name__}: {str(error)[:200]}"
    result.seconds = round(time.time() - start, 1)

    if result.code and score:
        results = run_draft(result.code, language, spec)
        result.cases_passed = sum(case.passed for case in results)
        result.all_passed = result.cases_passed == total
        result.failure = next((case.message for case in results if not case.passed), "")
    elif not result.code:
        result.failure = result.error
    return result


# ---- The agent that fixes its own draft -------------------------------------


class Attempt(BaseModel):
    number: int
    cases_passed: int
    cases_total: int
    code: str


class AgentDraftRun(BaseModel):
    """What happened when an agent was allowed to test and fix its own draft."""

    model: str
    language: str
    transformation: str
    attempts: list[Attempt] = Field(default_factory=list)
    all_passed: bool = False
    final_code: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    seconds: float = 0.0
    error: str = ""


AGENT_INSTRUCTIONS = f"""You are a data engineer. You will be asked to write one transformation.

You have a tool, run_tests. Give it your code and it runs the hand-worked test cases and tells
you which failed, with the expected and the actual values.

Work like this:
1. Write the code and call run_tests with it.
2. If any case failed, read the failure, fix the code, and call run_tests again.
3. Stop as soon as every case passes, or when the tool says you have no attempts left.

You have {MAX_AGENT_ATTEMPTS} attempts. Always pass the complete code to run_tests, never a fragment.
When you finish, reply with one short sentence saying whether the tests pass.
"""


def run_fix_agent(
    model,
    spec: TransformationSpec,
    language: Language,
    model_name: str = "",
    starting_code: str | None = None,
) -> AgentDraftRun:
    """Let a model write a transformation, run the tests, and fix its own failures.

    model is a LangChain chat model. Pass starting_code to hand the agent an existing draft
    to repair: that draft is tested first and recorded as attempt 1. The run is recorded
    attempt by attempt. Code from the agent is a draft like any other: passing the tests
    makes it a candidate for review.
    """
    from langchain.agents import create_agent  # imported here so the rest works without it
    from langchain_core.tools import StructuredTool

    run = AgentDraftRun(
        model=model_name or getattr(model, "model_name", type(model).__name__),
        language=language, transformation=spec.name,
    )  # fmt: skip

    def run_tests(code: str) -> str:
        """Run the hand-worked test cases on your code and report which passed and which failed."""
        if len(run.attempts) >= MAX_AGENT_ATTEMPTS:
            return "You have no attempts left. Stop now."
        code = strip_code_fence(code)
        results = run_draft(code, language, spec)
        passed = sum(result.passed for result in results)
        run.attempts.append(Attempt(
            number=len(run.attempts) + 1, cases_passed=passed, cases_total=len(results), code=code
        ))  # fmt: skip
        if passed == len(results):
            run.all_passed, run.final_code = True, code
            return "Every test case passed. You are done."
        left = MAX_AGENT_ATTEMPTS - len(run.attempts)
        return f"{describe_results(results)}\nYou have {left} attempts left."

    request = make_task_prompt(spec, language)
    if starting_code is not None:
        # The draft to repair counts as the first attempt, so the record shows where it started.
        report = run_tests(starting_code)
        request += (
            "\n# A draft to fix\n\nA colleague wrote this draft. It has been run against the "
            f"test cases:\n\n{run.attempts[0].code}\n\n{report}\n\nFix it."
        )

    agent = create_agent(
        model=model,
        tools=[StructuredTool.from_function(run_tests)],
        system_prompt=AGENT_INSTRUCTIONS,
    )
    start = time.time()
    try:
        if run.all_passed:
            return run  # the draft already passes; there is nothing to fix
        result = agent.invoke(
            {"messages": [{"role": "user", "content": request}]},
            {"recursion_limit": 4 * MAX_AGENT_ATTEMPTS + 6},
        )
        for message in result["messages"]:
            usage = getattr(message, "usage_metadata", None) or {}
            run.input_tokens += usage.get("input_tokens", 0)
            run.output_tokens += usage.get("output_tokens", 0)
            details = (getattr(message, "response_metadata", None) or {}).get("token_usage") or {}
            run.cost += float(details.get("cost") or 0)
    except Exception as error:  # noqa: BLE001 - a model failure must not lose the attempts so far
        run.error = f"{type(error).__name__}: {str(error)[:200]}"
    if not run.final_code and run.attempts:
        run.final_code = max(run.attempts, key=lambda attempt: attempt.cases_passed).code
    run.seconds = round(time.time() - start, 1)
    return run
