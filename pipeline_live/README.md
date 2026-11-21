# Live pipeline

This is not a milestone. It is a page that shows the whole data pipeline working, on files you choose.

You pick which files arrive, press **Run the pipeline**, and watch the real production code work through them. Every number on the page comes from that run.

| Step | What you see |
|---|---|
| 2 Load | One tile per file, coloured by what happened to it. Then the tables that were built |
| 3 Your desk | Files with renamed columns, each with the model's suggestion, for you to approve or refuse |
| 4 Check | The five checks with their counts, each finding, and what happens to it |
| 5 Review desk | Each record that needs a person, with **Accept** and **Exclude**. The next run obeys you |
| 6 Calculate | A bar per product. Click one to see how its figure is built, step by step |
| 7 Lineage | Which table is made from which, back to the files and their dates. Then a grid of the files behind one figure |
| 8 Run health and history | How long each step took, whether the run recalculated every month or only some, a bar per run, and the figures that moved |
| 9 Ask | The AI analyst's answer, the tools it called, and the verifier's result |

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
8. **Let the late files arrive.** After an "Everything" run, click "None", then "+ Late files", and run. Three files load, and one of them is a corrected version of a file you loaded before. Step 8 says the run was incremental, names the corrected file, and shows the three figures that moved. The camp stove's profit, unavailable until now, appears.
9. **Decide a finding.** At the review desk, press Exclude on the refund that is larger than its order line, then "Run again with your decisions". The refund is set aside, and the fleece pullover's September figure moves.
10. **Ask the analyst** the leader's question at the bottom, and read what it did step by step. After the late files, try: "Why did the trail water bottle's October profit change?"

## No key? It still works

Without an OpenRouter key in `.env`, the page switches AI off. Every step still runs: a renamed file waits at your desk and you type the mapping yourself. Only step 9, "Ask", needs a key.

The mappings to type for the renamed October files:

| File | Type this |
|---|---|
| `order_items_2026-10-12`, `-19`, `-26` | `list_price=unit_list_price, discount=discount_amount` |
| `payment_fees_2026-10-19`, `-26` | `fee_usd=fee_amount` |
| `shipments_2026-10-26` | `cost_1=pick_pack_cost, cost_2=carrier_cost` |

Open "Compare the rows" on each file to see why.

## What costs money

Two things call the model, through OpenRouter, with the key in your `.env` file:

- A suggestion for a renamed file: about 0.04 US cents each. Untick "Let AI suggest" to avoid it.
- "Ask the analyst": about half a US cent a question. It only runs when you press Ask.

Everything else is code and costs nothing.

## Good to know

- **It uses one milestone's production code**, named in `MILESTONE` near the top of `server.py`. Today that is milestone 6, the last one.
- **It works in its own folder**, `pipeline_live/workspace/`. It never changes a milestone's data. "Start over" on the page deletes that folder.
- **Files stay loaded between runs**, as in a real system. That is what lets a second run be compared with the first.
- **Late files load last**, after the files that arrived on time and after your desk, as they would in life.
- **Your decisions are kept** in the workspace folder, with the name "you". "Start over" forgets them.
- **The steps are played back slowly.** The pipeline itself takes a fraction of a second. The page pauses between steps so you can follow them. The run record shows the real time.
- **All data is fictional.**
