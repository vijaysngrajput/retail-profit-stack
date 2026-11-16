# Retail Profit Stack

## Project overview

**Retail Profit Stack: A Data Engineering Lab** is a learning project about how a large retailer can turn raw business activity into a trustworthy view of profitability. It is designed to help you become an **AI data engineer** by applying AI throughout the data lifecycle, not only in a final chatbot.

The project is inspired by retail economics and the kinds of data engineering challenges that arise in large retail businesses. It uses fictional data and transparent, documented assumptions. It does not claim to reproduce Amazon's internal systems, private data, or exact profit formulas.

## The learning approach

The project begins at the business-facing end of the system: an AI analyst answering a leader's question. The first milestone answers a useful retail question using mock data and mocked components. It does not build an ingestion platform.

Then the project works backward, replacing mocks one component at a time. Each milestone makes the answer's evidence more real, traceable, and trustworthy. This lets you learn what each layer contributes before you see the full system.

## The business experience

A retail leader can ask a question such as:

> Which products and categories generated the most contribution profit last month, what changed, and how confident should I be in those numbers?

The system returns a concise answer, shows the metrics and assumptions behind it, links the answer to its contributing records and transformations, and calls out data quality issues that could affect the result.

## Profit layers

The project makes the progression from activity to profit visible. The exact definitions are documented in each milestone's design documents.

1. **Business events:** orders, order items, discounts, cancellations, refunds, shipments, product costs, payment fees, and inventory movements.
2. **Net sales:** sales adjusted for discounts, cancellations, and refunds under defined rules.
3. **Gross profit:** net sales less product cost.
4. **Contribution profit:** gross profit less selected variable costs, such as fulfillment, shipping, payment processing, and returns.
5. **Business views:** profit by product, category, channel, and time, with the assumptions and source records available for inspection.

These are teaching definitions for a fictional retailer, not representations of Amazon's accounting policies or internal metrics.

## AI throughout the data lifecycle

AI is involved in every major component, with a clear boundary between AI assistance and verified results:

- **Business questions and metric definitions:** an AI assistant helps translate questions into documented metric definitions and identifies ambiguity for a person to resolve.
- **Source discovery and ingestion:** an AI helper inspects source schemas, explains fields, suggests mappings, and helps diagnose failed or changed inputs.
- **Data modeling and transformation:** AI assists with transformation drafts, joins, and explanations. Versioned code and explicit rules produce the actual tables and calculations.
- **Data quality:** AI summarizes anomalies, groups related failures, and suggests likely causes. Deterministic checks decide whether data passes, is quarantined, or needs review.
- **Lineage and observability:** AI explains where a metric came from, which loads and transformations contributed to it, and what changed between runs.
- **Business analysis:** an agent answers questions using approved metrics and data tools, cites the tables or records it used, and reports uncertainty or missing evidence.
- **Evaluation and improvement:** AI outputs are tested against known business questions and expected results. The system tracks accuracy, evidence use, data quality, and whether answers respect the metric definitions.

The AI features are part of the learning objective. They do not replace exact arithmetic, reproducible transformations, or quality gates for financial measures.

## Build direction: start at the answer, then work backward

The project has six milestones. Each one replaces one mock with a real or more realistic component. Each has its own folder under `src/`, listed in the [README](README.md#milestones).

1. **Business answer with mock components.** A small fictional retail dataset and precomputed metrics; the first AI analyst answers a bounded profitability question and shows its evidence.
2. **Metric and calculation layer.** Explicit, repeatable transformations for net sales, gross profit, and contribution profit replace the precomputed numbers; AI helps author and explain them.
3. **Quality and trust layer.** Checks for duplicates, missing costs, invalid event sequences, refund mismatches, and reconciliation differences; AI investigates and summarizes failures.
4. **Lineage and run history.** A record of which inputs and transformations produced each metric; AI explains the path and what changed across runs.
5. **Raw data and ingestion.** Generated source files replace the mocked source tables, with repeatable loading, schema-change handling, and AI-assisted source mapping that a person approves.
6. **Realistic operations.** Late-arriving and corrected files, incremental processing, a review desk, run health, and evaluation of the complete flow, with an AI agent that proposes improvements under human approval.

The project stays small at each step. A component is added only when it teaches a useful data engineering concept or improves the business answer.

## Learning goals

By working through the project, you gain practice in:

- Framing a business question as a data product.
- Modeling retail events and defining financial metrics precisely.
- Building repeatable ingestion and transformation workflows.
- Handling updates, late-arriving records, duplicates, and schema changes.
- Testing data quality and reconciling business totals.
- Tracing results through lineage and run history.
- Designing AI helpers and agents that work with data systems and tools.
- Evaluating AI explanations while keeping calculations reproducible.
- Communicating data assumptions, limitations, and confidence to business users.

## Guiding principles

- Start with the business decision and work backward to its evidence.
- Use fictional, generated data only.
- Make every metric definition and assumption inspectable.
- Keep the AI useful at each layer, but make outputs testable and traceable.
- Treat data quality as part of the product, not a cleanup task at the end.
- Build one learning milestone at a time; never the whole platform up front.

## Scope boundaries

This is a learning project. All of its data is fictional and generated. It does not connect to Amazon's internal systems or use confidential company information. It demonstrates a transparent retail profit calculation, and does not claim to match a particular retailer's accounting or operating model.
