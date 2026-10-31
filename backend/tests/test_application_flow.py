"""The flow engine on its own: no database or HTTP, and a fixed "today"."""

from datetime import date
import json

import pytest
from pydantic import ValidationError

from app.applications.flow import (
    QUESTIONNAIRE_DIR, InvalidAnswer, Questionnaire, add_months, available_questionnaires, check_answer, date_bounds,
    load_questionnaire, next_question, prefill_value, progress, reconcile, stop_message, summary_place,
    visible_questions,
)

TODAY = date(2026, 10, 18)
# ICAO 9303 specimen passport ("Utopia"). Never use real passport data in tests.
SPECIMEN = {
    "surname": "ERIKSSON", "given_names": "ANNA MARIA", "document_number": "L898902C3", "nationality": "UTO",
    "issuing_country": "UTO", "birth_date": "1974-08-12", "sex": "F", "expiry_date": "2030-04-15",
    "personal_number": "ZE184226B",
}
ANSWERS = {
    "main_destination": "FRA", "purpose": "tourism", "stay_over_90_days": False,
    "passport": SPECIMEN, "passport_issue_date": "2020-04-16",
    "surname_at_birth": "", "place_of_birth": "Zenith", "country_of_birth": "UTO", "marital_status": "single",
    "home_address": {"line1": "1 Example Street", "line2": "", "city": "Beirut", "region": "",
                     "postal_code": "", "country": "LBN"},
    "phone": "+96171123456", "occupation": "employed", "employer": "Example Company",
    "arrival_date": "2027-01-10", "departure_date": "2027-01-24", "entries": "single",
    "accommodation": "hotel", "accommodation_details": "Hotel Example, 1 Rue Exemple, Paris",
    "funding": "self", "previous_fingerprints": False,
}


@pytest.fixture
def schengen():
    return load_questionnaire("schengen-short-stay")


def answer_all(questionnaire, answers):
    """Answer whatever the engine asks next, the way the chat does, until it stops asking."""
    given = {}
    while (question := next_question(questionnaire, given)) is not None:
        given[question.id] = check_answer(question, answers[question.id], given, TODAY)
    return given


@pytest.mark.parametrize("questionnaire", available_questionnaires(), ids=lambda q: q.id)
def test_every_shipped_questionnaire_loads(questionnaire):
    assert questionnaire.steps and next_question(questionnaire, {}) is not None


def test_a_complete_walk_asks_each_question_once_in_file_order(schengen):
    given = answer_all(schengen, ANSWERS)
    assert list(given) == list(ANSWERS)
    assert next_question(schengen, given) is None and stop_message(schengen, given) is None
    assert progress(schengen, given).model_dump() == {
        "step_number": 4, "step_count": 4, "step_title": "Your trip", "answered": 20, "total": 20}


def test_progress_reports_the_current_step(schengen):
    given = answer_all(schengen, {**ANSWERS})
    partial = {key: given[key] for key in ["main_destination", "purpose", "stay_over_90_days"]}
    assert next_question(schengen, partial).id == "passport"
    assert progress(schengen, partial).model_dump() == {
        "step_number": 2, "step_count": 4, "step_title": "Passport", "answered": 3, "total": 18}


@pytest.mark.parametrize("occupation, asked, skipped", [
    ("employed", "employer", "school"),
    ("self_employed", "employer", "school"),
    ("student", "school", "employer"),
])
def test_occupation_branches(schengen, occupation, asked, skipped):
    answers = {**ANSWERS, "occupation": occupation, "school": "Example University"}
    given = answer_all(schengen, answers)
    assert asked in given and skipped not in given


def test_retired_traveler_skips_both_follow_ups(schengen):
    given = answer_all(schengen, {**ANSWERS, "occupation": "retired"})
    assert "employer" not in given and "school" not in given


@pytest.mark.parametrize("accommodation, asked, skipped", [
    ("hotel", "accommodation_details", "host_details"),
    ("rental", "accommodation_details", "host_details"),
    ("other", "accommodation_details", "host_details"),
    ("host", "host_details", "accommodation_details"),
])
def test_accommodation_branches(schengen, accommodation, asked, skipped):
    answers = {**ANSWERS, "accommodation": accommodation, "host_details": "Lina Example, 2 Rue Exemple, Paris"}
    given = answer_all(schengen, answers)
    assert asked in given and skipped not in given


def test_sponsor_and_fingerprint_follow_ups(schengen):
    given = answer_all(schengen, {**ANSWERS, "funding": "sponsor", "sponsor_details": "My aunt, Lina Example",
                                  "previous_fingerprints": True, "fingerprints_date": "2024-05-01"})
    assert given["sponsor_details"] == "My aunt, Lina Example" and given["fingerprints_date"] == "2024-05-01"
    assert next_question(schengen, given) is None


def test_long_stay_answer_stops_the_flow_until_it_changes(schengen):
    given = {"main_destination": "FRA", "purpose": "tourism", "stay_over_90_days": True}
    assert next_question(schengen, given) is None
    assert "90 days" in stop_message(schengen, given)
    given["stay_over_90_days"] = False
    assert stop_message(schengen, given) is None and next_question(schengen, given).id == "passport"


@pytest.mark.parametrize("question_id, raw, message", [
    ("main_destination", "USA", "Choose one of the options."),
    ("main_destination", None, "Choose one of the options."),
    ("stay_over_90_days", "no", "Answer yes or no."),
    ("place_of_birth", "   ", "This question needs an answer."),
    ("place_of_birth", "x" * 101, "Keep it under 100 characters."),
    ("place_of_birth", 7, "Type your answer."),
    ("country_of_birth", "lbn", "Choose a country."),
    ("phone", "71123456", "Phone must be an international E.164 number."),
    ("phone", "+999123456789", "Phone must be a valid international number."),
    ("phone", "", "This question needs an answer."),
    ("home_address", {"line1": "1 Example Street", "country": "LBN"}, "City is required."),
    ("home_address", {**ANSWERS["home_address"], "country": "lb"}, "Country: String should match pattern '^[A-Z]{1,3}$'"),
    ("home_address", {**ANSWERS["home_address"], "floor": "2"}, "This answer has a field we don't recognise."),
    ("passport", {**SPECIMEN, "surname": ""}, "Surname is required."),
    ("passport", {**SPECIMEN, "expiry_date": None}, "Your passport's date of birth and expiry date are both needed."),
    ("passport", {**SPECIMEN, "expiry_date": "2026-10-18"}, "This passport has expired. You'll need to renew it before applying."),
    ("passport_issue_date", "2026-10-19", "The issue date can't be in the future."),
    ("passport_issue_date", "2016-10-17", "Schengen countries need a passport issued in the last 10 years. You may need to renew it first."),
    ("arrival_date", "2026-10-18", "Your arrival date needs to be in the future."),
    ("arrival_date", "2027-04-19", "You can apply at most six months before your trip. Come back closer to the date."),
    ("arrival_date", "2027-02-30", "Choose a real date."),
    ("arrival_date", "10/01/2027", "Choose a date."),
    ("departure_date", "2027-01-09", "You can't leave before you arrive."),
    ("departure_date", "2027-04-10", "A short-stay visa covers at most 90 days, counting the days you arrive and leave."),
    ("fingerprints_date", "2021-11-17", "Only fingerprints from the last 59 months count. Answer no to the previous question instead."),
])
def test_invalid_answers_are_rejected_with_a_message(schengen, question_id, raw, message):
    with pytest.raises(InvalidAnswer) as error:
        check_answer(schengen.question(question_id), raw, ANSWERS, TODAY)
    assert str(error.value) == message


def test_departure_must_leave_three_months_of_passport_validity(schengen):
    answers = {**ANSWERS, "arrival_date": "2026-12-20", "passport": {**SPECIMEN, "expiry_date": "2027-04-01"}}
    question = schengen.question("departure_date")
    assert check_answer(question, "2027-01-01", answers, TODAY) == "2027-01-01"
    with pytest.raises(InvalidAnswer, match="three months"):
        check_answer(question, "2027-01-02", answers, TODAY)


def test_boundary_dates_are_allowed(schengen):
    assert check_answer(schengen.question("arrival_date"), "2026-10-19", ANSWERS, TODAY) == "2026-10-19"
    assert check_answer(schengen.question("arrival_date"), "2027-04-18", ANSWERS, TODAY) == "2027-04-18"
    # 10 Jan + 89 days = 9 Apr: arriving and leaving days both count, 90 in all.
    assert check_answer(schengen.question("departure_date"), "2027-04-09", ANSWERS, TODAY) == "2027-04-09"
    assert check_answer(schengen.question("passport_issue_date"), "2016-10-18", ANSWERS, TODAY) == "2016-10-18"


def test_answers_are_normalized_before_saving(schengen):
    assert check_answer(schengen.question("phone"), "+961 71 123 456", ANSWERS, TODAY) == "+96171123456"
    assert check_answer(schengen.question("place_of_birth"), "  New   York ", ANSWERS, TODAY) == "New York"
    assert check_answer(schengen.question("surname_at_birth"), "", ANSWERS, TODAY) == ""
    address = check_answer(schengen.question("home_address"),
                           {"line1": "1 Example Street", "city": "Beirut", "country": "LBN"}, ANSWERS, TODAY)
    assert address == ANSWERS["home_address"]


def test_date_bounds_follow_the_rules_and_earlier_answers(schengen):
    assert date_bounds(schengen.question("arrival_date"), {}, TODAY) == (date(2026, 10, 19), date(2027, 4, 18))
    assert date_bounds(schengen.question("departure_date"), ANSWERS, TODAY) == (date(2027, 1, 10), date(2027, 4, 9))
    # Without an arrival date or passport there's nothing to bound the departure by yet.
    assert date_bounds(schengen.question("departure_date"), {}, TODAY) == (None, None)


def test_changing_an_answer_drops_follow_ups_that_no_longer_apply(schengen):
    given = answer_all(schengen, {**ANSWERS, "accommodation": "host", "host_details": "Lina Example, Paris"})
    kept, dropped = reconcile(schengen, {**given, "accommodation": "hotel"}, TODAY)
    assert dropped == ["host_details"]
    assert next_question(schengen, kept).id == "accommodation_details"


def test_moving_the_arrival_date_drops_a_departure_date_that_no_longer_fits(schengen):
    given = answer_all(schengen, ANSWERS)
    kept, dropped = reconcile(schengen, {**given, "arrival_date": "2027-02-01"}, TODAY)
    assert dropped == ["departure_date"]
    assert next_question(schengen, kept).id == "departure_date"
    unchanged, nothing = reconcile(schengen, given, TODAY)
    assert unchanged == given and nothing == []


def test_add_months_clamps_to_the_end_of_the_month():
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 10, 18), -120) == date(2016, 10, 18)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


def _file(**changes):
    base = json.loads((QUESTIONNAIRE_DIR / "schengen-short-stay.json").read_text())
    trip = base["steps"][3]["questions"]
    for key, value in changes.items():
        if key == "trip":
            trip[:] = value(trip)
        else:
            base[key] = value
    return base


@pytest.mark.parametrize("broken, message", [
    (lambda q: q + [dict(q[0])], "used twice"),
    (lambda q: [{**q[0], "show_if": {"question": "departure_date", "in": ["x"]}}] + q[1:], "earlier question"),
    (lambda q: [{**q[0], "type": "choice"}] + q[1:], "need options"),
    (lambda q: q + [{"id": "extra", "type": "text", "prompt": "?", "options": [{"value": "a", "label": "A"}]}], "need options"),
    (lambda q: q + [{"id": "extra", "type": "text", "prompt": "?", "rules": [{"op": "<=", "ref": "today", "message": "m"}]}], "only date questions"),
    (lambda q: q + [{"id": "extra", "type": "text", "prompt": "?", "show_if": {"question": "funding", "in": ["friend"]}}], "can't have"),
    (lambda q: q + [{"id": "extra", "type": "date", "prompt": "?", "rules": [{"op": "<=", "ref": "later_date", "message": "m"}]}], "isn't an earlier question"),
    (lambda q: q + [{"id": "extra", "type": "text", "prompt": "?", "show_iff": {"question": "funding", "in": ["self"]}}], "Extra inputs"),
    (lambda q: q + [{"id": "extra", "type": "text", "prompt": "?", "prefill": "profile.phone"}], "doesn't give a text answer"),
    (lambda q: q + [{"id": "extra", "type": "phone", "prompt": "?", "prefill": "profile.fax"}], "doesn't give a phone answer"),
])
def test_broken_questionnaire_files_are_rejected_when_loaded(broken, message):
    with pytest.raises(ValidationError, match=message):
        Questionnaire.model_validate(_file(trip=broken))


def test_prefill_maps_saved_details_onto_the_question(schengen):
    profile = {"phone": "+96171123456", "address_line1": "1 Example Street", "address_city": "Beirut",
               "address_country": "LBN", "address_region": None}
    assert prefill_value(schengen.question("phone"), None, profile) == ("+96171123456", "profile")
    assert prefill_value(schengen.question("home_address"), None, profile) == (
        {"line1": "1 Example Street", "line2": "", "city": "Beirut", "region": "", "postal_code": "",
         "country": "LBN"}, "profile")
    assert prefill_value(schengen.question("passport"), SPECIMEN, None) == (SPECIMEN, "passport")
    assert prefill_value(schengen.question("passport"), None, profile) is None
    assert prefill_value(schengen.question("home_address"), None, {"phone": "+96171123456"}) is None
    assert prefill_value(schengen.question("place_of_birth"), SPECIMEN, profile) is None


@pytest.mark.parametrize("summary, message", [
    ({"place": "place_of_birth"}, "summary refers to 'place_of_birth'"),
    ({"date": "main_destination"}, "summary refers to 'main_destination'"),
    ({"place": "nowhere"}, "summary refers to 'nowhere'"),
])
def test_summary_must_name_a_fitting_question(summary, message):
    with pytest.raises(ValidationError, match=message):
        Questionnaire.model_validate(_file(summary=summary))


def test_summary_place_reads_the_choice_label(schengen):
    assert summary_place(schengen, {"main_destination": "D"}) == "Germany"
    assert summary_place(schengen, {}) is None


def test_visible_questions_hide_unmet_conditions(schengen):
    ids = [question.id for question in visible_questions(schengen, {"occupation": "student"})]
    assert "school" in ids and "employer" not in ids and "host_details" not in ids
