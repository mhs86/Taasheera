"""The completeness check (US 13) on its own: no database, a fixed "today"."""

from datetime import date

from app.applications.completeness import check, describe
from app.applications.flow import load_questionnaire
from test_application_flow import ANSWERS, SPECIMEN, TODAY

SCHENGEN = load_questionnaire("schengen-short-stay")


def test_a_full_application_is_ready_with_no_issues():
    report = check(SCHENGEN, ANSWERS, TODAY)
    assert report.ready and report.issues == [] and report.answered == report.total


def test_unanswered_questions_are_blocking_and_say_where_to_fix_them():
    answers = {key: value for key, value in ANSWERS.items() if key not in {"phone", "departure_date"}}
    report = check(SCHENGEN, answers, TODAY)
    assert not report.ready
    assert [(i.kind, i.severity, i.question_id, i.step_id) for i in report.issues] == [
        ("missing", "blocking", "phone", "personal"), ("missing", "blocking", "departure_date", "trip")]


def test_follow_ups_that_dont_apply_are_not_missing():
    # Staying in a hotel: the host's details are never asked, so they can't be missing.
    assert "host_details" not in {i.question_id for i in check(SCHENGEN, ANSWERS, TODAY).issues}


def test_an_answer_that_broke_a_rule_counts_as_missing():
    # On the arrival day the arrival date is no longer in the future, so it must be asked again.
    report = check(SCHENGEN, ANSWERS, date(2027, 1, 10))
    assert ("arrival_date", "missing") in {(i.question_id, i.kind) for i in report.issues}


def test_an_ineligible_answer_blocks_instead_of_listing_everything_after_it():
    report = check(SCHENGEN, {**ANSWERS, "stay_over_90_days": True}, TODAY)
    assert [(i.kind, i.question_id) for i in report.issues] == [("ineligible", "stay_over_90_days")]
    assert not report.ready


def test_a_newer_confirmed_passport_is_a_warning():
    newer = {**SPECIMEN, "document_number": "X1234567", "expiry_date": "2035-01-01"}
    report = check(SCHENGEN, ANSWERS, TODAY, latest_passport=newer)
    assert report.ready
    assert [(i.kind, i.severity, i.question_id) for i in report.issues] == [("inconsistent", "warning", "passport")]
    assert check(SCHENGEN, ANSWERS, TODAY, latest_passport=SPECIMEN).issues == []


def test_passport_and_profile_disagreements_are_warnings_ignoring_case_and_spacing():
    profile = {"surname": "eriksson", "given_names": "Anna  Maria", "birth_date": "1974-08-21", "nationality": None}
    issues = check(SCHENGEN, ANSWERS, TODAY, profile=profile).issues
    assert len(issues) == 1 and "date of birth" in issues[0].message and issues[0].severity == "warning"


def test_the_assistant_gets_a_plain_text_summary():
    assert "nothing is missing" in describe(check(SCHENGEN, ANSWERS, TODAY))
    text = describe(check(SCHENGEN, {k: v for k, v in ANSWERS.items() if k != "phone"}, TODAY))
    assert "not ready" in text and "[blocking] Not answered yet" in text
