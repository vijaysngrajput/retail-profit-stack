"""The live pipeline: a small local program that runs the production code for a web page.

This is not a milestone. It lets you choose which files arrive, then runs the real production
pipeline on them and reports every step to the page in pipeline_live/index.html.

Run it from the project root with:   uv run python pipeline_live/server.py
Then open:                           http://localhost:8765

It uses the production package of ONE milestone, named in MILESTONE below. It works in a
folder of its own (pipeline_live/workspace/), so it never changes that milestone's data.
"""

import json
import math
import os
import shutil
import sys
import threading
import time
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pyarrow.parquet as pq
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
MILESTONE = HERE.parent / "src" / "m6_realistic_operations"  # the production code this page runs
sys.path.insert(0, str(MILESTONE))

from retail_profit_stack import tools
from retail_profit_stack.agent import ENV_FILE
from retail_profit_stack.config import LANDING_DIR, LATE_DIR
from retail_profit_stack.ingest import ledger
from retail_profit_stack.ingest.dispatch import build_dispatcher
from retail_profit_stack.ingest.feeds import Places, feed_of
from retail_profit_stack.ingest.mapping import earlier_rows, sample_rows
from retail_profit_stack.ingest.rules import read_header
from retail_profit_stack.ingest.workflow import (
    answer,
    build_file_workflow,
    run_file,
    waiting_files,
)
from retail_profit_stack.lineage.compare import compare_runs
from retail_profit_stack.lineage.lineage import record_counts
from retail_profit_stack.lineage.runs import fingerprint, read_history
from retail_profit_stack.quality.review import decide, open_reviews, read_decisions
from retail_profit_stack.store import Store
from retail_profit_stack.transform.pipeline import load_sources, run_pipeline
from retail_profit_stack.transform.specs import ordered_specs

PORT = 8765
VERSION = 6  # raise this whenever the page needs something new from this program
WORKSPACE = HERE / "workspace"
# For testing: "--port 8766 --workspace some/folder" runs a second copy that shares nothing.
if "--port" in sys.argv:
    PORT = int(sys.argv[sys.argv.index("--port") + 1])
if "--workspace" in sys.argv:
    WORKSPACE = Path(sys.argv[sys.argv.index("--workspace") + 1]).resolve()
WAREHOUSE = WORKSPACE / "warehouse"
PLACES = Places(
    landing=LANDING_DIR,
    loaded=WORKSPACE / "loaded",
    state_file=WORKSPACE / "loader_state.sqlite",
    mappings_file=WORKSPACE / "approved_mappings.json",
)
LATE_PLACES = replace(PLACES, landing=LATE_DIR)  # the same records, fed from the late folder
DECISIONS = WORKSPACE / "review_decisions.json"  # what you decided at the review desk
LATE = "late/"  # a late file's name on the page starts with this, so two files can share a name
STEP_PAUSE = 0.7  # seconds between pipeline steps on the page, so a person can follow them


class LiveRun:
    """Everything the page needs to know about the run in progress."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.status = "idle"  # idle, loading, waiting, running, done, error
        self.workflow = None
        self.desk_done = threading.Event()
        self.last_run = None  # the PipelineRun of the latest pipeline run

    def emit(self, stage: str, kind: str, data: dict | None = None) -> None:
        """Add one event. The page asks for the events it has not seen yet."""
        with self.lock:
            event = {
                "seq": len(self.events),
                "stage": stage,
                "kind": kind,
                "data": clean(data or {}),
            }
            self.events.append(event)


LIVE = LiveRun()


def clean(value):
    """Make a value safe to send as JSON: no NaN, and dates and paths as text."""
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(item) for item in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):  # a numpy number
        return clean(value.item())
    return str(value)


# ---- What the page can ask for ----------------------------------------------


def list_files() -> list[dict]:
    """Every file that can arrive, on time or late, and whether it is already loaded.

    A late file's id starts with "late/". One late file is a correction: it has the same name
    as a file that arrived on time. A file counts as loaded when the load record holds its
    name with this exact content.
    """
    seen = {entry["file_name"]: entry for entry in ledger.files_seen(PLACES.state_file)}
    files = []
    for folder, prefix in ((LANDING_DIR, ""), (LATE_DIR, LATE)):
        for file in sorted(folder.glob("*.csv")):
            with file.open(encoding="utf-8") as handle:
                rows = sum(1 for _ in handle) - 1
            entry = seen.get(file.name, {})
            same_content = entry.get("fingerprint") == fingerprint(file)
            files.append({
                "id": prefix + file.name,
                "name": file.name,
                "feed": feed_of(file.name),
                "rows": rows,
                "columns": read_header(file),
                "late": prefix == LATE,
                "correction": prefix == LATE and (LANDING_DIR / file.name).exists(),
                "outcome": entry.get("outcome", "") if same_content else "",
            })  # fmt: skip
    return files


def start_over() -> None:
    """Forget everything this page has loaded and calculated."""
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    LIVE.events.clear()
    LIVE.status = "idle"
    LIVE.workflow = None
    LIVE.last_run = None


NO_KEY = (
    "This needs an OpenRouter key. Copy .env.example to .env, add your key, and restart "
    "this program. Everything else on the page works without one."
)


def has_key() -> bool:
    """Whether an OpenRouter key is set. Without one the page still works, with AI switched off."""
    load_dotenv(ENV_FILE)
    return bool(os.getenv("OPENROUTER_API_KEY"))


def make_live_model(use_ai: bool):
    """The model that suggests mappings, or None when AI is switched off or there is no key."""
    if not use_ai or not has_key():
        return None
    from retail_profit_stack.agent import make_model

    return make_model(timeout=30)


# ---- One run: load the chosen files, wait at the desk, then run the pipeline --


def run_everything(files: list[str], at_once: int, use_ai: bool) -> None:
    """The whole flow for one press of the Run button. Runs on its own thread."""
    try:
        LIVE.status = "loading"
        LIVE.desk_done.clear()
        model = make_live_model(use_ai)
        workflow = build_file_workflow(PLACES, model)
        LIVE.workflow = workflow
        LIVE.emit("load", "start", {"files": files, "at_once": at_once, "use_ai": use_ai})

        on_time = [name for name in files if not name.startswith(LATE)]
        late = [name.removeprefix(LATE) for name in files if name.startswith(LATE)]
        started = time.time()

        # 1. The dispatcher hands each file to its own worker. Each result is reported as it lands.
        def load(names: list[str], the_workflow, prefix: str) -> None:
            def work_file(file_name: str):
                result = run_file(the_workflow, file_name)
                LIVE.emit("load", "file", {**result, "id": prefix + file_name})
                return {"results": [result]}

            build_dispatcher(work_file).invoke(
                {"files": names, "results": []}, {"max_concurrency": at_once}
            )

        load(on_time, workflow, "")

        # 2. Files with a renamed column wait at the desk for a person.
        questions = waiting_files(workflow, PLACES)
        if questions:
            LIVE.status = "waiting"
            LIVE.emit("load", "done", {"counts": ledger.outcome_counts(PLACES.state_file)})
            for question in questions:
                file_name = question["file_name"]
                question["file_rows"] = sample_rows(PLACES.landing / file_name, 3)
                question["earlier_rows"] = earlier_rows(PLACES, feed_of(file_name), 3)
                LIVE.emit("desk", "question", question)
            LIVE.desk_done.wait()
            LIVE.status = "loading"

        # 3. Late files load last, as they would in life. A correction replaces the earlier file.
        load(late, build_file_workflow(LATE_PLACES, model), LATE)
        LIVE.emit("load", "done", {
            "seconds": round(time.time() - started, 1),
            "counts": ledger.outcome_counts(PLACES.state_file),
            "replaced": ledger.files_replaced(PLACES.state_file),
        })  # fmt: skip

        run_the_pipeline(len(files))
    except Exception as error:  # noqa: BLE001 - the page must be told, whatever went wrong
        LIVE.status = "error"
        LIVE.emit("error", "error", {"message": f"{type(error).__name__}: {error}"})


def run_the_pipeline(files_chosen: int) -> None:
    """Run the production pipeline once, then play its steps back to the page.

    The pipeline itself takes a fraction of a second. The pauses are only so a person can
    follow. Every number sent comes from the run.
    """
    LIVE.status = "running"
    note = f"Live pipeline: {files_chosen} files chosen"
    # incremental: recalculate only the months that changed files touch. The first run is full.
    run = run_pipeline(
        "sql", source_dir=PLACES.loaded, warehouse_dir=WAREHOUSE, note=note,
        incremental=True, decisions_file=DECISIONS,
    )  # fmt: skip
    LIVE.last_run = run
    record = run.record

    def step(stage: str, data: dict) -> None:
        LIVE.emit(stage, "start")
        time.sleep(STEP_PAUSE)
        LIVE.emit(stage, "result", data)

    step("records", {"inputs": record["inputs"], "ledger": ledger.files_seen(PLACES.state_file)})

    findings = run.findings.to_dict(orient="records")
    step("checks", {"outcomes": run.check_outcomes, "findings": findings})

    kept = {
        name: record["inputs"][name]["rows"] - run.quarantined_counts.get(name, 0)
        for name in record["inputs"]
    }
    step("quarantine", {"set_aside": run.quarantined_counts, "kept": kept})

    # The review desk: records waiting for a decision, and the ones already decided.
    records = run.finding_records.to_dict(orient="records")
    people = read_decisions(DECISIONS)
    decided = [
        {"record_key": row["record_key"], "decision": row["decision"], "detail": row["detail"],
         "person": people[row["record_key"]]["person"]}
        for row in records if row["decision"]
    ]  # fmt: skip
    step("review", {"open": open_reviews(run.findings, run.finding_records), "decided": decided})

    transformations = [
        {"name": spec.name, "inputs": list(spec.inputs), "rows": run.row_counts[spec.name],
         "rule": spec.rule}
        for spec in ordered_specs()
    ]  # fmt: skip
    step("calculate", {"transformations": transformations, "profit": profit_rows(run)})

    step("lineage", {
        "graph": lineage_graph(run),
        "rows": len(run.lineage),
        "records": int(run.lineage[["source_table", "row_number"]].drop_duplicates().shape[0]),
        "adds_up": record["lineage_adds_up"],
    })  # fmt: skip

    history = read_history(WAREHOUSE)
    comparison = None
    if len(history) >= 2:
        full = compare_runs(history[-2]["run_id"], history[-1]["run_id"], WAREHOUSE)
        moved = [row for row in full["figures_changed"] if row["metric"] == "contribution_profit"]
        comparison = {**full, "figures_changed": moved, "all_changes": len(full["figures_changed"])}
    step("record", {"record": record, "history": run_history(), "comparison": comparison})

    LIVE.status = "done"
    LIVE.emit("done", "done", {"run_id": run.run_id})


TERMS = ["gross_sales", "discounts", "refunds", "net_sales", "product_cost", "gross_profit",
         "fulfillment_cost", "shipping_cost", "payment_fees", "return_cost", "contribution_profit"]  # fmt: skip


def profit_rows(run) -> list[dict]:
    """The profit table with product names and every term, newest month and highest profit first."""
    profit = run.tables["monthly_product_profit"].to_pandas()
    products = load_sources(PLACES.loaded)["products"].to_pandas()
    table = profit.merge(products, on="product_id", how="left")
    table = table.sort_values(["month", "contribution_profit"], ascending=[False, False])
    columns = ["month", "product_id", "product_name", "category", "units_sold", *TERMS]
    return table[columns].to_dict(orient="records")


def files_behind(lineage, month: str, product_id: str) -> list[dict]:
    """Which landing files the records behind one figure came from, and how many from each.

    A table is its loaded pieces put end to end in file-name order. So a record's row number
    says which piece, and therefore which file, it arrived in.
    """
    rows = lineage[(lineage["month"] == month) & (lineage["product_id"] == product_id)]
    records = rows[["source_table", "row_number"]].drop_duplicates()
    behind = []
    for feed in sorted(set(records["source_table"])):
        numbers = sorted(int(n) for n in records[records["source_table"] == feed]["row_number"])
        first_row = 1
        for piece in sorted((PLACES.loaded / feed).glob("*.parquet")):
            size = pq.read_metadata(piece).num_rows
            count = sum(first_row <= number < first_row + size for number in numbers)
            if count:
                behind.append({"feed": feed, "file": piece.stem + ".csv", "records": count})
            first_row += size
    return behind


def lineage_graph(run) -> dict:
    """The table-level lineage: which files built each source table, and which table feeds which.

    files: for each feed, the loaded files (one per date partition) with their row counts.
    tables: every table with its row count. edges: input table -> output table.
    """
    files = {}
    for feed in run.record["inputs"]:
        pieces = sorted((PLACES.loaded / feed).glob("*.parquet"))
        files[feed] = [
            {"file": piece.stem + ".csv", "rows": pq.read_metadata(piece).num_rows}
            for piece in pieces
        ]
    tables = {name: item["rows"] for name, item in run.record["inputs"].items()}
    tables.update(run.row_counts)
    steps = run.lineage_steps.to_dict(orient="records")
    edges = [{"from": step["input_table"], "to": step["output_table"]} for step in steps]
    return {"files": files, "tables": tables, "edges": edges}


def run_history() -> list[dict]:
    """One line per run kept in the history: its files, findings, and total contribution profit."""
    history = []
    for record in read_history(WAREHOUSE):
        folder = WAREHOUSE / "runs" / record["run_id"]
        profit = pq.read_table(folder / "monthly_product_profit.parquet").to_pandas()
        history.append({
            "run_id": record["run_id"],
            "started_at": record["started_at"],
            "files": sum(item.get("files", 0) for item in record["inputs"].values()),
            "findings": record["findings"],
            "mode": record.get("mode", "full"),
            "total_profit": round(float(profit["contribution_profit"].sum()), 2),
            "unavailable": int(profit["contribution_profit"].isna().sum()),
        })  # fmt: skip
    return history


def answer_question(file_name: str, approved: bool, person: str, mapping: dict | None) -> dict:
    """A person's answer to one waiting file. When none is left waiting, the pipeline starts."""
    result = answer(LIVE.workflow, file_name, approved, person or "you", mapping)
    LIVE.emit("desk", "answered", result)
    if not waiting_files(LIVE.workflow, PLACES):
        LIVE.desk_done.set()
    return result


def decide_record(record_key: str, decision: str, note: str) -> dict:
    """Your decision on one record at the review desk. The next run obeys it."""
    return decide(DECISIONS, record_key, decision, "you", note)


def trace_figure(month: str, product_id: str) -> dict:
    """The records behind one product's figures in one month, from the latest run's lineage."""
    run = LIVE.last_run
    store = Store(source_dir=PLACES.loaded, warehouse_dir=WAREHOUSE, state_file=PLACES.state_file)
    evidence = tools.get_evidence(month, product_id, store=store)
    return {
        "month": month, "product_id": product_id, "run_id": run.run_id,
        "record_counts": record_counts(run.lineage, month, product_id),
        "files": files_behind(run.lineage, month, product_id),
        "set_aside": evidence.set_aside_count,
        "steps": evidence.steps,
        "records": [record.model_dump() for record in evidence.records],
    }  # fmt: skip


def ask_analyst(question: str) -> dict:
    """Ask the production analyst a question about the latest run. Calls the model."""
    from retail_profit_stack.agent import run_analyst

    if not has_key():
        return {"answer": None, "error": NO_KEY}
    if LIVE.last_run is None:
        return {"answer": None, "error": "Run the pipeline first, then ask."}
    store = Store(source_dir=PLACES.loaded, warehouse_dir=WAREHOUSE, state_file=PLACES.state_file)
    run = run_analyst(question, store=store)
    return {
        "answer": run.answer.model_dump() if run.answer else None,
        "error": run.error,
        "steps": run.steps,
        "checks": [check.model_dump() for check in run.verification.checks] if run.verification else [],
        "verified": bool(run.verification and run.verification.passed),
        "cost": run.cost, "seconds": run.seconds, "run_id": run.run_id,
    }  # fmt: skip


# ---- The web server ----------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the terminal quiet
        pass

    def send_json(self, data, status: int = 200) -> None:
        body = json.dumps(clean(data)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/files":
            self.send_json(
                {
                    "files": list_files(),
                    "milestone": MILESTONE.name,
                    "status": LIVE.status,
                    "version": VERSION,
                    "has_key": has_key(),
                }
            )
        elif self.path.startswith("/api/events"):
            since = int(self.path.partition("since=")[2] or 0)
            with LIVE.lock:
                events = LIVE.events[since:]
            self.send_json({"events": events, "status": LIVE.status})
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self.read_json()
            if self.path == "/api/run":
                if LIVE.status in ("loading", "waiting", "running"):
                    return self.send_json({"error": "A run is already in progress."}, 409)
                files = sorted(body.get("files", []))
                # "again" runs the pipeline on the records already loaded, with your decisions.
                if not files and not body.get("again"):
                    return self.send_json({"error": "Choose at least one file."}, 400)
                LIVE.events.clear()
                arguments = (files, int(body.get("at_once", 5)), bool(body.get("use_ai", True)))
                threading.Thread(target=run_everything, args=arguments, daemon=True).start()
                return self.send_json({"started": True})
            if self.path == "/api/answer":
                return self.send_json(answer_question(
                    body["file_name"], bool(body["approved"]), body.get("person", ""),
                    body.get("mapping"),
                ))  # fmt: skip
            if self.path == "/api/decide":
                return self.send_json(
                    decide_record(body["record_key"], body["decision"], body.get("note", ""))
                )
            if self.path == "/api/trace":
                return self.send_json(trace_figure(body["month"], body["product_id"]))
            if self.path == "/api/ask":
                return self.send_json(ask_analyst(body["question"]))
            if self.path == "/api/reset":
                if LIVE.status in ("loading", "running"):
                    return self.send_json({"error": "Wait for the run to finish first."}, 409)
                LIVE.desk_done.set()
                start_over()
                return self.send_json({"reset": True})
            return self.send_json({"error": "not found"}, 404)
        except Exception as error:  # noqa: BLE001 - report the problem to the page
            return self.send_json({"error": f"{type(error).__name__}: {error}"}, 500)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    address = f"http://localhost:{PORT}"
    print(f"The live pipeline is running the production code of {MILESTONE.name}.")
    print(f"Open {address} in your browser. Press Ctrl+C here to stop.")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
