# Milestone 2: Metric and calculation layer

**Status:** Done. Design documents approved; lab notebooks run live; production code and tests passing; signed off by the learner.

**What it adds:** profit is calculated from orders, refunds, and costs by explicit, repeatable transformations, replacing milestone 1's prepared profit table. The same rule can run on pandas or SQL today, and on PySpark later. AI drafts the transformations, tests judge its work, and several models are compared on accuracy, cost, and speed.

This folder is self-contained. It started as a copy of milestone 1 and imports nothing from another milestone.

| Folder | Holds |
|---|---|
| [docs/](docs/) | [BRD](docs/BRD.md), [HLD](docs/HLD.md), and [LLD](docs/LLD.md), each with a data flow diagram |
| `notebooks/` | The lab: six short notebooks, run in order, plus `lab_helpers.py` |
| `retail_profit_stack/` | Production code. The new part is `transform/`: contracts, engines, implementations, pipeline, and AI drafting |
| `tests/` | Tests for the production code |
| `data/source/` | The business's records, generated |
| `data/warehouse/` | The calculated tables, written by the pipeline (not committed) |
| `data/mock/` | What is still mocked: the quality flags and the reporting period |
| `evals/` | Milestone 1's evaluation questions, and the hand-worked cases for the transformations |
| [milestone_2_recap.html](milestone_2_recap.html) | A closing page to open when you finish the milestone |

## Read it in this order

1. [docs/BRD.md](docs/BRD.md): why this milestone exists and what the business needs.
2. [docs/HLD.md](docs/HLD.md): the transformation layer and how it sits under the analyst.
3. [docs/LLD.md](docs/LLD.md): the exact detail of each part. Keep it open for the next two steps.
4. The lab notebooks in `notebooks/`, in order from `01` to `06`.
5. The code in `retail_profit_stack/transform/` and `tests/`.
6. [milestone_2_recap.html](milestone_2_recap.html): when you have finished, open this page in a browser.

Section 13 of the LLD maps each notebook to the design sections and code files behind it.

## Run it

From this folder, calculate the tables, then run the tests:

```
uv run python -m retail_profit_stack.transform.pipeline
uv run pytest
```

The pipeline takes the engine as an optional word: `sql` (the default) or `pandas`. The tests need no key and no network, and they run the pipeline themselves.

To run the lab, open the notebooks in VS Code, choose the project's `.venv` as the kernel, and run them in order:

| Notebook | What you do | Model requests |
|---|---|---|
| `01_the_business_records` | Recall the question and the answer key, and explore the records | 0 |
| `02_one_calculation_two_engines` | Write a calculation by hand in pandas and in SQL, with test cases | 0 |
| `03_a_model_drafts_a_transformation` | Ask a model to write the calculation, and let the tests judge it | 3 |
| `04_which_model` | Give the same tasks to six models and compare them | about 85 (about 25 with `TINY` on) |
| `05_an_agent_that_fixes_its_own_code` | Give a model the tests as a tool | about 20 |
| `06_the_pipeline_and_the_same_question` | Run the pipeline on each engine and ask the analyst again | about 8 |

Notebooks 3 to 6 need `OPENROUTER_API_KEY` in the `.env` file at the project root. When the lab was built, a full run cost about 15 US cents, most of it the stronger model in notebook 5. All models are reached through OpenRouter; nothing is installed locally.

Notebooks 3 to 5 run code that a model wrote. It runs under limits (no file or network access for SQL; a checked, separate process for pandas; a time limit for both), which reduce the risk but are not a perfect sandbox. The notebooks show the code before running it.

To regenerate the business's records from their inputs:

```
uv run python -m retail_profit_stack.source_data
```

The standard every milestone follows is described in the project [README](../../README.md#how-every-milestone-is-built).
