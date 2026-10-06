"""Phase 7 tests for the Jira write. No Jira call is made."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jira import add_comment, choose_transition, set_due_date, transition_issue


def test_choose_transition_matches_the_destination_status():
    transitions = [
        {"id": "11", "name": "Start progress", "to": {"name": "In Progress"}},
        {"id": "31", "name": "Mark done", "to": {"name": "Done"}},
    ]
    assert choose_transition(transitions, "Done") == "31"
    assert choose_transition(transitions, "Blocked") is None


def test_done_posts_the_matching_transition(monkeypatch):
    calls = []

    class Response:
        def json(self):
            return {
                "transitions": [
                    {"id": "31", "name": "Done", "to": {"name": "Done"}},
                ]
            }

        def raise_for_status(self):
            return None

    monkeypatch.setattr("jira.requests.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        "jira.requests.post",
        lambda url, **kwargs: calls.append((url, kwargs.get("json"))) or Response(),
    )
    monkeypatch.setattr("jira._jira_auth", lambda: ("https://example.atlassian.net", None, "KAN"))
    transition_issue("KAN-2", "Done")
    assert calls == [
        (
            "https://example.atlassian.net/rest/api/3/issue/KAN-2/transitions",
            {"transition": {"id": "31"}},
        )
    ]


def test_need_more_time_sets_the_due_date(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "jira.requests.put",
        lambda url, **kwargs: calls.append((url, kwargs.get("json"))) or Response(),
    )
    monkeypatch.setattr("jira._jira_auth", lambda: ("https://example.atlassian.net", None, "KAN"))
    set_due_date("KAN-2", "2026-10-20")
    assert calls == [
        (
            "https://example.atlassian.net/rest/api/3/issue/KAN-2",
            {"fields": {"duedate": "2026-10-20"}},
        )
    ]


def test_blocked_adds_a_comment(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "jira.requests.post",
        lambda url, **kwargs: calls.append(kwargs.get("json")) or Response(),
    )
    monkeypatch.setattr("jira._jira_auth", lambda: ("https://example.atlassian.net", None, "KAN"))
    add_comment("KAN-2", "Marked blocked in Slack.")
    text = calls[0]["body"]["content"][0]["content"][0]["text"]
    assert text == "Marked blocked in Slack."
