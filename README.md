# Retail Profit Stack

An AI data engineering learning project about tracing retail profitability from business events to trustworthy metrics and answers. All data is fictional.

Read [Retail_Profit_Stack.md](Retail_Profit_Stack.md) for the project overview.

## Start here

1. **Understand the business.** Open [understand_business/business_workflow.html](understand_business/business_workflow.html) in a browser. It shows how a product reaches a customer, from several points of view.
2. **Set up** your environment (see below).
3. **Work through the milestones in order**, starting with [milestone 1](src/m1_mocked_business_answer/).

## Milestones

The project starts at the business answer and works backward, replacing one mocked part with a real one in each milestone.

| Milestone | What it adds | Status |
|---|---|---|
| [1. Mocked business answer](src/m1_mocked_business_answer/) | An AI analyst answers a profit question from prepared figures and shows its evidence | Done |
| [2. Metric and calculation layer](src/m2_metric_calculation_layer/) | Profit is calculated from orders, refunds, and costs | Not started |
| [3. Quality and trust layer](src/m3_quality_trust_layer/) | Real data quality checks replace the planted problems | Not started |
| [4. Lineage and run history](src/m4_lineage_run_history/) | Every figure can be traced to its inputs and compared between runs | Not started |
| [5. Raw data and ingestion](src/m5_raw_data_ingestion/) | Source files are generated and loaded repeatably | Not started |
| [6. Realistic operations](src/m6_realistic_operations/) | Late data, corrections, and reruns are handled | Not started |

## How every milestone is built

Every milestone follows the same standard, so once you know one you know them all.

**Each milestone is self-contained.** It has its own folder under `src/` with everything it needs, and it imports nothing from another milestone. Code is copied forward from one milestone to the next on purpose, so you can open any milestone and see the whole system at that point, and compare two folders to see how the code improved.

```
src/<milestone>/
  README.md              status, reading order, and how to run it
  docs/                  BRD.md, HLD.md, LLD.md
  notebooks/             the lab: numbered notebooks, run in order
  retail_profit_stack/   production code
  tests/                 tests for the production code
  data/                  this milestone's data
  evals/                 questions with known correct answers
  milestone_N_recap.html a closing page: what was asked, what you built, what you learned
```

**Each milestone is built in the same order**, the way a real data team works:

1. **Design documents.** Three short documents, each with a data flow diagram:
   - **BRD** (business requirements): what the business needs and why
   - **HLD** (high-level design): the parts of the system and how data moves between them
   - **LLD** (low-level design): the exact tables, formulas, functions, and checks
2. **Lab notebooks.** A short series of Jupyter notebooks that work the solution out step by step. They are written for someone who has never written LLM or agent code.
3. **Production code and tests.** The same logic rebuilt properly, with tests that prove it matches the notebooks.
4. **Recap page.** An animated page to open when you finish, showing how far the data system has come and what the next milestone adds.

**The lab notebooks teach you to use AI to meet a business requirement, and to know how far to trust it.** In every milestone:

- You answer the question by hand first, so you have an answer key.
- Every AI answer is shown beside that key, so you can see whether it was right.
- Each new idea is built by hand once before a library does it for you.
- Each notebook teaches one idea, opens with where you are, and ends with what you now know.
- The design documents are shown inside the notebooks at the point you need them.

**The rule behind every milestone:** let the model do what it is good at (understanding questions, choosing what to look up, explaining), keep every number in code, and check the result with code.

## Set up

Install Git, Python 3.12 or later, and [uv](https://docs.astral.sh/uv/). In this folder, run:

```sh
uv sync
```

Copy `.env.example` to `.env` and add an OpenRouter API key. Keep `.env` private; it is ignored by Git.

The labs are tested with `anthropic/claude-haiku-5.5`, a low-cost paid model, which is the default in `.env.example`. A whole milestone's lab costs a few US cents. You can set `MODEL_NAME=openrouter/free` to pay nothing, but free models are slow and often fail at the structured calls the labs rely on.

In VS Code, install the Python and Jupyter extensions. Open a notebook, choose **Select Kernel**, then **Python Environments**, and select this project's `.venv`.

See [setup/INSTRUCTIONS.md](setup/INSTRUCTIONS.md) for platform-specific notes.

## Run a milestone

Open the milestone's `README.md` for its reading order and its list of notebooks. To run its tests, which need no API key:

```sh
cd src/m1_mocked_business_answer
uv run pytest
```
