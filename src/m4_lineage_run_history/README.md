# Milestone 4: Lineage and run history

**Status:** Done. Design documents approved; lab notebooks run live; production code and tests passing; signed off by the learner.

**What it adds:** the system now remembers how each result was made.

- **For a figure:** every pipeline run gets an id and a record, and keeps its own tables. **Lineage** links every figure to every record behind it. Two runs can be compared, so "why did this number change?" is looked up, not guessed.
- **For an answer:** every step the AI analyst takes is recorded as a **trace**, kept in Langfuse. The analyst is measured with **experiments**: a fixed list of questions, scored with a confusion matrix, kappa, and the cost of mistakes.

This folder is self-contained. It started as a copy of milestone 3 and imports nothing from another milestone.

| Folder | Holds |
|---|---|
| [docs/](docs/) | [BRD](docs/BRD.md), [HLD](docs/HLD.md), and [LLD](docs/LLD.md), each with a data flow diagram |
| `notebooks/` | The lab: seven short notebooks, run in order, plus `lab_helpers.py` |
| `retail_profit_stack/` | Production code. The new parts are `lineage/` (run records, lineage, run comparison), `tracing.py`, `scoring.py`, and `experiments.py` |
| `tests/` | Tests for the production code |
| `data/source/` | The business's records, generated, as in milestone 3 |
| `data/warehouse/` | The run history: one folder of tables per pipeline run (not committed) |
| `evals/` | The fourteen evaluation questions, and milestone 3's check cases |
| [milestone_4_recap.html](milestone_4_recap.html) | A closing page to open when you finish the milestone |

## Read it in this order

1. [docs/BRD.md](docs/BRD.md): why this milestone exists and what the business needs.
2. [docs/HLD.md](docs/HLD.md): the parts. Section 8 explains Langfuse in plain words.
3. [docs/LLD.md](docs/LLD.md): the exact detail of each part. Keep it open for the next two steps.
4. The lab notebooks in `notebooks/`, in order from `01` to `07`.
5. The code in `retail_profit_stack/lineage/` and `tests/`.
6. [milestone_4_recap.html](milestone_4_recap.html): when you have finished, open this page in a browser.

Section 13 of the LLD maps each notebook to the design sections and code files behind it.

## Set up Langfuse (once)

Langfuse is a website that keeps a record of every step an AI agent takes. Notebooks 5 and 7 use it. It has a free plan, which is enough for this lab.

1. Sign up at [cloud.langfuse.com](https://cloud.langfuse.com) and create a project. Use a project made only for this lab.
2. In the project's settings, open **API Keys** and create a key.
3. Add the three values it shows to the `.env` file at the project root:

```
LANGFUSE_SECRET_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_BASE_URL=...
```

What is sent to Langfuse: the questions, the analyst's prompts and replies, and the tool results. All of it is fictional data. Your OpenRouter key is never sent.

The production code works without Langfuse. Tracing is off unless you ask for it, and the tests never use it.

## Run it

From this folder, make the two pipeline runs the milestone starts with, then run the tests:

```
uv run python -m retail_profit_stack.make_history
uv run pytest
```

`make_history` clears `data/warehouse/` and makes `RUN-0001` (duplicated records counted, as before milestone 3) and `RUN-0002` (duplicated records set aside). The tests need no key, no network, and no Langfuse, and they rebuild those two runs themselves.

To add one more run to the history:

```
uv run python -m retail_profit_stack.transform.pipeline
```

The analyst compares the latest two runs. After adding runs of your own, run `make_history` again to go back to the starting two.

To run the lab, open the notebooks in VS Code, choose the project's `.venv` as the kernel, and run them in order:

| Notebook | What you do | Model requests |
|---|---|---|
| `01_a_figure_traced_by_hand` | Find every record behind one figure yourself, and add them up | 0 |
| `02_run_records` | Work out a fingerprint by hand, then give every pipeline run an id and a record | 0 |
| `03_lineage` | Save which records made each figure, prove it adds up, and break it on purpose | 0 |
| `04_two_runs_compared` | Find what changed between two runs: settings, inputs, figures, records | 0 |
| `05_a_trace_of_the_analyst` | Give the analyst the new tools, record its steps by hand, then open the trace in Langfuse | about 15 |
| `06_scoring_an_agent` | Work out a confusion matrix, kappa, and the cost of mistakes on three made-up analysts | 0 |
| `07_two_experiments` | Run the analyst without and with the run tool on the same questions, and compare the scores | about 40 |

Notebooks 5 and 7 need `OPENROUTER_API_KEY` and the three Langfuse settings. When the lab was built, a full run cost about 5 US cents. All models are reached through OpenRouter; nothing is installed locally.

Notebooks 2 to 4 keep their own pipeline runs in `notebooks/lab_warehouse/`, so your experiments there never change the real run history. Notebooks 5 and 7 call `make_history` at the top, which resets the real one to its two starting runs.

The standard every milestone follows is described in the project [README](../../README.md#how-every-milestone-is-built).
