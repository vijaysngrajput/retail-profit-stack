# Milestone 1: Mocked business answer

**Status:** Done, signed off by the learner on 2026-11-11. Design documents approved, six lab notebooks reviewed by the learner, production code and tests passing.

This folder is self-contained. Everything the milestone needs is here, and nothing in it imports from another milestone.

| Folder | Holds |
|---|---|
| [docs/](docs/) | [BRD](docs/BRD.md), [HLD](docs/HLD.md), and [LLD](docs/LLD.md), each with a data flow diagram |
| `notebooks/` | The lab: six short notebooks, run in order, plus `lab_helpers.py` |
| `retail_profit_stack/` | Production code, rebuilt from the notebook |
| `tests/` | Tests for the production code |
| `data/mock/` | This milestone's mock data |
| `evals/` | Evaluation questions with known answers |
| [milestone_1_recap.html](milestone_1_recap.html) | A closing page to open when you finish the milestone |

## Read it in this order

1. [docs/BRD.md](docs/BRD.md): why this milestone exists and what the business needs.
2. [docs/HLD.md](docs/HLD.md): the parts of the system and how data moves between them.
3. [docs/LLD.md](docs/LLD.md): the exact detail of each part. Keep it open for the next two steps.
4. The lab notebooks in `notebooks/`, in order from `01` to `06`. Each teaches one idea and shows the document sections it relies on.
5. The code in `retail_profit_stack/` and `tests/`: the same logic, rebuilt for production.

6. [milestone_1_recap.html](milestone_1_recap.html): when you have finished, open this page in a browser. It looks back at the requirement, the system you built, and what you learned, and shows what comes next.

Section 11 of the LLD maps each notebook to the design sections and code files behind it.

## Run it

From this folder:

```
uv run pytest
```

The tests use a scripted fake model, so they need no key and no network.

To run the lab, open the notebooks in VS Code, choose the project's `.venv` as the kernel, and run them in order:

| Notebook | What you do | Model requests |
|---|---|---|
| `01_the_business_question` | Read the brief, explore the data, answer the question by hand | 0 |
| `02_first_llm_calls` | Call a model, get a structured reply, have AI draft the metric definitions | 2 |
| `03_llm_with_all_the_data` | Put the data in the prompt, ask the question, check the answer | 1 |
| `04_tools_and_agents` | Build one tool, run the agent loop by hand, then let LangChain run it | about 7 |
| `05_the_agent_answers` | Give an agent six tools and compare it with the single call | about 8 |
| `06_verify_and_production` | Check an answer with code and see the production version | 0 (about 15 with the evaluation on) |

Notebooks 2 to 5 need `OPENROUTER_API_KEY` in the `.env` file at the project root. The model is set by `MODEL_NAME` in the same file. The lab is tested with `anthropic/claude-haiku-5.5`, a low-cost paid model: the whole lab costs a few US cents. `MODEL_NAME=openrouter/free` costs nothing, but free models are slow, limited to about 50 requests a day, and often fail at the structured calls. Each notebook saves its result in `notebooks/results/` for the next one, so run them in order the first time.

To rebuild the mock data from its hand-chosen inputs:

```
uv run python -m retail_profit_stack.mock_data
```

The standard every milestone follows is described in the project [README](../../README.md#how-every-milestone-is-built). This milestone is the worked example of it.
