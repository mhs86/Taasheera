"""Regressions at the boundary between the independently developed Sprint 3 features."""

import pytest
from sqlmodel import Session, select

from app.applications.flow import InvalidAnswer
from app.applications.router import application_context, application_proposal
from app.chat_history import load_history, save_turn
from app.models import AssistantMessage, Traveler
from test_monitoring_privacy import api, deletion_data  # noqa: F401 (parametrized SQLite/PostgreSQL fixture)


def start(api, owner="one"):
    response = api.client.post("/applications", headers=api.headers(owner), json={
        "destination": "SCHENGEN", "visa_type": "short_stay"})
    assert response.status_code == 201
    return response.json()["id"]


def test_account_erasure_removes_general_and_application_conversations(api):  # noqa: F811
    doomed, kept = start(api), start(api, "two")
    owner, other = api.ids["one"], api.ids["two"]
    with Session(api.app.state.engine) as session:
        for traveler, application_id in ((owner, None), (owner, doomed), (other, None), (other, kept)):
            save_turn(session, traveler, application_id, "Synthetic question", "Synthetic reply")
    response = api.client.request("DELETE", "/auth/account", headers=api.headers("one"), json=deletion_data(api))
    assert response.status_code == 204
    with Session(api.app.state.engine) as session:
        assert session.get(Traveler, owner) is None
        assert session.exec(select(AssistantMessage).where(AssistantMessage.traveler_id == owner)).all() == []
        assert len(load_history(session, other, None)) == 2
        assert len(load_history(session, other, kept)) == 2


def test_application_deletion_removes_only_its_conversation_with_foreign_keys_enforced(api):  # noqa: F811
    doomed, kept, other_app = start(api), start(api), start(api, "two")
    owner, other = api.ids["one"], api.ids["two"]
    with Session(api.app.state.engine) as session:
        for traveler, application_id in ((owner, None), (owner, doomed), (owner, kept), (other, other_app)):
            save_turn(session, traveler, application_id, "Synthetic question", "Synthetic reply")
    assert api.client.delete(f"/applications/{doomed}", headers=api.headers("two")).status_code == 404
    response = api.client.delete(f"/applications/{doomed}", headers=api.headers("one"))
    assert response.status_code == 204
    with Session(api.app.state.engine) as session:
        assert session.exec(select(AssistantMessage).where(AssistantMessage.application_id == doomed)).all() == []
        assert len(load_history(session, owner, None)) == 2
        assert len(load_history(session, owner, kept)) == 2
        assert len(load_history(session, other, other_app)) == 2
        # A late model reply must not recreate the deleted conversation.
        save_turn(session, owner, doomed, "Late question", "Late reply")
        assert load_history(session, owner, doomed) == []


def test_archived_application_context_explains_read_only_state_and_refuses_change_proposals(api):  # noqa: F811
    application_id = start(api)
    assert api.client.put(f"/applications/{application_id}/answers/main_destination",
                          headers=api.headers("one"), json={"value": "FRA"}).status_code == 200
    assert api.client.post(f"/applications/{application_id}/archive", headers=api.headers("one")).status_code == 200
    with Session(api.app.state.engine) as session:
        context = application_context(session, api.ids["one"], application_id)
        assert "archived" in context.lower() and "restore" in context.lower()
        with pytest.raises(InvalidAnswer, match="archived"):
            application_proposal(session, api.ids["one"], application_id, "change_answer",
                                 {"question_id": "main_destination", "value": "D"})
        report = application_proposal(session, api.ids["one"], application_id, "run_completeness_check", {})
        assert report.action == "check" and not report.report.ready
    assert api.client.post(f"/applications/{application_id}/unarchive", headers=api.headers("one")).status_code == 200
    with Session(api.app.state.engine) as session:
        proposal = application_proposal(session, api.ids["one"], application_id, "change_answer",
                                        {"question_id": "main_destination", "value": "D"})
        assert proposal.action == "change_answer"
