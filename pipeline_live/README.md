# Live pipeline

This is not a milestone. It is a page that shows the whole data pipeline working, on files you choose.

You pick which files arrive, press **Run the pipeline**, and watch the real production code work through them. Every number on the page comes from that run.

| Step | What you see |
|---|---|
| 2 Load | One tile per file, coloured by what happened to it. Then the tables that were built |
| 3 Your desk | Files with renamed columns, each with the model's suggestion, for you to approve or refuse |
| 4 Check | The five checks with their counts, each finding, and what happens to it |
| 5 Calculate | A bar per product. Click one to see how its figure is built, step by step |
| 6 Trace | A grid of the files that product's figure came from: the feed down the side, the week along the top |
| 7 Run history | A bar per run, and the figures that moved since the run before |
| 8 Ask | The AI analyst's answer, the tools it called, and the verifier's result |

Hover over any bar, tile, or cell for its detail.

## Start it

From the project root:

```
uv run python pipeline_live/server.py
```

Your browser opens at http://localhost:8765. Press Ctrl+C in the terminal to stop it.

A web page cannot run Python by itself. So there are two parts:

| File | What it is |
|---|---|
| `server.py` | A small local program. It runs the production code and tells the page what happened at each step |
| `index.html` | The page. It shows the steps, and sends your choices and approvals back |

## What to try

1. **September only.** The default choice. Press Run. A few findings, twelve rows of profit, and no file waits.
2. **Then everything.** Click "Everything" and run again. Six files stop at your desk with renamed columns. Read the model's suggestion and its confidence, open "Look at the rows", and approve. The run record then shows what changed since the first run: which inputs, and which figures moved.
3. **Click a product's bar.** The page shows how its figure is built, and which files its records came from.
4. **Run the same files again.** Nothing is loaded twice, and the comparison says nothing changed.
5. **Leave out the product costs.** Every product's profit becomes unavailable, and the missing-cost check says why.
6. **Switch AI off.** A renamed file still waits. You type the mapping yourself.
7. **Refuse a mapping.** The file is rejected, and its records are missing from the figures.
8. **Ask the analyst** the leader's question at the bottom, and read what it did step by step.

## What costs money

Two things call the model, through OpenRouter, with the key in your `.env` file:

- A suggestion for a renamed file: about 0.04 US cents each. Untick "Let AI suggest" to avoid it.
- "Ask the analyst": about half a US cent a question. It only runs when you press Ask.

Everything else is code and costs nothing.

## Good to know

- **It uses one milestone's production code**, named in `MILESTONE` near the top of `server.py`. Today that is milestone 5. Change that one line to point it at a later milestone.
- **It works in its own folder**, `pipeline_live/workspace/`. It never changes a milestone's data. "Start over" on the page deletes that folder.
- **Files stay loaded between runs**, as in a real system. That is what lets a second run be compared with the first.
- **The steps are played back slowly.** The pipeline itself takes a fraction of a second. The page pauses between steps so you can follow them. The run record shows the real time.
- **All data is fictional.**
