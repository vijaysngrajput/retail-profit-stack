"""LLD section 8: each check passes a correct answer and fails a deliberately broken one."""

from helpers import change_answer, change_tool_log, main_answer, main_tool_log
from retail_profit_stack.schemas import AnalystAnswer, DefinitionRef, SourceRef
from retail_profit_stack.verify import numbers_in_text, verify_answer


def failed(answer, log=None):
    report = verify_answer(answer, main_tool_log() if log is None else log)
    return {check.name for check in report.checks if not check.passed}


def test_correct_answer_passes_every_check():
    report = verify_answer(main_answer(), main_tool_log())
    assert report.passed, [check for check in report.checks if not check.passed]
    assert len(report.checks) == 9  # milestone 1's seven, figures_listed, and run_cited


def test_wrong_figure_is_caught():
    answer = main_answer()
    answer.figures[0].value += 100
    assert failed(answer) == {"figures_match_tools"}


def test_figure_for_the_wrong_month_is_caught():
    answer = main_answer()
    answer.figures[0].month = "2026-09"
    assert "figures_match_tools" in failed(answer)


def test_invented_number_in_the_text_is_caught():
    answer = main_answer()
    answer.narrative += " That is roughly $61,000 a year."
    assert failed(answer) == {"no_unsupported_numbers"}


def test_a_year_written_in_words_is_not_treated_as_a_figure():
    answer = main_answer()
    answer.headline = "In October 2026, Hydration led the categories."
    assert failed(answer) == set()
    answer.headline = "In October 2031, Hydration led the categories."
    assert failed(answer) == {"no_unsupported_numbers"}


def test_rounded_number_in_the_text_is_allowed():
    answer = main_answer()
    answer.narrative = "Trail water bottle made about $5,157 and ranked 1 of 12 products."
    assert failed(answer) == set()


def test_missing_sources_are_caught():
    answer = main_answer()
    answer.sources = []
    assert failed(answer) == {"sources_cited"}


def test_source_that_was_never_read_is_caught():
    answer = main_answer()
    answer.sources.append(SourceRef(table="general_ledger"))
    assert failed(answer) == {"sources_cited"}


def test_missing_or_stale_definition_is_caught():
    answer = main_answer()
    answer.definitions_used = [DefinitionRef(metric="contribution_profit", version="0.9.0")]
    assert failed(answer) == {"definitions_stated"}


def test_confidence_that_ignores_the_rule_is_caught():
    answer = main_answer()
    answer.confidence.level = "high"
    assert failed(answer) == {"confidence_matches_rule"}


def test_figures_without_a_quality_check_are_caught():
    log = [call for call in main_tool_log() if call.name != "get_quality_flags"]
    answer = main_answer()
    answer.caveats = []
    answer.sources = answer.sources[:1]
    assert failed(answer, log) == {"confidence_matches_rule"}


def test_unmentioned_flag_is_caught():
    answer = main_answer()
    answer.caveats = answer.caveats[:1]
    assert failed(answer) == {"flags_mentioned"}


def test_clean_decline_passes_and_messy_decline_fails():
    clean = AnalystAnswer(
        status="declined",
        headline="I can't forecast.",
        narrative="",
        decline_reason="Forecasts are outside the approved metrics.",
    )
    assert verify_answer(clean, []).passed
    no_reason = clean.model_copy(update={"decline_reason": None})
    assert failed(no_reason, []) == {"decline_is_clean"}
    with_figures = clean.model_copy(update={"figures": main_answer().figures[:1]})
    assert "decline_is_clean" in failed(with_figures, [])


def test_dates_ids_and_versions_are_not_treated_as_figures():
    text = "In 2026-10, P001 (QF-002, ORD-20401) under version 1.0.0 made $5,188.20, up 2.9%."
    assert numbers_in_text(text) == [(5188.20, 2), (2.9, 1)]


def test_amounts_in_the_text_with_no_figures_listed_fails():
    answer = main_answer()
    answer.figures = []
    assert "figures_listed" in failed(answer)
    answer.headline, answer.narrative = "Nine records were set aside.", "No amounts here."
    assert "figures_listed" not in failed(answer)


# ---- New in milestone 4: the ninth check ----


def test_an_answer_that_names_no_run_or_another_run_fails():
    answer = main_answer()
    answer.run_id = None
    assert failed(answer) == {"run_cited"}
    answer.run_id = "RUN-0001"
    assert failed(answer) == {"run_cited"}


def test_a_change_between_runs_must_equal_what_compare_runs_returned():
    log = change_tool_log()
    assert failed(change_answer(), log) == set()
    answer = change_answer()
    answer.figures[2].value = -30.00  # the model worked out its own difference
    assert "figures_match_tools" in failed(answer, log)


def test_a_declined_answer_need_not_list_the_flags_it_looked_at():
    declined = AnalystAnswer(
        status="declined",
        headline="I can't report profit after marketing spend.",
        narrative="",
        decline_reason="Marketing spend is not in the approved metrics.",
    )
    assert failed(declined) == set()  # the tool log holds flags; the declined answer has none
