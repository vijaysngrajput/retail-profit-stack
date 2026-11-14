# LLD: Milestone 2, Metric and calculation layer

**Status:** Approved by the learner; built
**Fits inside:** [HLD](HLD.md)

> **What this document is.** A low-level design (LLD) gives the exact detail needed to build each part named in the [HLD](HLD.md): table columns, rules, function signatures, and checks. Keep it open beside the notebooks and the code. Section 13 tells you which notebook and which code file build each part of this document.

The fixed contracts from milestone 1 are unchanged: the metric definitions (version 1.0.0), the six tools, the answer format, the verifier checks, and the seven evaluation questions. This document does not repeat them. Sections 4 to 6 define this milestone's new contract, the transformation layer. Review those most closely.

## 1. Files

Everything lives inside this milestone's folder, `src/m2_metric_calculation_layer/`. Nothing imports from another milestone. Paths are relative to that folder. Files marked *new* did not exist in milestone 1.

```
docs/                             BRD.md, HLD.md, LLD.md
notebooks/                        the lab: six notebooks, lab_helpers.py, results/
data/
  source/                         new: generated business records (CSV)
  warehouse/                      new: calculated tables (Parquet), written by the pipeline
  mock/                           quality_flags.csv, reporting_period.json (still mocked)
retail_profit_stack/
  source_data.py                  new: generates data/source/ (replaces mock_data.py)
  transform/                      new: the transformation layer
    contracts.py                  Column, TableSchema, TransformationSpec, conform()
    specs.py                      the source table schemas and the six transformation specs
    engines/
      base.py                     Engine: the interface every engine implements
      sql_engine.py               SqlEngine (DuckDB)
      pandas_engine.py            PandasEngine
      spark_engine.py             SparkEngine: the reserved slot, not built
    implementations/
      sql/<name>.sql              one query per transformation
      pandas/<name>.py            one function per transformation
    pipeline.py                   runs the transformations in order on one engine
    testing.py                    runs an implementation against the hand-worked cases
    drafting.py                   asks a model for an implementation; runs untrusted code safely
  store.py                        changed: reads data/warehouse/ and data/source/
  tools.py                        changed: get_evidence reads source rows
  schemas.py, agent.py, verify.py, evaluation.py, config.py, definitions/   as milestone 1
evals/
  m1_cases.json                   the seven questions from milestone 1
  m2_transform_cases.json         new: hand-worked cases for the six transformations
tests/
milestone_2_recap.html
```

## 2. Source tables

Seven CSV files in `data/source/`. Dates are `YYYY-MM-DD`. Amounts are US dollars with two decimal places.

Column types are `string`, `integer`, `decimal`, `month` (text like `2026-10`), and `date` (a real date). Source tables have no key: whether a row may repeat is a data quality question for milestone 3.

| Table | Columns | Notes |
|---|---|---|
| `products` | `product_id`, `product_name`, `category` | 12 rows, as milestone 1 |
| `orders` | `order_id`, `order_date`, `status` | `status` is `completed` or `cancelled` |
| `order_items` | `order_item_id`, `order_id`, `product_id`, `quantity`, `unit_list_price`, `discount_amount` | One row per product on an order. `discount_amount` is for the whole line |
| `refunds` | `refund_id`, `order_item_id`, `product_id`, `refund_date`, `refund_amount`, `return_handling_cost` | A line can have more than one refund |
| `shipments` | `shipment_id`, `order_item_id`, `product_id`, `ship_date`, `pick_pack_cost`, `carrier_cost` | One per shipped line |
| `payment_fees` | `fee_id`, `order_item_id`, `product_id`, `capture_date`, `fee_amount` | One per paid line |
| `product_costs` | `product_id`, `month`, `unit_cost` | The cost in force for a month (`YYYY-MM`) |

Refunds, shipments, and fees carry `product_id` so each can be summed without a join. They also carry `order_item_id`, so a figure can be traced to its order.

**How the generator makes the figures equal milestone 1's.** `source_data.py` starts from milestone 1's monthly inputs for each product (units, discount rate, refunds, return cost) and spreads them over individual orders, using a fixed random seed so the files are the same every time. Line discounts and fees are rounded to cents, and the last line of each product-month absorbs any rounding difference so the totals match exactly. A test compares the calculated table with milestone 1's table, value for value.

**What the generator plants on purpose.**

| In the records | Why it is there |
|---|---|
| No `product_costs` row for the camp stove in 2026-10 | The missing cost behind flag QF-001 |
| Three trail water bottle orders whose lines, shipments, and fees appear twice in 2026-10 | The duplicates behind flag QF-002. They are counted, as in milestone 1 |
| A 2026-09 refund of $60.00 on a sun hat line worth $25.00 | The oversized refund behind flag QF-003 |
| A few cancelled orders, with lines but no shipment or fee | To prove cancelled orders are left out |
| A few 2026-09 orders refunded in 2026-10 | To prove a refund counts in the month it is issued |
| Some lines with two refunds | To expose a calculation that joins detail to detail |

## 3. The standard table format

Every engine returns an **Apache Arrow table**. `conform(table, schema)` in `contracts.py` checks and normalises it, and every output passes through it.

| Rule | Detail |
|---|---|
| Columns | Exactly the contract's columns, in the contract's order |
| Types | `string`, `integer` (64-bit), `decimal` (64-bit float rounded to 2 places), `month` (string `YYYY-MM`), `date` (source tables only) |
| Missing values | Null. Allowed only in columns the contract marks as nullable |
| Key | The contract's key columns identify a row. Duplicate keys are an error |
| Order | Rows sorted by the key columns |
| Rounding | Amounts are rounded to cents once, after summing, never before |

A table that breaks a rule raises `ContractError` naming the rule and the column. Calculated tables are saved as `data/warehouse/<name>.parquet`.

## 4. Contracts

```python
@dataclass(frozen=True)
class Column:
    name: str
    type: Literal["string", "integer", "decimal", "month", "date"]
    nullable: bool = False
    description: str = ""

@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: tuple[Column, ...]
    key: tuple[str, ...]

@dataclass(frozen=True)
class TransformationSpec:
    name: str                 # also the name of its output table
    inputs: tuple[str, ...]   # source tables or other transformations
    output: TableSchema
    rule: str                 # the business rule, in words
    definitions: tuple[str, ...]   # metric terms from metrics_v1.json this produces
```

A spec contains no SQL and no pandas. It is the single description that people, engines, tests, and AI prompts all read.

## 5. The six transformations

Every output is keyed by `month`, `product_id`. A row exists only where the transformation has something to report.

| Name | Inputs | Output columns | Rule |
|---|---|---|---|
| `sales` | `orders`, `order_items` | `units_sold`, `gross_sales`, `discounts` | For lines on orders that are not cancelled, by the month of `order_date`: sum `quantity`; sum `quantity × unit_list_price`; sum `discount_amount` |
| `refund_totals` | `refunds` | `refunds`, `return_cost` | By the month of `refund_date`: sum `refund_amount`; sum `return_handling_cost` |
| `delivery_costs` | `shipments` | `fulfillment_cost`, `shipping_cost` | By the month of `ship_date`: sum `pick_pack_cost`; sum `carrier_cost` |
| `fee_totals` | `payment_fees` | `payment_fees` | By the month of `capture_date`: sum `fee_amount` |
| `product_cost` | `sales`, `product_costs` | `product_cost` (nullable) | `units_sold × unit_cost` for that product and month. Null when there is no cost row. Every `sales` row appears |
| `monthly_product_profit` | the five above | Milestone 1's columns exactly: `units_sold`, the 11 money terms, `metric_version` | One row per `sales` row. A product-month with no refunds, delivery costs, or fees has 0.00 for those terms. `net_sales`, `gross_profit`, and `contribution_profit` follow the metric definitions. A null `product_cost` makes `gross_profit` and `contribution_profit` null |

**A seventh task, for the lab only.** `profit_all_in_one` produces the same profit table in one step, straight from the six source tables. It is the "simple approach" that the six small transformations are compared with: harder for a model to get right, and harder for a person to check. It has reference implementations and hand-worked cases like the others, but the pipeline does not run it.

Two rules apply to all of them:

- **Sum first, then join.** Each source table is summed to product and month by its own transformation. Only those summed tables are joined. Joining order lines directly to refunds or shipments repeats rows and inflates the totals.
- **Count what is there.** Duplicated rows are summed like any others.

## 6. Engines

```python
class Engine(ABC):
    name: str                                   # "sql", "pandas", "spark"

    @abstractmethod
    def register(self, name: str, table: pa.Table) -> None:
        """Make a table available to implementations under this name."""

    @abstractmethod
    def load_implementation(self, spec: TransformationSpec) -> Implementation:
        """Find this engine's implementation of a transformation."""

    @abstractmethod
    def execute(self, implementation: Implementation, spec: TransformationSpec) -> pa.Table:
        """Run the implementation and return its result as an Arrow table."""

    def run(self, spec: TransformationSpec) -> pa.Table:
        """load_implementation, execute, then conform() to the spec's output schema."""
```

| Engine | An implementation is | How it runs |
|---|---|---|
| `SqlEngine` | `implementations/sql/<name>.sql`: one `SELECT` that names its input tables | In an in-memory DuckDB database where each input is registered as a view |
| `PandasEngine` | `implementations/pandas/<name>.py`: a function `transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame` | Called with the inputs as DataFrames |
| `SparkEngine` | Reserved: `implementations/spark/<name>.py`, a function over Spark DataFrames | Not built. The class exists and raises `NotImplementedError` with a note on what it needs |

`get_engine(name)` returns a fresh engine. The default comes from the setting `TRANSFORM_ENGINE` (`sql` unless set). `engine.run(spec)` uses the engine's own implementation; `engine.run(spec, implementation)` runs another one, which is how a draft is tested.

**Pipeline.** `run_pipeline(engine_name=None) -> PipelineRun` loads the source tables, checks them against their schemas, orders the six specs so each runs after its inputs, runs each on the engine, registers its output for the next, and writes the Parquet files. `PipelineRun` records the engine, each table's row count, and the time taken.

**Adding an engine later** takes three things and changes nothing else: a class that implements `Engine`, an implementation of each transformation, and a pass on the same conformance tests.

## 7. Changes to the tools and the store

The six tool signatures and result shapes do not change.

| Part | Change |
|---|---|
| `Store` | Loads `monthly_product_profit` from `data/warehouse/`. If the file is missing, it raises an error saying to run the pipeline. Also loads the source tables for evidence |
| `query_profit`, `compare_profit` | No change. They read the calculated table |
| `get_evidence` | Returns real source rows for the product and month: order lines, refunds, shipments, payment fees, and the product cost. Same record shape as before. The most notable records come first within each kind: a record that appears more than once, then the largest amounts. `is_sample` stays true because `limit` returns only some of the rows; a new field, `total_records`, says how many there are, and the note says they are real records |
| `get_quality_flags` | No change. Still reads the planted flags |

## 8. Hand-worked test cases

`evals/m2_transform_cases.json` holds the cases that define "correct" for a transformation. Each case has tiny input tables written out in full and the output worked out by hand.

| Transformation | Cases |
|---|---|
| `sales` | A plain order; a discounted line; a cancelled order (left out); two months and two products; a duplicated line (counted twice) |
| `refund_totals` | One refund; two refunds on one line; an order from one month refunded in the next |
| `delivery_costs` | One shipment; several products and months |
| `fee_totals` | One fee; several products and months |
| `product_cost` | Cost present; cost missing (null, and the row is kept) |
| `monthly_product_profit` | All terms present; no refunds that month (0.00); missing cost (profit null, sales still shown); two products |
| `profit_all_in_one` | One plain order; everything at once (a September order refunded in October, a line with two refunds, a cancelled order, a product with no cost); a line loaded twice |

There are 22 cases in all.

`run_cases(implementation, engine, spec) -> list[CaseResult]` runs an implementation on each case and compares the result with the expected output through `conform()`. A case fails if the code raises an error, breaks the contract, or returns a different value.

## 9. AI drafting

**The task.** `make_task_prompt(spec, language, context)` builds the prompt from the spec: the rule, the input table columns, and the output columns. `language` is `sql` or `pandas`. `context` is `trimmed` (only the tables this transformation reads) or `full` (every table in the system, as background).

The prompt mentions how to handle dates only when one of the task's inputs has a date column. An earlier version gave that advice on every task, and several models misapplied it to tasks with no dates. Removing it lifted them from between 64% and 86% of cases passed to 93% or more.

**The reply.** A structured answer:

```python
class DraftImplementation(BaseModel):
    reasoning: str = Field(description="Two or three sentences on the approach")
    code: str = Field(description="Only the SQL query, or only the Python function")
```

**Running a draft.** A draft is untrusted code. `run_draft(code, language, spec)` applies these limits before and while running it against the test cases:

| Language | Limits |
|---|---|
| SQL | Must be a single `SELECT` statement. Runs in an in-memory DuckDB database with access to files and the network switched off. Time limit of 10 seconds |
| pandas | Checked before it runs: it must define `transform`, may import only `pandas` and `numpy`, and may not use file, network, process, or dynamic-execution calls. Then it runs in a separate process with a time limit of 10 seconds |

A model's reply is capped at 12,000 tokens, so a model that rambles cannot run on indefinitely. A draft that breaks a limit is scored as failing every case, with the reason recorded. These limits reduce risk; they are not a perfect sandbox, and the lab says so.

**Scoring a draft.** `DraftResult` records the model, language, transformation, cases passed out of total, the first failure message, input and output tokens, cost in dollars as reported by OpenRouter, and seconds taken.

## 10. Model comparison

Each model is given each of the seven tasks (the six transformations and the all-in-one task) in each language. The models are set in one list at the top of the notebook. They were chosen from OpenRouter's catalogue when the lab was built, after a live trial, to cover a range of price and size and to include open-weight models. Each must support structured output.

| Model | Kind |
|---|---|
| `anthropic/claude-haiku-5.5` | Closed; the lab's default model |
| `deepseek/deepseek-v4.1-flash` | Open-weight |
| `openai/gpt-oss-20b` | Open-weight, small |
| `google/gemma-4-31b-it` | Open-weight |
| `mistralai/mistral-small-2603` | Open-weight, small |
| `meta-llama/llama-3.1-8b-instruct` | Open-weight, very small |

| Measure | How it is worked out |
|---|---|
| Accuracy | Test cases passed ÷ test cases run, by model and language |
| Fully correct | Transformations where every case passed, out of six |
| Cost | Sum of the cost OpenRouter reports for each call |
| Speed | Average seconds per draft |
| Prompt size | Input tokens with the full context and with the trimmed context, for the same task |

A full run makes 84 model calls, sent several at a time, and takes about three minutes. When the lab was built it cost about five cents. `TINY = True` runs two tasks in place of seven.

## 11. The agent that fixes its own draft

An agent built with LangChain's `create_agent`, as in milestone 1, with one tool:

```python
def run_tests(code: str) -> str
    # Runs the draft against the hand-worked cases with the limits in section 9.
    # Returns how many passed and, for each failure, the expected and actual rows.
```

The agent is given the same task prompt and told to call `run_tests` until every case passes, up to 5 attempts. It can also be handed an existing draft to repair (`starting_code`): that draft is tested first and recorded as attempt 1. `AgentDraftRun` records the final code, each attempt, whether every case passed, and the total tokens, cost, and time.

The lab uses it twice. First it hands the agent a draft with a known mistake (order lines joined straight to refunds) and watches the repair. Then it compares three ways of writing the all-in-one task from scratch: an inexpensive model's single draft, the same model with the tests as a tool, and a stronger model's single draft. Because models do not give the same answer twice, each is run three times.

A loop helps only a model that can act on a failure message. In trials when the lab was built, one small model went from 5 correct runs in 6 to 6 in 6 with the tests, while another repeated the same error on all five attempts and cost six times as much as a single draft. The attempt limit exists for that case.

Code from the agent is treated like any other draft. Passing the tests makes it a candidate. A person reviews it before it replaces a production implementation.

## 12. Tests

All tests run offline with no API key.

| Area | What is tested |
|---|---|
| Source data | Schemas, references between tables, each planted condition is present, and the files match the generator |
| Contracts | `conform()` accepts a correct table and rejects each kind of violation |
| Implementations | Every transformation passes every hand-worked case on both engines |
| Conformance | Both engines return identical tables for every transformation on the full data |
| Pipeline | Runs in dependency order; running twice gives identical files; the result equals milestone 1's profit table |
| Engine slot | `SparkEngine` implements the interface and reports clearly that it is not built |
| Drafting | The limits reject unsafe SQL and unsafe pandas code; a correct draft passes; a wrong draft fails with a useful message |
| Agent | With a scripted fake model: a failing draft is retried and the run is recorded |
| Tools | Milestone 1's tool tests pass on calculated data; evidence returns real source rows |
| Evaluation | Milestone 1's seven cases still score correctly |
| Notebook parity | The lab's hand-written transformations give the same output as production |

## 13. Where each part is built

The lab is six notebooks, run in order. Reusable code lives in `notebooks/lab_helpers.py`. Milestone 1's notebooks on LLM and agent basics are not repeated; the lab refers back to them.

From notebook 2 onward the notebooks import this milestone's production package. The learner writes the core ideas by hand first (a transformation in pandas and in SQL, and a test case), then uses the production versions. Running code that a model wrote needs care, and there is one careful implementation of that, not two.

| Notebook | What the learner does | Documents shown | This document's sections | Production code |
|---|---|---|---|---|
| 1. Where we are, and the business's records | Recalls the question and the answer key, and explores the source tables, including the planted problems | BRD 1, 3, 6 | 2. Source tables | `source_data.py`, `data/source/` |
| 2. One calculation, two engines | Writes `sales` by hand in pandas, writes hand-worked test cases, writes it again in SQL, and sees both give the same output | HLD 6 and LLD 3, 4 | 3 to 6, 8 | `transform/contracts.py`, `engines/`, `testing.py` |
| 3. A model drafts a transformation | Has one model draft a transformation, runs the tests on it, and studies what it got wrong | HLD 7 and LLD 9 | 9. AI drafting | `transform/drafting.py` |
| 4. Which model? Accuracy, cost, and speed | Sends every task to several models in SQL and pandas, with a full and a trimmed prompt, and charts the results | BRD 3 and LLD 10 | 10. Model comparison | `transform/drafting.py` |
| 5. An agent that tests and fixes its own code | Hands an agent a broken draft to repair, then compares a single draft with a test loop over several runs | LLD 11 | 11. The agent | `transform/drafting.py` |
| 6. The pipeline, and the same question again | Runs the pipeline on each engine, confirms the table equals milestone 1's, and asks the analyst the leader's question on calculated data | HLD 3, 8 and LLD 6, 7 | 6, 7, 12 | `transform/pipeline.py`, `store.py`, `tools.py`, `tests/` |
