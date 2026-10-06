"""Phase 5 tests. The model is fake, so these do not call a real LLM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent import build_graph, friendly_nudge, parse_blocker, read_blocker
from jira import Task
from text import comments_to_text


def make_task(comments: str = "", due_date: str = "2026-10-01", status: str = "To Do") -> Task:
    return Task(
        key="KAN-2",
        title="Write test plan",
        assignee="Dinesh",
        status=status,
        due_date=due_date,
        last_updated="2026-10-06",
        comments=comments,
    )


def test_jira_comment_json_becomes_plain_text():
    payload = {
        "comments": [
            {
                "body": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Blocked: waiting for the design file"}],
                        }
                    ],
                }
            }
        ]
    }
    assert comments_to_text(payload) == "Blocked: waiting for the design file"


def test_parse_blocker_accepts_json_inside_markdown():
    raw = '```json\n{"blocked": true, "reason": "Waiting for the design file"}\n```'
    assert parse_blocker(raw) == (True, "Waiting for the design file")


def test_empty_comments_skip_the_model():
    calls = []
    result = read_blocker(make_task(""), lambda prompt: calls.append(prompt) or "{}")
    assert result["blocked"] is False
    assert calls == []


def test_friendly_nudge_falls_back_when_a_key_is_missing():
    task = make_task()
    text = friendly_nudge([task], __import__("datetime").date(2026, 10, 6), lambda prompt: "Hello")
    assert "KAN-2" in text


def test_graph_uses_python_for_dates_and_the_model_for_comments(monkeypatch):
    task = make_task("Blocked: waiting for the design file")
    monkeypatch.setattr("agent.fetch_tasks_with_comments", lambda: [task])
    seen = {}

    def fake_post(groups, today=None, blockers=None):
        seen["overdue"] = [item.key for item in groups["overdue"]]
        seen["blockers"] = blockers

    def fake_nudges(tasks=None, render=None, **kwargs):
        seen["nudge"] = render([task], __import__("datetime").date(2026, 10, 6))

    monkeypatch.setattr("agent.post_digest", fake_post)
    monkeypatch.setattr("agent.send_nudges", fake_nudges)

    def fake_llm(prompt: str) -> str:
        if prompt.startswith("Rewrite"):
            return "Hi, KAN-2 still needs a look."
        return '{"blocked": true, "reason": "Waiting for the design file"}'

    result = build_graph(fake_llm).invoke({})
    assert result["notified"] is True
    assert seen["overdue"] == ["KAN-2"]
    assert seen["blockers"][0]["reason"] == "Waiting for the design file"
    assert "KAN-2" in seen["nudge"]
