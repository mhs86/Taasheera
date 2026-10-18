from datetime import date, timedelta

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, select

from app.applications.router import application_context
from app.auth import access_token
from app.database import build_engine
from app.main import create_app
from app.models import Application, ApplicationAnswer, AuthSession, Traveler
from app.passport.storage import PassportImageStorage
from app.schema import migration_config, schema_revision

# ICAO 9303 specimen passport ("Utopia"). Never use real passport data in tests.
SPECIMEN = {
    "surname": "ERIKSSON", "given_names": "ANNA MARIA", "document_number": "L898902C3", "nationality": "UTO",
    "issuing_country": "UTO", "birth_date": "1974-08-12", "sex": "F",
    "expiry_date": (date.today() + timedelta(days=2000)).isoformat(), "personal_number": "ZE184226B",
}
ARRIVAL = date.today() + timedelta(days=30)
ANSWERS = {
    "main_destination": "FRA", "purpose": "tourism", "stay_over_90_days": False,
    "passport": SPECIMEN, "passport_issue_date": (date.today() - timedelta(days=700)).isoformat(),
    "surname_at_birth": "", "place_of_birth": "Zenith", "country_of_birth": "UTO", "marital_status": "single",
    "home_address": {"line1": "1 Example Street", "city": "Beirut", "country": "LBN"},
    "phone": "+961 71 123 456", "occupation": "retired",
    "arrival_date": ARRIVAL.isoformat(), "departure_date": (ARRIVAL + timedelta(days=10)).isoformat(),
    "entries": "single", "accommodation": "host", "host_details": "Lina Example, 2 Rue Exemple, Paris",
    "funding": "self", "previous_fingerprints": False,
}
START = {"destination": "SCHENGEN", "visa_type": "short_stay"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSPORT_STORAGE_DIR", str(tmp_path / "passports"))
    app = create_app(f"sqlite:///{(tmp_path / 'applications.db').as_posix()}")
    with TestClient(app) as client:
        headers = []
        with Session(app.state.engine) as session:
            for number in (1, 2):
                traveler = Traveler(name=f"Traveler {number}", email=f"traveler{number}@example.com",
                                    password_hash="test-hash")
                session.add(traveler)
                session.flush()
                auth_session = AuthSession(id=f"application-session-{number}", traveler_id=traveler.id,
                                           refresh_hash=f"{number}" * 64, expires_at=2**31)
                session.add(auth_session)
                headers.append({"Authorization": f"Bearer {access_token(auth_session, app.state.auth_settings).access_token}"})
            session.commit()
        yield client, app, headers, PassportImageStorage(tmp_path / "passports")


def start(client, headers):
    response = client.post("/applications", headers=headers, json=START)
    assert response.status_code == 201
    return response.json()


def put(client, headers, application_id, question_id, value):
    return client.put(f"/applications/{application_id}/answers/{question_id}", headers=headers, json={"value": value})


def answer_all(client, headers, application_id, answers=ANSWERS, stop_at=None):
    """Answer whatever the server asks next until it's done, or until it asks `stop_at`."""
    state = client.get(f"/applications/{application_id}", headers=headers).json()
    while state["current"] and state["current"]["id"] != stop_at:
        response = put(client, headers, application_id, state["current"]["id"], answers[state["current"]["id"]])
        assert response.status_code == 200, response.json()
        state = response.json()
    return state


def test_options_list_the_schengen_questionnaire(api):
    client, _, headers, _ = api
    [option] = client.get("/applications/options", headers=headers[0]).json()
    assert option["destination"] == "SCHENGEN" and option["visa_type"] == "short_stay"
    assert option["destination_label"] == "Schengen area" and option["visa_label"] == "Short stay (type C)"
    assert "90 days" in option["visa_description"]


def test_group_size_is_recorded_when_starting(api):
    client, app, headers, _ = api
    state = client.post("/applications", headers=headers[0], json={**START, "group_size": 3}).json()
    assert state["group_size"] == 3
    assert start(client, headers[0])["group_size"] == 1
    for size in (0, 11, "two"):
        assert client.post("/applications", headers=headers[0], json={**START, "group_size": size}).status_code == 422


def test_starting_creates_a_draft_that_asks_the_first_question(api):
    client, app, headers, _ = api
    response = client.post("/applications", headers=headers[0], json=START)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "private, no-store"
    state = response.json()
    assert state["status"] == "DRAFT" and state["answers"] == [] and state["stopped"] is None
    assert state["current"]["id"] == "main_destination" and len(state["current"]["options"]) == 29
    assert state["progress"] == {"step_number": 1, "step_count": 4, "step_title": "Eligibility",
                                 "answered": 0, "total": 18}
    assert [step["title"] for step in state["steps"]] == ["Eligibility", "Passport", "About you", "Your trip"]
    with Session(app.state.engine) as session:
        stored = session.get(Application, state["id"])
        assert stored.traveler_id == 1 and stored.questionnaire_id == "schengen-short-stay"
        assert len(state["id"]) == 32


@pytest.mark.parametrize("body", [
    {"destination": "USA", "visa_type": "tourist"},
    {**START, "traveler_id": 2},
    {"destination": "SCHENGEN"},
])
def test_unknown_visas_and_extra_fields_are_rejected(api, body):
    client, app, headers, _ = api
    assert client.post("/applications", headers=headers[0], json=body).status_code == 422
    with Session(app.state.engine) as session:
        assert session.exec(select(Application)).first() is None


def test_a_full_walk_ends_with_a_complete_application(api):
    client, app, headers, _ = api
    application_id = start(client, headers[0])["id"]
    state = answer_all(client, headers[0], application_id)
    assert state["status"] == "ANSWERS_COMPLETE" and state["current"] is None
    assert [answer["question"]["id"] for answer in state["answers"]] == list(ANSWERS)
    assert {answer["source"] for answer in state["answers"]} == {"traveler"}
    by_id = {answer["question"]["id"]: answer["value"] for answer in state["answers"]}
    assert by_id["phone"] == "+96171123456"
    assert by_id["home_address"] == {"line1": "1 Example Street", "line2": "", "city": "Beirut",
                                     "region": "", "postal_code": "", "country": "LBN"}
    with Session(app.state.engine) as session:
        assert len(session.exec(select(ApplicationAnswer)).all()) == len(ANSWERS)


def test_the_list_names_each_application_by_its_answers(api):
    client, _, headers, _ = api
    first = start(client, headers[0])["id"]
    second = client.post("/applications", headers=headers[0], json={**START, "group_size": 2}).json()["id"]
    answer_all(client, headers[0], first, stop_at="departure_date")
    listed = client.get("/applications", headers=headers[0]).json()
    # Most recently changed first.
    assert [item["id"] for item in listed] == [first, second]
    assert listed[0]["place"] == "France" and listed[0]["trip_date"] == ARRIVAL.isoformat()
    assert listed[0]["destination_label"] == "Schengen area" and listed[0]["status"] == "DRAFT"
    assert listed[0]["answered"] == 13 and listed[0]["total"] == 18
    assert listed[1]["place"] is None and listed[1]["trip_date"] is None and listed[1]["group_size"] == 2
    assert listed[1]["answered"] == 0
    # Timestamps carry their UTC offset even though SQLite stores them without one.
    assert listed[0]["created_at"].endswith(("Z", "+00:00"))


def test_each_answer_is_saved_immediately_and_resumes(api):
    client, _, headers, _ = api
    application_id = start(client, headers[0])["id"]
    assert put(client, headers[0], application_id, "main_destination", "D").status_code == 200
    resumed = client.get(f"/applications/{application_id}", headers=headers[0]).json()
    assert resumed["answers"][0]["value"] == "D" and resumed["current"]["id"] == "purpose"
    assert client.get("/applications", headers=headers[0]).json()[0]["id"] == application_id


def test_invalid_answers_are_rejected_without_saving(api):
    client, app, headers, _ = api
    application_id = start(client, headers[0])["id"]
    response = put(client, headers[0], application_id, "main_destination", "USA")
    assert response.status_code == 422 and response.json() == {"detail": "Choose one of the options."}
    with Session(app.state.engine) as session:
        assert session.exec(select(ApplicationAnswer)).first() is None


def test_date_rules_give_the_picker_its_range(api):
    client, _, headers, _ = api
    application_id = start(client, headers[0])["id"]
    arrival = answer_all(client, headers[0], application_id, stop_at="arrival_date")["current"]
    assert arrival["date_min"] == (date.today() + timedelta(days=1)).isoformat()
    put(client, headers[0], application_id, "arrival_date", ANSWERS["arrival_date"])
    departure = client.get(f"/applications/{application_id}", headers=headers[0]).json()["current"]
    assert departure["id"] == "departure_date"
    assert departure["date_min"] == ARRIVAL.isoformat()
    assert departure["date_max"] == (ARRIVAL + timedelta(days=89)).isoformat()


def test_questions_must_be_answered_in_order(api):
    client, _, headers, _ = api
    application_id = start(client, headers[0])["id"]
    skipped = put(client, headers[0], application_id, "arrival_date", ARRIVAL.isoformat())
    assert skipped.status_code == 409
    assert put(client, headers[0], application_id, "no_such_question", "x").status_code == 404


def test_hidden_follow_ups_cannot_be_answered(api):
    client, _, headers, _ = api
    application_id = start(client, headers[0])["id"]
    answer_all(client, headers[0], application_id)
    # Retired, so "employer" isn't part of this application.
    assert put(client, headers[0], application_id, "employer", "Example Company").status_code == 409


def test_a_long_stay_marks_the_application_ineligible_until_changed(api):
    client, _, headers, _ = api
    application_id = start(client, headers[0])["id"]
    put(client, headers[0], application_id, "main_destination", "FRA")
    put(client, headers[0], application_id, "purpose", "tourism")
    stopped = put(client, headers[0], application_id, "stay_over_90_days", True).json()
    assert stopped["status"] == "INELIGIBLE" and stopped["current"] is None and "90 days" in stopped["stopped"]
    # The gate holds on the server: the next question can't be answered while stopped.
    assert client.put(f"/applications/{application_id}/answers/passport", headers=headers[0],
                      json={"value": SPECIMEN}).status_code == 409
    resumed = put(client, headers[0], application_id, "stay_over_90_days", False).json()
    assert resumed["status"] == "DRAFT" and resumed["current"]["id"] == "passport"


def test_changing_an_earlier_answer_clears_follow_ups_that_no_longer_apply(api):
    client, app, headers, _ = api
    application_id = start(client, headers[0])["id"]
    answer_all(client, headers[0], application_id)
    changed = put(client, headers[0], application_id, "accommodation", "hotel").json()
    assert changed["cleared"] == ["host_details"]
    assert changed["status"] == "DRAFT" and changed["current"]["id"] == "accommodation_details"
    with Session(app.state.engine) as session:
        assert session.get(ApplicationAnswer, (application_id, "host_details")) is None


def test_a_confirmed_passport_upload_answers_the_passport_question(api):
    client, _, headers, storage = api
    application_id = start(client, headers[0])["id"]
    for question in ["main_destination", "purpose", "stay_over_90_days"]:
        put(client, headers[0], application_id, question, ANSWERS[question])
    upload_id = storage.save(1, b"jpeg")
    path = f"/applications/{application_id}/answers/passport"
    # Uploaded but not yet confirmed: an OCR guess never becomes an answer.
    assert client.put(path, headers=headers[0], json={"passport_upload_id": upload_id}).status_code == 404
    storage.save_review(1, upload_id, SPECIMEN)
    other_upload = storage.save(2, b"jpeg")
    storage.save_review(2, other_upload, SPECIMEN)
    assert client.put(path, headers=headers[0], json={"passport_upload_id": other_upload}).status_code == 404
    response = client.put(path, headers=headers[0], json={"passport_upload_id": upload_id})
    assert response.status_code == 200
    answer = response.json()["answers"][-1]
    assert answer["source"] == "passport_upload" and answer["value"] == SPECIMEN
    # Editing the stored review later doesn't change the application's copy.
    storage.save_review(1, upload_id, {**SPECIMEN, "surname": "CHANGED"})
    resumed = client.get(f"/applications/{application_id}", headers=headers[0]).json()
    assert resumed["answers"][-1]["value"]["surname"] == "ERIKSSON"


@pytest.mark.parametrize("body", [
    {"value": SPECIMEN, "passport_upload_id": "a" * 32},
    {},
    {"passport_upload_id": "../../etc"},
    {"value": "x", "source": "passport_upload"},
])
def test_answer_bodies_are_strict(api, body):
    client, _, headers, _ = api
    application_id = start(client, headers[0])["id"]
    response = client.put(f"/applications/{application_id}/answers/main_destination", headers=headers[0], json=body)
    assert response.status_code == 422


def test_a_passport_upload_only_answers_the_passport_question(api):
    client, _, headers, storage = api
    application_id = start(client, headers[0])["id"]
    upload_id = storage.save(1, b"jpeg")
    storage.save_review(1, upload_id, SPECIMEN)
    response = client.put(f"/applications/{application_id}/answers/main_destination", headers=headers[0],
                          json={"passport_upload_id": upload_id})
    assert response.status_code == 422


def test_travelers_only_see_and_change_their_own_applications(api):
    client, app, headers, _ = api
    application_id = start(client, headers[0])["id"]
    assert client.get(f"/applications/{application_id}", headers=headers[1]).status_code == 404
    assert put(client, headers[1], application_id, "main_destination", "FRA").status_code == 404
    assert client.get("/applications", headers=headers[1]).json() == []
    with Session(app.state.engine) as session:
        assert session.exec(select(ApplicationAnswer)).first() is None


def test_unauthenticated_and_cross_site_requests_are_rejected(api):
    client, _, headers, _ = api
    assert client.get("/applications").status_code == 401
    assert client.post("/applications", json=START).status_code == 401
    assert client.post("/applications", json=START,
                       headers={**headers[0], "Origin": "https://evil.invalid"}).status_code == 403
    application_id = start(client, headers[0])["id"]
    assert client.put(f"/applications/{application_id}/answers/main_destination", json={"value": "FRA"},
                      headers={**headers[0], "Origin": "https://evil.invalid"}).status_code == 403


def test_the_assistant_context_is_owner_scoped_and_lists_answers(api):
    client, app, headers, _ = api
    application_id = start(client, headers[0])["id"]
    answer_all(client, headers[0], application_id, stop_at="arrival_date")
    with Session(app.state.engine) as session:
        assert application_context(session, 2, application_id) is None
        context = application_context(session, 1, application_id)
    assert context.startswith("Visa: Schengen short-stay visa (type C)\nTravelling: alone\n")
    assert "Current question: When do you plan to arrive in the Schengen area?" in context
    assert "- Which Schengen country is your main destination? France" in context
    assert "- Will you stay in the Schengen area for more than 90 days in any 180-day period? No" in context
    assert "line1: 1 Example Street, city: Beirut, country: LBN" in context


def test_group_size_migration_counts_existing_applications_as_one_traveler(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'before-group-size.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(migration_config(), "1f04330ae8cb")
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO traveler (id,name,email,password_hash,auth_type) "
                                "VALUES (1,'Existing','existing@example.com','hash','email_password')"))
        connection.execute(text(
            "INSERT INTO application (id,traveler_id,questionnaire_id,questionnaire_version,destination,visa_type,"
            "status,created_at,updated_at) VALUES ('" + "c" * 32 + "',1,'schengen-short-stay',1,'SCHENGEN',"
            "'short_stay','DRAFT','2026-10-18 10:00:00','2026-10-18 10:00:00')"))
    command.upgrade(migration_config(), "head")
    with Session(engine) as session:
        assert session.get(Application, "c" * 32).group_size == 1
    engine.dispose()


def test_migration_upgrades_from_previous_head(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'previous-head.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(migration_config(), "e6f81a73c902")
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO traveler (id,name,email,password_hash,auth_type) "
                                "VALUES (1,'Existing','existing@example.com','hash','email_password')"))
    command.upgrade(migration_config(), "head")
    with Session(engine) as session:
        session.add(Application(id="b" * 32, traveler_id=1, questionnaire_id="schengen-short-stay",
                                questionnaire_version=1, destination="SCHENGEN", visa_type="short_stay"))
        session.add(ApplicationAnswer(application_id="b" * 32, question_id="home_address",
                                      value={"line1": "1 Example Street"}, source="traveler"))
        session.commit()
        assert session.get(ApplicationAnswer, ("b" * 32, "home_address")).value == {"line1": "1 Example Street"}
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), SQLModel.metadata) == []
    assert schema_revision(engine)[0] == schema_revision(engine)[1]
    command.downgrade(migration_config(), "e6f81a73c902")
    engine.dispose()
