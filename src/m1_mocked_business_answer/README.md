# Milestone 1: Mocked business answer

**Status:** Done, signed off by the learner on 2026-11-11. Design documents approved, lab notebook run by the learner, production code and tests passing.

This folder is self-contained. Everything the milestone needs is here, and nothing in it imports from another milestone.

| Folder | Holds |
|---|---|
| [docs/](docs/) | [BRD](docs/BRD.md), [HLD](docs/HLD.md), and [LLD](docs/LLD.md), each with a data flow diagram |
| `notebooks/` | The lab notebook: using AI to answer the business question, step by step |
| `retail_profit_stack/` | Production code, rebuilt from the notebook |
| `tests/` | Tests for the production code |
| `data/mock/` | This milestone's mock data |
| `evals/` | Evaluation questions with known answers |

## Read it in this order

1. [docs/BRD.md](docs/BRD.md): why this milestone exists and what the business needs.
2. [docs/HLD.md](docs/HLD.md): the parts of the system and how data moves between them.
3. [docs/LLD.md](docs/LLD.md): the exact detail of each part. Keep it open for the next two steps.
4. The lab notebook in `notebooks/`: six parts, each showing the document sections it relies on.
5. The code in `retail_profit_stack/` and `tests/`: the same logic, rebuilt for production.

Section 11 of the LLD maps each part of the lab to the design sections and code files behind it.

## Run it

From this folder:

```
uv run pytest
```

The tests use a scripted fake model, so they need no key and no network.

To run the lab, open `notebooks/m1_mocked_business_answer.ipynb` in VS Code and choose the project's `.venv` as the kernel. The cells that call a model need `OPENROUTER_API_KEY` in the `.env` file at the project root; without it they are skipped.

To rebuild the mock data from its hand-chosen inputs:

```
uv run python -m retail_profit_stack.mock_data
```

The expectations for this milestone are in [MILESTONES.md](../../MILESTONES.md).
