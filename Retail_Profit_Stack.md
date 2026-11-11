# Retail Profit Stack

## Project overview

**Retail Profit Stack: A Data Engineering Lab** is a learning project about how a large retailer can turn raw business activity into a trustworthy view of profitability. It is designed to help the learner become an **AI data engineer** by applying AI throughout the data lifecycle, not only in a final chatbot.

The project is inspired by retail economics and the kinds of data engineering challenges that arise in large retail businesses. It uses fictional data and transparent, documented assumptions. It does not claim to reproduce Amazon's internal systems, private data, or exact profit formulas.

## The learning approach

We will begin at the business-facing end of the system, as the UnderCover insurance lab begins with an agent making a claim decision. The first version will answer a useful retail question using mock data and mocked components. It will not initially build a complete ingestion platform.

Then we will work backward, replacing mocks one component at a time. Each step will make the answer's evidence more real, traceable, and trustworthy. This lets us learn what each layer contributes before building the full system.

## The business experience

A retail leader should be able to ask a question such as:

> Which products and categories generated the most contribution profit last month, what changed, and how confident should I be in those numbers?

The system should return a concise answer, show the metrics and assumptions behind it, link the answer to its contributing records and transformations, and call out data quality issues that could affect the result.

## Profit layers

The project will make the progression from activity to profit visible. Exact definitions will be agreed and documented as the project develops.

1. **Business events:** orders, order items, discounts, cancellations, refunds, shipments, product costs, payment fees, and inventory movements.
2. **Net sales:** sales adjusted for discounts, cancellations, and refunds under defined rules.
3. **Gross profit:** net sales less product cost.
4. **Contribution profit:** gross profit less selected variable costs, such as fulfillment, shipping, payment processing, and returns.
5. **Business views:** profit by product, category, channel, and time, with the assumptions and source records available for inspection.

These are teaching definitions for a fictional retailer, not representations of Amazon's accounting policies or internal metrics.

## AI throughout the data lifecycle

AI will be involved in every major component, with a clear boundary between AI assistance and verified results:

- **Business questions and metric definitions:** an AI assistant helps translate questions into documented metric definitions and identifies ambiguity for the learner to resolve.
- **Source discovery and ingestion:** an AI helper inspects source schemas, explains fields, suggests mappings, and helps diagnose failed or changed inputs.
- **Data modeling and transformation:** AI assists with transformation drafts, joins, and explanations. Versioned code and explicit rules produce the actual tables and calculations.
- **Data quality:** AI summarizes anomalies, groups related failures, and suggests likely causes. Deterministic checks decide whether data passes, is quarantined, or needs review.
- **Lineage and observability:** AI explains where a metric came from, which loads and transformations contributed to it, and what changed between runs.
- **Business analysis:** an agent answers questions using approved metrics and data tools, cites the tables or records it used, and reports uncertainty or missing evidence.
- **Evaluation and improvement:** AI outputs are tested against known business questions and expected results. The system tracks accuracy, evidence use, data quality, and whether answers respect the metric definitions.

The AI features are part of the learning objective. They do not replace exact arithmetic, reproducible transformations, or quality gates for financial measures.

## Build direction: start at the answer, then work backward

The stages below are an initial learning path, not a detailed implementation plan. Each stage can replace one mock with a real or more realistic component.

1. **Business answer with mock components** — use a small fictional retail dataset and precomputed metrics; build the first AI analyst that answers a bounded profitability question and shows its evidence.
2. **Metric and calculation layer** — replace precomputed numbers with explicit, repeatable transformations for net sales, gross profit, and contribution profit; add AI help for authoring and explaining the models.
3. **Quality and trust layer** — add checks for duplicates, missing costs, invalid event sequences, refund mismatches, and reconciliation differences; use AI to investigate and summarize failures.
4. **Lineage and run history** — record which inputs and transformations produced each metric; let the AI explain the path and identify changes across runs.
5. **Raw data and ingestion** — replace mocked source tables with generated source files or controlled sample feeds; add repeatable loading, schema-change handling, and AI-assisted source mapping.
6. **More realistic operations** — simulate late-arriving events, corrected orders, and reruns; add incremental processing, observability, and evaluation of the complete flow.

We will keep the project small at each step and only add a component when it teaches a useful data engineering concept or improves the business answer.

## Learning goals

By building the project, the learner should gain practice in:

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
- Use fictional or synthetic data unless a future stage explicitly selects a public or authorized source.
- Make every metric definition and assumption inspectable.
- Keep the AI useful at each layer, but make outputs testable and traceable.
- Treat data quality as part of the product, not a cleanup task at the end.
- Build only the next learning milestone; do not build the whole platform up front.

## Initial scope boundaries

The first version is a learning prototype. It will use mock data and mocked upstream components, and it will not connect to Amazon's internal systems or use confidential company information. It will demonstrate a transparent retail profit calculation rather than claim to match a particular retailer's accounting or operating model.
