"""Runs one pandas draft against test cases, in a process of its own.

Used by drafting.run_draft. The parent process sends the draft's code and the cases as JSON
on standard input, and reads the outputs as JSON from standard output. Running the draft here
keeps a crash, a hang, or a mistake in the draft away from the notebook or test that asked.
"""

import json
import sys

import pandas as pd

from retail_profit_stack.transform.contracts import table_from_rows
from retail_profit_stack.transform.engines.pandas_engine import to_frame
from retail_profit_stack.transform.specs import schema_for


def main() -> None:
    payload = json.loads(sys.stdin.read())
    namespace: dict = {}
    outputs = []
    try:
        exec(compile(payload["code"], "<draft>", "exec"), namespace)  # noqa: S102 - checked by the parent
        transform = namespace["transform"]
    except Exception as error:  # noqa: BLE001
        problem = f"{type(error).__name__}: {error}"
        print(json.dumps([{"error": problem} for _ in payload["cases"]]))
        return

    for case in payload["cases"]:
        try:
            inputs = {
                name: to_frame(table_from_rows(rows, schema_for(name)))
                for name, rows in case["inputs"].items()
            }
            result = transform(inputs)
            if not isinstance(result, pd.DataFrame):
                raise TypeError(f"transform must return a DataFrame, got {type(result).__name__}")
            rows = json.loads(result.to_json(orient="records", date_format="iso") or "[]")
            outputs.append({"columns": [str(column) for column in result.columns], "rows": rows})
        except Exception as error:  # noqa: BLE001
            outputs.append({"error": f"{type(error).__name__}: {str(error)[:300]}"})
    print(json.dumps(outputs))


if __name__ == "__main__":
    main()
