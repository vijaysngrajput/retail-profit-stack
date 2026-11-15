# Milestone 5: Raw data and ingestion

**Status:** Done. Design documents approved; lab notebooks run live; production code and tests passing; signed off by the learner.

**What it adds:** the business's records now arrive as files and are loaded by a repeatable process.

- **Safe to repeat.** A file is known by the fingerprint of its content. Loading it twice, or loading a resent copy, changes nothing.
- **A rule for every file.** Code compares each file's columns with the contract and applies one of seven rules: load, skip, reject, or wait.
- **AI suggests, a person approves.** When a column has been renamed, a model suggests what it means. The workflow pauses until a person approves, and the approved mapping is saved and reused.
- **It can wait, and survive a crash.** The loader is a graph whose state is saved after every step, in a file on your computer.
- **Many at once.** A dispatcher loads the files side by side, with a cap and a retry.

Everything above the loader is unchanged, and every figure equals milestone 4's.

This folder is self-contained. It started as a copy of milestone 4 and imports nothing from another milestone.

| Folder | Holds |
|---|---|
| [docs/](docs/) | [BRD](docs/BRD.md), [HLD](docs/HLD.md), and [LLD](docs/LLD.md), each with a data flow diagram |
| `notebooks/` | The lab: seven short notebooks, run in order, plus `lab_helpers.py` |
| `retail_profit_stack/` | Production code. The new part is `ingest/`: the rules, the load record, mappings, the file workflow, and the dispatcher |
| `tests/` | Tests for the production code |
| `data/landing/` | The fifty files as they arrive, generated, with seven file problems planted |
| `data/approved_mappings.json` | The mappings a person has approved |
| `data/loaded/`, `data/loader_state.sqlite` | What the loader writes: one piece per file, the load record, and the saved workflows (not committed) |
| `data/warehouse/` | The run history, as milestone 4 (not committed) |
| `evals/` | The fourteen evaluation questions, and the true meaning of each renamed column |
| [milestone_5_recap.html](milestone_5_recap.html) | A closing page to open when you finish the milestone |

## See it working

The [live pipeline](../../pipeline_live/) runs this milestone's production code on files you choose, and shows every step on one page: loading, your approval desk, the checks, the calculations, lineage back to the files and their dates, and the run history. From the project root:

```
uv run python pipeline_live/server.py
```

## Read it in this order

1. [docs/BRD.md](docs/BRD.md): why this milestone exists and what the business needs.
2. [docs/HLD.md](docs/HLD.md): the parts. Section 7 explains graphs, saved state, and the pause in plain words. Section 8 explains loading many files at once.
3. [docs/LLD.md](docs/LLD.md): the exact detail of each part. Keep it open for the next two steps.
4. The lab notebooks in `notebooks/`, in order from `01` to `07`.
5. The code in `retail_profit_stack/ingest/` and `tests/`.
6. [milestone_5_recap.html](milestone_5_recap.html): when you have finished, open this page in a browser.

Section 12 of the LLD maps each notebook to the design sections and code files behind it.

## Run it

From this folder, load the files and make the two pipeline runs, then run the tests:

```
uv run python -m retail_profit_stack.make_history
uv run pytest
```

`make_history` loads the landing files (the three mappings are already approved, so nothing waits), then makes `RUN-0001` and `RUN-0002` as in milestone 4. Loading is safe to repeat. The tests need no key, no network, and no Langfuse.

Other commands:

| Command | What it does |
|---|---|
| `uv run python -m retail_profit_stack.source_data` | Write the fifty landing files again. The same seed gives the same files |
| `uv run python -m retail_profit_stack.ingest.dispatch` | Load every landing file, and print each file's outcome |
| `uv run python -m retail_profit_stack.ingest.workflow` | List the files waiting for approval, and answer each one in the terminal |

To run the lab, open the notebooks in VS Code, choose the project's `.venv` as the kernel, and run them in order:

| Notebook | What you do | Model requests |
|---|---|---|
| `01_files_arrive_by_hand` | Load the files the naive way, and watch three things go wrong without an error | 0 |
| `02_a_loader_safe_to_repeat` | Fingerprint each file, compare its columns with the contract, and choose a rule for every file | 0 |
| `03_ai_reads_a_changed_file` | Ask a model what a renamed column means, score its suggestions, and see why a person must approve | about 9 |
| `04_a_workflow_that_can_wait` | Build the loader as a graph by hand. A renamed file pauses, and you approve it | about 2 |
| `05_crash_and_carry_on` | Pause a file, restart the kernel on purpose, and find it still waiting | about 1 |
| `06_a_swarm_of_file_workers` | Load fifty files side by side, with a stand-in first, and score each run | about 18 |
| `07_the_same_question_from_loaded_files` | Approve the waiting files, run the pipeline, and ask the leader's question | about 6 |

Notebooks 3 to 7 need `OPENROUTER_API_KEY` in the `.env` file at the project root. Notebook 6 also uses the Langfuse settings from milestone 4. When the lab was built, a full run cost about 3 US cents.

The lab loads into folders of its own inside `notebooks/` (`lab_loaded/`, `lab_state.sqlite`, `lab_mappings.json`). It never changes the landing files or the real load record. In notebook 5 you restart the kernel partway through, on purpose.

The standard every milestone follows is described in the project [README](../../README.md#how-every-milestone-is-built).
