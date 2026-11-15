"""Shared test helpers: a scripted fake model and a known-good answer."""

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from retail_profit_stack import tools
from retail_profit_stack.schemas import (
    AnalystAnswer,
    Caveat,
    Confidence,
    DefinitionRef,
    Figure,
    SourceRef,
    ToolCall,
)

MAIN_QUESTION = (
    "Which products and categories generated the most contribution profit last month, "
    "what changed, and how confident should I be in those numbers?"
)


class ScriptedChatModel(GenericFakeChatModel):
    """A fake model that replays a fixed list of messages, so agent tests need no network."""

    def bind_tools(self, tools, **kwargs):
        return self


def scripted_model(tool_calls: list[tuple[str, dict]], answer: AnalystAnswer) -> ScriptedChatModel:
    """A model that makes the given tool calls in order, then returns the given answer."""
    messages = [
        AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{index}"}])
        for index, (name, args) in enumerate(tool_calls)
    ]
    messages.append(
        AIMessage(
            content="",
            tool_calls=[{"name": "AnalystAnswer", "args": answer.model_dump(), "id": "call-final"}],
        )
    )
    return ScriptedChatModel(messages=iter(messages))


MAIN_TOOL_CALLS = [
    ("get_reporting_period", {}),
    ("get_metric_definition", {"metric": "contribution_profit"}),
    ("query_profit", {"month": "2026-10", "group_by": "product", "top_n": 3}),
    ("query_profit", {"month": "2026-10", "group_by": "category"}),
    ("compare_profit", {"month": "2026-10", "previous_month": "2026-09", "group_by": "category"}),
    ("get_quality_flags", {"month": "2026-10"}),
]


def main_tool_log() -> list[ToolCall]:
    """The tool log a correct run of the main question would produce."""
    functions = {
        "get_reporting_period": tools.get_reporting_period,
        "get_metric_definition": tools.get_metric_definition,
        "query_profit": tools.query_profit,
        "compare_profit": tools.compare_profit,
        "get_quality_flags": tools.get_quality_flags,
    }
    return [
        ToolCall(name=name, arguments=args, result=functions[name](**args).model_dump())
        for name, args in MAIN_TOOL_CALLS
    ]


# ---- New in milestone 4: a correct answer to "why did this figure change since the last run?"

CHANGE_QUESTION = (
    "Why did the trail water bottle's October 2026 contribution profit change since the last run?"
)
CHANGE_TOOL_CALLS = [
    ("compare_runs", {"month": "2026-10", "product_id": "trail water bottle"}),
    ("get_quality_flags", {"month": "2026-10", "product_id": "P001"}),
]


def change_tool_log() -> list[ToolCall]:
    """The tool log a correct run of CHANGE_QUESTION would produce."""
    functions = {"compare_runs": tools.compare_runs, "get_quality_flags": tools.get_quality_flags}
    return [
        ToolCall(name=name, arguments=args, result=functions[name](**args).model_dump())
        for name, args in CHANGE_TOOL_CALLS
    ]


def main_answer() -> AnalystAnswer:
    """A correct answer to the main question, built only from tool results."""
    products = tools.query_profit("2026-10", "product", top_n=3).rows
    categories = tools.query_profit("2026-10", "category").rows
    changes = {
        row.entity_id: row for row in tools.compare_profit("2026-10", "2026-09", "category").rows
    }
    quality = tools.get_quality_flags("2026-10")
    figures = [
        Figure(
            label=f"{row.entity_name}, contribution profit",
            metric="contribution_profit",
            kind="value",
            value=row.contribution_profit,
            unit="USD",
            month="2026-10",
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            source_tool="query_profit",
        )
        for row in [*products, *categories]
    ]
    figures.append(
        Figure(
            label="Hydration, change in contribution profit",
            metric="contribution_profit",
            kind="change",
            value=changes["Hydration"].change,
            unit="USD",
            month="2026-10",
            entity_type="category",
            entity_id="Hydration",
            source_tool="compare_profit",
        )
    )
    top = products[0]
    return AnalystAnswer(
        status="answered",
        headline=(
            f"{top.entity_name} led products with ${top.contribution_profit:,.2f} of contribution "
            f"profit in 2026-10, and Hydration led categories with "
            f"${categories[0].contribution_profit:,.2f}."
        ),
        narrative=(
            f"Hydration rose by ${changes['Hydration'].change:,.2f} from 2026-09. Camp cannot be "
            "compared because Camp stove has no product cost."
        ),
        figures=figures,
        definitions_used=[DefinitionRef(metric="contribution_profit", version="1.0.0")],
        assumptions=["Refunds count in the month they are issued."],
        caveats=[Caveat(flag_id=flag.flag_id, text=flag.description) for flag in quality.flags],
        confidence=Confidence(level=quality.confidence_level, reasons=quality.confidence_reasons),
        sources=[SourceRef(table="monthly_product_profit"), SourceRef(table="quality_flags")],
        run_id=quality.run_id,
    )


def change_answer() -> AnalystAnswer:
    """A correct answer to CHANGE_QUESTION, built only from tool results."""
    comparison = tools.compare_runs("2026-10", "trail water bottle")
    quality = tools.get_quality_flags("2026-10", "P001")
    moved = comparison.figures_changed[0]
    values = {
        "earlier_run_value": moved.earlier,
        "value": moved.later,
        "run_change": moved.change,
    }
    figures = [
        Figure(
            label=f"Trail water bottle, contribution profit ({kind})",
            metric="contribution_profit",
            kind=kind,
            value=value,
            unit="USD",
            month="2026-10",
            entity_type="product",
            entity_id="P001",
            source_tool="compare_runs",
        )
        for kind, value in values.items()
    ]
    return AnalystAnswer(
        status="answered",
        headline=f"It fell by ${abs(moved.change):,.2f} because duplicated records are now set aside.",
        narrative=f"It was ${moved.earlier:,.2f} in {comparison.earlier_run}.",
        figures=figures,
        definitions_used=[DefinitionRef(metric="contribution_profit", version="1.0.0")],
        caveats=[Caveat(flag_id=flag.flag_id, text=flag.description) for flag in quality.flags],
        confidence=Confidence(level=quality.confidence_level, reasons=quality.confidence_reasons),
        sources=[SourceRef(table="run_history"), SourceRef(table="quality_flags")],
        run_id=comparison.run_id,
    )
