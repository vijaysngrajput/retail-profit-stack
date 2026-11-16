# Milestone 3: Quality and trust layer

**Status:** Done. Design documents, lab notebooks, production code, and tests are complete.

**What it adds:** quality checks that run on the business's records and decide what happens to them, replacing the hand-written list of data problems. Records that are certainly wrong are set aside and left out of the figures. An AI agent then investigates each problem the checks found and writes a report for a person.

This folder is self-contained. It started as a copy of milestone 2 and imports nothing from another milestone.

| Folder | Holds |
|---|---|
| [docs/](docs/) | [BRD](docs/BRD.md), [HLD](docs/HLD.md), and [LLD](docs/LLD.md), each with a data flow diagram |
| `notebooks/` | The lab: six short notebooks, run in order, plus `lab_helpers.py` |
| `retail_profit_stack/` | Production code. The new part is `quality/`: checks, quarantine, the investigation desk, and the investigator agent |
| `tests/` | Tests for the production code |
| `data/source/` | The business's records, generated, with seven problems planted in them |
| `data/warehouse/` | The calculated tables and the quality findings, written by the pipeline (not committed) |
| `data/quality_rulebook.md` | What each check means, and the usual causes of each problem |
| `evals/` | The evaluation questions, the check cases, and the planted cause of each finding |
| [milestone_3_recap.html](milestone_3_recap.html) | A closing page to open when you finish the milestone |

## Read it in this order

1. [docs/BRD.md](docs/BRD.md): why this milestone exists and what the business needs.
2. [docs/HLD.md](docs/HLD.md): the checks, the quarantine, and the investigator agent.
3. [docs/LLD.md](docs/LLD.md): the exact detail of each part. Keep it open for the next two steps.
4. The lab notebooks in `notebooks/`, in order from `01` to `06`.
5. The code in `retail_profit_stack/quality/` and `tests/`.
6. [milestone_3_recap.html](milestone_3_recap.html): when you have finished, open this page in a browser.

Section 12 of the LLD maps each notebook to the design sections and code files behind it.

## Run it

From this folder, run the pipeline, then the tests:

```
uv run python -m retail_profit_stack.transform.pipeline
uv run pytest
```

The pipeline checks the records, sets the wrong ones aside, calculates the figures, and writes the findings. The tests need no key and no network, and they run the pipeline themselves.

To run the lab, open the notebooks in VS Code, choose the project's `.venv` as the kernel, and run them in order:

| Notebook | What you do | Model requests |
|---|---|---|
| `01_the_problems_by_hand` | Recall the question, find the data problems yourself, and correct the answer key | 0 |
| `02_checks_in_code` | Write two quality checks as queries, and prove each one works | 0 |
| `03_quarantine_and_the_figures` | Set the wrong records aside, recalculate, and confirm the totals add up | 0 |
| `04_a_todo_list_and_a_helper_by_hand` | Ask a model to explain the problems, then build an agent that organises its own work | about 20 |
| `05_a_harness_works_the_queue` | Give every problem to a ready-made agent harness, and score its reports | about 40 |
| `06_the_same_question_with_real_warnings` | Ask the analyst the leader's question, now that the warnings come from real checks | about 8 |

Notebooks 4 to 6 need `OPENROUTER_API_KEY` in the `.env` file at the project root. When the lab was built, a full run cost about 10 US cents. All models are reached through OpenRouter; nothing is installed locally.

In notebooks 4 and 5 an AI agent reads and writes files. It works in a `desk` folder inside `notebooks/` that holds copies, and its file tools cannot reach anything outside that folder. It cannot run commands. Nothing it writes is read by the pipeline or the analyst.

To regenerate the business's records:

```
uv run python -m retail_profit_stack.source_data
```

The standard every milestone follows is described in the project [README](../../README.md#how-every-milestone-is-built).
