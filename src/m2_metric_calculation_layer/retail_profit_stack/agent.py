"""The analyst agent: a model, the six tools, and a structured answer.

Implements LLD section 6 (Agent) and the request trace in section 7. The model
chooses tools and writes the words. Every number comes from a tool, and the
verifier checks the result before it is returned.
"""

import os
import time

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from retail_profit_stack import tools
from retail_profit_stack.config import DEFAULT_MODEL, MILESTONE_DIR, OPENROUTER_BASE_URL
from retail_profit_stack.schemas import AnalystAnswer, AnalystRun, ToolCall
from retail_profit_stack.store import Store
from retail_profit_stack.verify import verify_answer

SYSTEM_PROMPT = """You are the profit analyst for Kestrel Ridge Outfitters, a fictional online \
retailer of outdoor gear. You answer questions about profit for retail leaders.

What you can answer:
- Net sales, gross profit, and contribution profit, and their components, by product or by \
category, for the months that have data.
- How a figure changed between two months.
- How a metric is defined.
- Known data problems behind a figure.

Rules:
1. Every number you give must come from a tool result. Never add, subtract, average, rank, or \
round numbers yourself. If you need a total, a ranking, or a change, call the tool that returns it.
2. If a question says "last month" or names no month, call get_reporting_period first.
3. Before you give any figure, call get_quality_flags for each month and scope you report on. \
Set confidence.level to the confidence_level the tool returned (the worst one if you called it \
more than once), and list every returned flag in caveats with its flag_id.
4. Put each number in figures exactly as the tool returned it. Use entity_id values from the \
tool results. A value the tool returned as null is unavailable: report it as null and explain why.
5. In definitions_used, give the metric name and metric_version for every metric in your figures.
6. In sources, list the tables the tools read.
7. Write amounts in the headline and narrative exactly as returned, for example $5,188.20.
8. Decline, with status "declined", no figures, and a decline_reason, when a question asks for \
a forecast, for costs or metrics that are not listed above, for months without data, or for \
anything other than this retailer's profit.
"""

# The project root holds the shared .env file (two levels above this milestone's folder).
ENV_FILE = MILESTONE_DIR.parent.parent / ".env"


def make_model() -> ChatOpenAI:
    """The live model, reached through OpenRouter with the key in the project's .env file."""
    load_dotenv(ENV_FILE)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(f"No OPENROUTER_API_KEY found. Add it to {ENV_FILE}")
    return ChatOpenAI(
        model=os.getenv("MODEL_NAME", DEFAULT_MODEL),
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(api_key),
        timeout=120,
        max_retries=5,
        temperature=0,
    )


def make_tools(log: list[ToolCall], store: Store | None = None) -> list[StructuredTool]:
    """Wrap the six tools for the agent. Each call and its result is appended to the log."""

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
        """Return sample source records (orders, refunds, costs) behind one product's figures."""
        return record(
            "get_evidence", tools.get_evidence, month=month, product_id=product_id, limit=limit
        )

    def get_quality_flags(
        month: str, product_id: str | None = None, category: str | None = None
    ) -> str:
        """Return known data problems for a month and the confidence level they imply.

        Leave product_id and category empty for the whole month, or set one to narrow the scope.
        """
        return record(
            "get_quality_flags",
            tools.get_quality_flags,
            month=month,
            product_id=product_id,
            category=category,
        )

    functions = [
        get_reporting_period,
        get_metric_definition,
        query_profit,
        compare_profit,
        get_evidence,
        get_quality_flags,
    ]
    return [StructuredTool.from_function(function) for function in functions]


def run_analyst(
    question: str, model: BaseChatModel | None = None, store: Store | None = None
) -> AnalystRun:
    """Answer one question. Returns the answer, the tool log, and the verification report.

    Pass a model to use something other than the live one; the tests pass a scripted fake.
    """
    start = time.time()
    model = model or make_model()
    model_name = getattr(model, "model_name", type(model).__name__)
    log: list[ToolCall] = []
    agent = create_agent(
        model=model,
        tools=make_tools(log, store),
        system_prompt=SYSTEM_PROMPT,
        response_format=ToolStrategy(AnalystAnswer),
    )
    run = AnalystRun(question=question, model=model_name)
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": question}]}, {"recursion_limit": 40}
        )
        run.answer = result.get("structured_response")
        if run.answer is None:
            run.error = "The model finished without a structured answer"
    except Exception as error:  # noqa: BLE001 - a model failure must not hide the tool log
        run.error = f"{type(error).__name__}: {error}"
    if run.answer is not None:
        run.verification = verify_answer(run.answer, log)
    run.tool_log = log
    run.seconds = round(time.time() - start, 1)
    return run
