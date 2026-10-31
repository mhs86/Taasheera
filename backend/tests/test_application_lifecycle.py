"""Archive, delete and the timeline of an application (US 79, US 20)."""

from alembic import command
from sqlalchemy import text
from sqlmodel import Session, select

from app.database import build_engine
from app.models import Application, ApplicationAnswer
from app.schema import migration_config
from test_applications_api import ANSWERS, answer_all, api, put, start  # noqa: F401 (api is a fixture)


def listed(client, headers, **params):
    response = client.get("/applications", headers=headers, params=params)
    assert response.status_code == 200
    return [application["id"] for application in response.json()]


def test_archive_hides_an_application_until_it_is_restored(api):
    client, _, headers, _ = api
    kept, archived = start(client, headers[0]), start(client, headers[0])
    before = client.get(f"/applications/{archived['id']}", headers=headers[0]).json()

    response = client.post(f"/applications/{archived['id']}/archive", headers=headers[0])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["archived_at"] is not None
    # Archiving isn't a change to the answers, so "last updated" and the status stay as they were.
    assert response.json()["updated_at"] == before["updated_at"]
    assert response.json()["status"] == before["status"]
    assert listed(client, headers[0]) == [kept["id"]]
    assert listed(client, headers[0], archived="true") == [archived["id"]]
    # Still readable, so a bookmarked link doesn't break.
    assert client.get(f"/applications/{archived['id']}", headers=headers[0]).json()["archived_at"] is not None

    assert client.post(f"/applications/{archived['id']}/archive", headers=headers[0]).status_code == 200
    response = client.post(f"/applications/{archived['id']}/unarchive", headers=headers[0])
    assert response.status_code == 200
    assert response.json()["archived_at"] is None
    assert set(listed(client, headers[0])) == {kept["id"], archived["id"]}
    assert listed(client, headers[0], archived="true") == []


def test_delete_removes_the_application_and_its_answers_only(api):
    client, app, headers, _ = api
    doomed, kept = start(client, headers[0]), start(client, headers[0])
    other = start(client, headers[1])
    for application_id, owner in ((doomed["id"], headers[0]), (kept["id"], headers[0]), (other["id"], headers[1])):
        answer_all(client, owner, application_id, stop_at="passport")

    response = client.delete(f"/applications/{doomed['id']}", headers=headers[0])
    assert response.status_code == 204
    assert response.content == b""
    with Session(app.state.engine) as session:
        assert session.get(Application, doomed["id"]) is None
        assert session.exec(select(ApplicationAnswer)
                            .where(ApplicationAnswer.application_id == doomed["id"])).all() == []
        for survivor in (kept["id"], other["id"]):
            assert session.exec(select(ApplicationAnswer)
                                .where(ApplicationAnswer.application_id == survivor)).all() != []
    assert listed(client, headers[0]) == [kept["id"]]
    assert client.get(f"/applications/{doomed['id']}", headers=headers[0]).status_code == 404
    assert client.delete(f"/applications/{doomed['id']}", headers=headers[0]).status_code == 404


def test_another_travelers_application_cannot_be_archived_deleted_or_read(api):
    client, app, headers, _ = api
    application = start(client, headers[0])
    put(client, headers[0], application["id"], "main_destination", "FRA")
    for method, path in (("post", "archive"), ("post", "unarchive"), ("get", "timeline")):
        response = getattr(client, method)(f"/applications/{application['id']}/{path}", headers=headers[1])
        assert response.status_code == 404
    assert client.delete(f"/applications/{application['id']}", headers=headers[1]).status_code == 404
    assert client.post(f"/applications/{'0' * 32}/archive", headers=headers[0]).status_code == 404
    with Session(app.state.engine) as session:
        stored = session.get(Application, application["id"])
        assert stored is not None and stored.archived_at is None


def test_lifecycle_needs_sign_in_and_the_sites_own_origin(api):
    client, _, headers, _ = api
    application = start(client, headers[0])
    assert client.post(f"/applications/{application['id']}/archive").status_code == 401
    assert client.get(f"/applications/{application['id']}/timeline").status_code == 401
    assert client.delete(f"/applications/{application['id']}").status_code == 401
    foreign = {**headers[0], "Origin": "https://attacker.example"}
    assert client.post(f"/applications/{application['id']}/archive", headers=foreign).status_code == 403
    assert client.delete(f"/applications/{application['id']}", headers=foreign).status_code == 403
    assert listed(client, headers[0]) == [application["id"]]


def test_timeline_of_a_draft_lists_answers_in_order_and_the_next_question(api):
    client, _, headers, _ = api
    application = start(client, headers[0])
    state = answer_all(client, headers[0], application["id"], stop_at="passport")

    response = client.get(f"/applications/{application['id']}/timeline", headers=headers[0])
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    timeline = response.json()
    kinds = [event["kind"] for event in timeline["events"]]
    assert kinds[0] == "started"
    answered = [event for event in timeline["events"] if event["kind"] == "answered"]
    assert [event["question_id"] for event in answered] == [answer["question"]["id"] for answer in state["answers"]]
    assert all(event["step_title"] for event in answered)
    assert [event["at"] for event in timeline["events"]] == sorted(event["at"] for event in timeline["events"])
    assert timeline["next"]["kind"] == "answer"
    assert state["current"]["prompt"] in timeline["next"]["text"]
    # No answers or passport values in the timeline, only the questions.
    assert "FRA" not in response.text and "France" not in response.text


def test_timeline_of_a_complete_stopped_and_archived_application(api):
    client, _, headers, _ = api
    complete = start(client, headers[0])
    answer_all(client, headers[0], complete["id"])
    timeline = client.get(f"/applications/{complete['id']}/timeline", headers=headers[0]).json()
    assert timeline["events"][-1]["kind"] == "complete"
    assert timeline["next"]["kind"] == "complete"
    assert "nothing is submitted without your confirmation" in timeline["next"]["text"]

    client.post(f"/applications/{complete['id']}/archive", headers=headers[0])
    timeline = client.get(f"/applications/{complete['id']}/timeline", headers=headers[0]).json()
    assert timeline["events"][-1]["kind"] == "archived"
    assert timeline["archived_at"] is not None
    assert timeline["next"]["kind"] == "archived"

    stopped = start(client, headers[0])
    put(client, headers[0], stopped["id"], "main_destination", "FRA")
    put(client, headers[0], stopped["id"], "purpose", "tourism")
    assert put(client, headers[0], stopped["id"], "stay_over_90_days", True).json()["status"] == "INELIGIBLE"
    timeline = client.get(f"/applications/{stopped['id']}/timeline", headers=headers[0]).json()
    assert timeline["events"][-1]["kind"] == "stopped"
    assert "90 days" in timeline["events"][-1]["text"]
    assert timeline["next"]["kind"] == "change"
    # The reason is said once, in the timeline, not repeated as the next step.
    assert "90 days" not in timeline["next"]["text"]


def test_an_archived_application_is_read_only_until_restored(api):
    client, app, headers, _ = api
    application = start(client, headers[0])
    put(client, headers[0], application["id"], "main_destination", "FRA")
    archived = client.post(f"/applications/{application['id']}/archive", headers=headers[0]).json()

    response = put(client, headers[0], application["id"], "purpose", "tourism")
    assert response.status_code == 409
    assert "archived" in response.json()["detail"]
    # Reading it, even when an answer no longer applies, stores nothing.
    with Session(app.state.engine) as session:
        session.delete(session.get(ApplicationAnswer, (application["id"], "main_destination")))
        session.add(ApplicationAnswer(application_id=application["id"], question_id="arrival_date",
                                      value="2000-01-01", source="traveler"))
        session.commit()
    state = client.get(f"/applications/{application['id']}", headers=headers[0]).json()
    assert state["updated_at"] == archived["updated_at"]
    with Session(app.state.engine) as session:
        assert session.get(ApplicationAnswer, (application["id"], "arrival_date")) is not None

    client.post(f"/applications/{application['id']}/unarchive", headers=headers[0])
    assert put(client, headers[0], application["id"], "main_destination", "FRA").status_code == 200


def test_request_logs_name_the_full_route_template(api, caplog):
    client, _, headers, _ = api
    application = start(client, headers[0])
    with caplog.at_level("INFO"):
        client.get(f"/applications/{application['id']}/timeline", headers=headers[0])
    routes = [record.activity["route"] for record in caplog.records if hasattr(record, "activity")]
    assert "/applications/{application_id}/timeline" in routes


def test_archived_at_migration_keeps_existing_applications_active(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'before-archive.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(migration_config(), "e9776504c5f8")
    engine = build_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO traveler (id,name,email,password_hash,auth_type) "
                                "VALUES (1,'Existing','existing@example.com','hash','email_password')"))
        connection.execute(text(
            "INSERT INTO application (id,traveler_id,questionnaire_id,questionnaire_version,destination,visa_type,"
            "group_size,status,created_at,updated_at) VALUES ('" + "d" * 32 + "',1,'schengen-short-stay',1,"
            "'SCHENGEN','short_stay',1,'DRAFT','2026-10-18 10:00:00','2026-10-18 10:00:00')"))
    command.upgrade(migration_config(), "head")
    with Session(engine) as session:
        assert session.get(Application, "d" * 32).archived_at is None
    command.downgrade(migration_config(), "e9776504c5f8")
    engine.dispose()
