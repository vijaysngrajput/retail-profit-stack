"""The analyst agent: a model, the seven tools, and a structured answer.

Implements LLD sections 6 to 8. The model chooses tools and writes the words. Every number
comes from a tool, and the verifier checks the result before it is returned. New in
milestone 4: the compare_runs tool, a record of every step, and optional tracing in Langfuse.
"""

import os
import time

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from retail_profit_stack import tools
from retail_profit_stack.config import DEFAULT_MODEL, MILESTONE_DIR, OPENROUTER_BASE_URL
from retail_profit_stack.schemas import AnalystAnswer, AnalystRun, ToolCall
from retail_profit_stack.store import Store, get_store
from retail_profit_stack.tracing import StepRecorder, langfuse_handler, trace_labels
from retail_profit_stack.verify import verify_answer

SYSTEM_PROMPT = """You are the profit analyst for Kestrel Ridge Outfitters, a fictional online \
retailer of outdoor gear. You answer questions about profit for retail leaders.

What you can answer:
- Net sales, gross profit, and contribution profit, and their components, by product or by \
category, for the months that have data.
- How a figure changed between two months.
- How a metric is defined.
- Known data problems behind a figure.
- Where a figure came from: the records behind it and the pipeline run that calculated it.

Rules:
1. Every number you give must come from a tool result. Never add, subtract, average, rank, or \
round numbers yourself. If you need a total, a ranking, or a change, call the tool that returns it.
2. If a question says "last month" or names no month, call get_reporting_period first.
3. Before you give any figure, call get_quality_flags for each month and scope you report on. \
Use the narrowest scope that covers your answer: pass product_id when the question is about one \
product, category when it is about one category, and neither when it is about the whole month. \
Set confidence.level to the confidence_level the tool returned (the worst one if you called it \
more than once), and list every flag that any call returned in caveats with its flag_id, \
including low-severity flags and flags about other products or an earlier month.
4. Every metric value you mention (a value returned by query_profit or compare_profit) must \
also be an entry in figures, so an answer that gives a metric value never has an empty figures \
list. A count of records from a quality flag is not a figure. Put each number in figures exactly \
as the tool returned it. Use entity_id values from the \
tool results. A value the tool returned as null is unavailable: report it as null and explain why.
5. In definitions_used, give the metric name and metric_version for every metric in your figures. \
The metric_version in a tool result is the version of every term in that result, not only of \
the metric you asked for.
6. In sources, list the tables the tools read.
7. Write amounts in the headline and narrative exactly as returned, for example $5,188.20.
8. Keep the answer short. Give at most 15 figures, and always include the ones the question \
asks for: for the top products or categories give each one's value, and for "what changed" give \
each category's change. Keep the narrative under 120 words.
9. Decline, with status "declined", no figures, and a decline_reason, when a question asks for \
a forecast, for costs or metrics that are not listed above, for months without data, or for \
anything other than this retailer's profit.
10. Tool results carry a run_id: the pipeline run the figures came from. Set run_id in your \
answer to that value. When asked where a figure came from, call query_profit for the figure \
itself and get_evidence for the records behind it, and report its record_counts and \
set_aside_count.
"""

# Added to the instructions only when the analyst has the compare_runs tool (LLD section 8).
RUN_TOOL_RULE = """11. When asked whether or why a figure changed "since the last run" or \
"between runs", call compare_runs. In figures, give the earlier run's value with kind \
"earlier_run_value", today's value with kind "value", and the change with kind "run_change", \
each exactly as returned. Give only the reasons compare_runs shows: changed settings, inputs, \
code, checks, records, and findings. If it shows none, say the reason is not recorded.
"""

# Without the tool, the analyst has no record of earlier runs and must say so.
NO_RUN_TOOL_RULE = """11. You have no record of earlier pipeline runs. Decline a question \
about what changed "since the last run" or "between runs".
"""

# The project root holds the shared .env file (two levels above this milestone's folder).
ENV_FILE = MILESTONE_DIR.parent.parent / ".env"


def make_model(timeout: int = 120) -> ChatOpenAI:
    """The live model, reached through OpenRouter with the key in the project's .env file.

    timeout is how many seconds one call may take before it is given up and tried again.
    """
    load_dotenv(ENV_FILE)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(f"No OPENROUTER_API_KEY found. Add it to {ENV_FILE}")
    return ChatOpenAI(
        model=os.getenv("MODEL_NAME", DEFAULT_MODEL),
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(api_key),
        timeout=timeout,
        max_retries=5,
        temperature=0,
        # Ask OpenRouter to report what each call cost, so a run can add it up.
        extra_body={"usage": {"include": True}},
    )


def make_tools(
    log: list[ToolCall], store: Store | None = None, run_tool: bool = True
) -> list[StructuredTool]:
    """Wrap the tools for the agent. Each call and its result is appended to the log.

    run_tool=False leaves compare_runs out, so the agent has milestone 3's six tools.
    """

    def record(name: str, function, **arguments) -> str:
        try:
            result = function(**arguments, store=store)
        except tools.ToolInputError as error:
            log.append(ToolCall(name=name, arguments=arguments, error=str(error)))
            return f"Error: {error}"
        log.append(ToolCall(name=name, arguments=arguments, result=result.model_dump()))
        return result.model_dump_json()

    def get_reporting_period() -> str:
        """Say which month 'last month' (current_month) is, and which months have data."""
        return record("get_reporting_period", tools.get_reporting_period)

    def get_metric_definition(metric: str) -> str:
        """Return a metric's formula, components, assumptions, and version.

        metric is one of: net_sales, gross_profit, contribution_profit, or a component such as
        gross_sales, discounts, refunds, product_cost, shipping_cost.
        """
        return record("get_metric_definition", tools.get_metric_definition, metric=metric)

    def query_profit(
        month: str, group_by: str, metric: str = "contribution_profit", top_n: int | None = None
    ) -> str:
        """Return all profit figures for a month, ranked highest first by one metric.

        month is YYYY-MM. group_by is 'product' or 'category'. top_n keeps only the top rows.
        Category rows are summed for you. is_complete is false when a value is missing.
        metric_version is the version of every term in the rows, such as net_sales.
        """
        return record(
            "query_profit",
            tools.query_profit,
            month=month,
            group_by=group_by,
            metric=metric,
            top_n=top_n,
        )

    def compare_profit(
        month: str, previous_month: str, group_by: str, metric: str = "contribution_profit"
    ) -> str:
        """Return the change and percentage change in one metric between two months.

        group_by is 'product' or 'category'. Rows are sorted from the biggest fall to the
        biggest rise. change is null when the two months cannot be compared.
        """
        return record(
            "compare_profit",
            tools.compare_profit,
            month=month,
            previous_month=previous_month,
            group_by=group_by,
            metric=metric,
        )

    def get_evidence(month: str, product_id: str, limit: int = 5) -> str:
        """Return the records behind one product's figures for a month, read from lineage.

        record_counts counts every record behind the figures, by source table. set_aside_count
        is how many records were quarantined. records shows the largest few. product_id may
        be a product id such as P001, or the product's name.
        """
        return record(
            "get_evidence", tools.get_evidence, month=month, product_id=product_id, limit=limit
        )

    def get_quality_flags(
        month: str, product_id: str | None = None, category: str | None = None
    ) -> str:
        """Return known data problems for a month and the confidence level they imply.

        Leave product_id and category empty for the whole month, or set one to narrow the scope.
        product_id may be a product id such as P011, or the product's name such as sun hat.
        """
        return record(
            "get_quality_flags",
            tools.get_quality_flags,
            month=month,
            product_id=product_id,
            category=category,
        )

    def compare_runs(
        month: str | None = None,
        product_id: str | None = None,
        metric: str = "contribution_profit",
    ) -> str:
        """Compare the latest pipeline run with the one before it.

        Returns what changed between the two runs (settings, inputs, code, checks), the figures
        that moved for one metric, and the records counted in only one of the runs. Set month
        and product_id to narrow it to one figure. product_id may be a product's name. Leave
        both empty to see every figure that changed.
        """
        return record(
            "compare_runs", tools.compare_runs, month=month, product_id=product_id, metric=metric
        )

    functions = [
        get_reporting_period,
        get_metric_definition,
        query_profit,
        compare_profit,
        get_evidence,
        get_quality_flags,
    ]
    if run_tool:
        functions.append(compare_runs)
    return [StructuredTool.from_function(function) for function in functions]


def run_analyst(
    question: str,
    model: BaseChatModel | None = None,
    store: Store | None = None,
    trace: bool = False,
    run_tool: bool = True,
) -> AnalystRun:
    """Answer one question. Returns the answer, the tool log, the steps, and the verification.

    Pass a model to use something other than the live one; the tests pass a scripted fake.
    trace=True also sends every step to Langfuse. run_tool=False leaves compare_runs out.
    """
    start = time.time()
    model = model or make_model()
    model_name = getattr(model, "model_name", type(model).__name__)
    store = store or get_store()
    log: list[ToolCall] = []
    rule = RUN_TOOL_RULE if run_tool else NO_RUN_TOOL_RULE
    agent = create_agent(
        model=model,
        tools=make_tools(log, store, run_tool),
        system_prompt=SYSTEM_PROMPT + rule,
        response_format=ToolStrategy(AnalystAnswer),
    )
    run = AnalystRun(question=question, model=model_name, run_id=store.run_id)

    # The recorder keeps the steps in memory. Langfuse's handler, when asked for, sends them on.
    recorder = StepRecorder()
    callbacks: list = [recorder]
    langfuse = langfuse_handler() if trace else None
    if langfuse is not None:
        callbacks.append(langfuse)
    config: RunnableConfig = {
        "recursion_limit": 24,
        "callbacks": callbacks,
        "metadata": trace_labels(store.run_id, "profit analyst"),
    }
    try:
        result = agent.invoke({"messages": [{"role": "user", "content": question}]}, config)
        run.answer = result.get("structured_response")
        if run.answer is None:
            run.error = "The model finished without a structured answer"
    except Exception as error:  # noqa: BLE001 - a model failure must not hide the tool log
        run.error = f"{type(error).__name__}: {error}"
    if run.answer is not None:
        # Code knows which run the tools read. If the model left run_id empty, fill it in.
        # The verifier still fails an answer that names a different run.
        if run.answer.run_id is None and run.answer.status == "answered":
            run.answer.run_id = store.run_id
        run.verification = verify_answer(run.answer, log)
    run.tool_log = log
    run.steps = recorder.steps
    run.cost = round(recorder.cost, 6)
    if langfuse is not None:
        run.trace_id = langfuse.last_trace_id or ""
    run.seconds = round(time.time() - start, 1)
    return run
