# Milestone 6: Realistic operations

**Status:** Built. Design documents written and the build completed without a pause, as the learner asked; lab notebooks run live; production code and tests passing. Waiting for the learner to run the lab and sign off.

**What it adds:** the system stops assuming that data arrives once, complete, and on time, and it starts measuring and improving its own AI analyst.

**Operations, all in code:**

- **Late and corrected files.** A late file loads like any other. A file sent again with different content replaces the earlier version.
- **Incremental runs.** The pipeline recalculates only the months that changed files touch, and the result equals a full rebuild.
- **Restatements.** When a reported figure changes, the run history shows it and names the files that caused it. The analyst explains it.
- **A review desk.** A person decides each "needs review" finding, and the next run obeys.
- **Run health.** Every run records its steps, how long each took, and any warning.

**Measure and improve:**

- **An end-to-end evaluation.** From generated files to scored answers, on an evaluation set and a held-out set.
- **A judge.** A second AI model grades the analyst's explanations against a reference written by code.
- **An improver.** An AI agent proposes changes to the analyst. A person approves each one. Code keeps it or rolls it back.

This folder is self-contained. It started as a copy of milestone 5 and imports nothing from another milestone.

| Folder | Holds |
|---|---|
| [docs/](docs/) | [BRD](docs/BRD.md), [HLD](docs/HLD.md), and [LLD](docs/LLD.md), each with a data flow diagram |
| `notebooks/` | The lab: eight short notebooks, run in order, plus `lab_helpers.py` |
| `retail_profit_stack/` | Production code. New: `quality/review.py`, `e2e.py`, `judge.py`, `analyst_versions.py`, `improver.py` |
| `tests/` | Tests for the production code |
| `data/landing/` | The fifty files that arrive on time |
| `data/landing_late/` | Three files that arrive after month-end close |
| `evals/` | The evaluation set (18 questions) and the held-out set (10) |
| [milestone_6_recap.html](milestone_6_recap.html) | The closing page of the project |

## See it working

The [live pipeline](../../pipeline_live/) runs this milestone's production code on files you choose, including the late ones, and has the review desk on the page. From the project root:

```
uv run python pipeline_live/server.py
```

## Read it in this order

1. [docs/BRD.md](docs/BRD.md): why this milestone exists. Section 5 explains the new words.
2. [docs/HLD.md](docs/HLD.md): the parts. Sections 8 to 10 explain the evaluation, the judge, and the improver in plain words.
3. [docs/LLD.md](docs/LLD.md): the exact detail of each part. Keep it open for the next two steps.
4. The lab notebooks in `notebooks/`, in order from `01` to `08`.
5. The code in `retail_profit_stack/` and `tests/`.
6. [milestone_6_recap.html](milestone_6_recap.html): when you have finished, open this page in a browser.

Section 12 of the LLD maps each notebook to the design sections and code files behind it.

## Run it

From this folder, build to month-end close and then apply the late files, then run the tests:

```
uv run python -m retail_profit_stack.make_history --late
uv run pytest
```

Without `--late` the command stops at month-end close: `RUN-0001` and `RUN-0002`, as in milestone 5. With it, the three late files are loaded and `RUN-0003` is made with an incremental run. The tests need no key and no network.

To run the lab, open the notebooks in VS Code, choose the project's `.venv` as the kernel, and run them in order:

| Notebook | What you do | Model requests |
|---|---|---|
| `01_late_and_corrected_files_by_hand` | Work out by hand what three late files should do to the figures | 0 |
| `02_corrections_and_incremental_runs` | Load the late files, recalculate only what they touch, and prove it equals a full rebuild | 0 |
| `03_the_review_desk` | Decide the findings that need review, and watch the next run obey | 0 |
| `04_run_health_and_restatements` | Read a run's health, and ask the analyst why a reported figure changed | about 6 |
| `05_a_judge_with_a_reference_answer` | Test a judge on explanations whose grade you know, then use it | about 12 |
| `06_the_end_to_end_evaluation` | Score the whole system from files to answers, on two question sets | about 30 |
| `07_the_improver` | Approve a change the improver proposes, and see code keep it or roll it back | about 60 |
| `08_the_whole_system` | Run everything from files to answer, and look back over six milestones | about 10 |

Notebooks 4 to 8 need `OPENROUTER_API_KEY` in the `.env` file at the project root. When the lab was built, a full run with the default small question sets cost about 10 US cents. Notebooks 6 and 7 have a `TINY` switch: with the full sets they cost about 6 and 15 US cents.

The improver spends within a budget set in code. As a second guard, you can put a credit limit on your key at [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys).

The lab builds the system in a folder of its own, `notebooks/lab_e2e/`, and keeps its decisions and analyst versions in `notebooks/`. It never changes this milestone's real data.

The standard every milestone follows is described in the project [README](../../README.md#how-every-milestone-is-built).
