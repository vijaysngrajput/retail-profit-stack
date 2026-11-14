"""Run an implementation against the hand-worked test cases.

Implements LLD section 8 (Hand-worked test cases). A case is a tiny set of input tables
written out in full, and the output worked out by hand. The cases define what "correct" means
for a transformation, on every engine and whoever wrote the implementation.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa

from retail_profit_stack.config import EVALS_DIR
from retail_profit_stack.transform.contracts import (
    ContractError,
    TransformationSpec,
    table_from_rows,
    tables_differ,
)
from retail_profit_stack.transform.engines import Implementation, get_engine
from retail_profit_stack.transform.specs import schema_for

CASES_FILE = EVALS_DIR / "m2_transform_cases.json"


@dataclass(frozen=True)
class TransformCase:
    transformation: str
    name: str
    why: str
    inputs: dict[str, list[dict]]
    expected: list[dict]


@dataclass(frozen=True)
class CaseResult:
    case: str
    passed: bool
    message: str = ""


def load_cases(transformation: str | None = None, path: Path = CASES_FILE) -> list[TransformCase]:
    """The hand-worked cases, for one transformation or for all of them."""
    cases = [TransformCase(**item) for item in json.loads(path.read_text("utf-8"))]
    return [case for case in cases if transformation in (None, case.transformation)]


def case_inputs(case: TransformCase) -> dict[str, pa.Table]:
    """A case's input rows as tables with the right column types."""
    return {name: table_from_rows(rows, schema_for(name)) for name, rows in case.inputs.items()}


def check_output(actual: pa.Table, case: TransformCase, spec: TransformationSpec) -> CaseResult:
    """Compare an output, already in the standard form, with the case's expected rows."""
    difference = tables_differ(actual, table_from_rows(case.expected, spec.output))
    return CaseResult(case=case.name, passed=difference is None, message=difference or "")


def run_cases(
    spec: TransformationSpec, engine_name: str, implementation: Implementation | None = None
) -> list[CaseResult]:
    """Run one implementation on every case for its transformation. Trusted code only.

    Code written by a model must go through drafting.run_draft, which applies limits first.
    """
    results = []
    for case in load_cases(spec.name):
        engine = get_engine(engine_name)
        try:
            for name, table in case_inputs(case).items():
                engine.register(name, table)
            results.append(check_output(engine.run(spec, implementation), case, spec))
        except ContractError as error:
            results.append(CaseResult(case=case.name, passed=False, message=f"Contract: {error}"))
        except Exception as error:  # noqa: BLE001 - any failure of the implementation fails the case
            message = f"{type(error).__name__}: {str(error)[:300]}"
            results.append(CaseResult(case=case.name, passed=False, message=message))
    return results
