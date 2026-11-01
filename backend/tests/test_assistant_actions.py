"""Assistant proposals (US 110) on their own: checked like typed answers, never saved here."""

import pytest

from app.applications.actions import catalog, propose
from app.applications.flow import InvalidAnswer, load_questionnaire
from test_application_flow import ANSWERS, TODAY

SCHENGEN = load_questionnaire("schengen-short-stay")


def test_a_change_is_checked_and_shown_next_to_the_current_answer():
    proposal = propose(SCHENGEN, ANSWERS, "change_answer", {"question_id": "departure_date", "value": "2027-01-20"}, TODAY)
    assert (proposal.action, proposal.value, proposal.current_display) == ("change_answer", "2027-01-20", "2027-01-24")


def test_choices_and_yes_no_accept_labels_and_words():
    assert propose(SCHENGEN, ANSWERS, "change_answer", {"question_id": "purpose", "value": "Business"},
                   TODAY).value == "business"
    assert propose(SCHENGEN, ANSWERS, "change_answer", {"question_id": "previous_fingerprints", "value": "yes"},
                   TODAY).value is True


@pytest.mark.parametrize("args, message", [
    ({"question_id": "departure_date", "value": "2027-01-01"}, "before you arrive"),
    ({"question_id": "purpose", "value": "smuggling"}, "isn't one of the choices"),
    ({"question_id": "home_address", "value": "Paris"}, "several parts"),
    ({"question_id": "host_details", "value": "Someone"}, "isn't one you can go to"),  # hidden: hotel stay
    ({"question_id": "no_such_question", "value": "x"}, "isn't one you can go to"),
])
def test_proposals_that_break_a_rule_are_refused(args, message):
    with pytest.raises(InvalidAnswer, match=message):
        propose(SCHENGEN, ANSWERS, "change_answer", args, TODAY)


def test_the_assistant_cannot_skip_ahead_of_the_current_question():
    early = {key: ANSWERS[key] for key in ("main_destination", "purpose")}
    assert propose(SCHENGEN, early, "go_to_question", {"question_id": "stay_over_90_days"}, TODAY).action == "go_to_question"
    with pytest.raises(InvalidAnswer):
        propose(SCHENGEN, early, "change_answer", {"question_id": "arrival_date", "value": "2027-01-10"}, TODAY)


def test_the_check_runs_straight_away_because_it_changes_nothing():
    proposal = propose(SCHENGEN, {k: v for k, v in ANSWERS.items() if k != "phone"}, "run_completeness_check", {}, TODAY)
    assert proposal.action == "check" and not proposal.report.ready


def test_unknown_tools_are_refused():
    with pytest.raises(InvalidAnswer):
        propose(SCHENGEN, ANSWERS, "submit_application", {"question_id": "purpose"}, TODAY)


def test_the_catalog_lists_ids_types_and_choices_of_reachable_questions():
    text = catalog(SCHENGEN, {key: ANSWERS[key] for key in ("main_destination", "purpose")})
    assert "- purpose (choice, answered) choices: tourism," in text
    assert "- stay_over_90_days (yes_no, current question)" in text
    assert "arrival_date" not in text
