"""Phase 6 tests. No Slack call is made."""

import hashlib
import hmac
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from actions import connect, handle_action, handle_request, nudge_blocks, on_socket_request
from jira import Task

NOW = datetime(2026, 10, 6, 10, 0, tzinfo=timezone.utc)
SECRET = "test-secret"


def make_task(key: str = "KAN-2") -> Task:
    return Task(
        key=key,
        title="Write test plan",
        assignee="Dinesh",
        status="To Do",
        due_date="2026-10-01",
        last_updated="2026-10-06",
    )


def test_each_task_gets_three_buttons():
    blocks = nudge_blocks("Your at-risk tasks", [make_task("KAN-2"), make_task("KAN-6")])
    buttons = [element for block in blocks if block["type"] == "actions" for element in block["elements"]]
    assert [button["text"]["text"] for button in buttons[:3]] == [
        "Done",
        "Blocked",
        "Need more time",
    ]
    assert [button["value"] for button in buttons if button["action_id"] == "task_done"] == [
        "KAN-2",
        "KAN-6",
    ]


def test_a_click_is_saved_and_jira_is_not_mentioned_as_updated(tmp_path):
    db_path = tmp_path / "nudges.db"
    body = handle_action(
        {
            "user": {"id": "U123"},
            "actions": [{"action_id": "task_need_time", "value": "KAN-2"}],
        },
        db_path,
        NOW,
    )
    assert "KAN-2" in body["text"]
    assert "Need more time" in body["text"]
    assert "unchanged" in body["text"]
    connection = connect(db_path)
    row = connection.execute(
        "SELECT task_key, action, slack_user_id FROM replies"
    ).fetchone()
    connection.close()
    assert row == ("KAN-2", "need_time", "U123")


def test_unknown_button_is_not_saved(tmp_path):
    db_path = tmp_path / "nudges.db"
    body = handle_action({"actions": [{"action_id": "other", "value": "KAN-2"}]}, db_path, NOW)
    assert "not recognized" in body["text"]
    connection = connect(db_path)
    count = connection.execute("SELECT COUNT(*) FROM replies").fetchone()[0]
    connection.close()
    assert count == 0


def test_socket_mode_click_is_saved(tmp_path, monkeypatch):
    posted = {}

    def fake_post(url, json, timeout):
        posted["url"] = url
        posted["text"] = json["text"]

    monkeypatch.setattr("actions.requests.post", fake_post)

    class Request:
        type = "interactive"
        envelope_id = "env-1"
        payload = {
            "user": {"id": "U123"},
            "response_url": "https://hooks.slack.com/actions/T/B/secret",
            "actions": [{"action_id": "task_blocked", "value": "KAN-2"}],
        }

    class Client:
        def __init__(self):
            self.acks = []

        def send_socket_mode_response(self, response):
            self.acks.append(response.envelope_id)

    client = Client()
    on_socket_request(client, Request(), tmp_path / "nudges.db")
    assert client.acks == ["env-1"]
    assert "Blocked" in posted["text"]


def _approval_id(db_path: Path) -> int:
    connection = connect(db_path)
    approval_id = connection.execute("SELECT id FROM approvals").fetchone()[0]
    connection.close()
    return approval_id


def test_a_click_posts_approval_and_does_not_write_jira(tmp_path):
    db_path = tmp_path / "nudges.db"
    posted = []
    applied = []
    handle_action(
        {"user": {"id": "U123"}, "actions": [{"action_id": "task_done", "value": "KAN-2"}]},
        db_path,
        NOW,
        post_channel=lambda text, blocks: posted.append(blocks),
        apply_jira=lambda key, action: applied.append((key, action)),
    )
    buttons = posted[0][1]["elements"]
    assert [button["text"]["text"] for button in buttons] == ["Approve", "Reject"]
    assert applied == []
    connection = connect(db_path)
    status = connection.execute("SELECT status FROM approvals").fetchone()[0]
    connection.close()
    assert status == "pending"


def test_reject_leaves_jira_unchanged(tmp_path):
    db_path = tmp_path / "nudges.db"
    applied = []
    handle_action(
        {"user": {"id": "U123"}, "actions": [{"action_id": "task_blocked", "value": "KAN-2"}]},
        db_path,
        NOW,
        apply_jira=lambda key, action: applied.append((key, action)),
    )
    body = handle_action(
        {"actions": [{"action_id": "reject_request", "value": str(_approval_id(db_path))}]},
        db_path,
        NOW,
        apply_jira=lambda key, action: applied.append((key, action)),
    )
    assert "not changed" in body["text"]
    assert applied == []


def test_approve_writes_jira_once(tmp_path):
    db_path = tmp_path / "nudges.db"
    applied = []
    handle_action(
        {"user": {"id": "U123"}, "actions": [{"action_id": "task_need_time", "value": "KAN-2"}]},
        db_path,
        NOW,
    )
    approval_id = str(_approval_id(db_path))
    body = handle_action(
        {"actions": [{"action_id": "approve_request", "value": approval_id}]},
        db_path,
        NOW,
        apply_jira=lambda key, action: applied.append((key, action)),
    )
    again = handle_action(
        {"actions": [{"action_id": "approve_request", "value": approval_id}]},
        db_path,
        NOW,
        apply_jira=lambda key, action: applied.append((key, action)),
    )
    assert applied == [("KAN-2", "need_time")]
    assert "Approved" in body["text"]
    assert "already approved" in again["text"]


def test_a_failed_jira_write_stays_pending(tmp_path):
    db_path = tmp_path / "nudges.db"
    handle_action(
        {"user": {"id": "U123"}, "actions": [{"action_id": "task_done", "value": "KAN-2"}]},
        db_path,
        NOW,
    )

    def fail(key, action):
        raise RuntimeError("no transition")

    body = handle_action(
        {"actions": [{"action_id": "approve_request", "value": str(_approval_id(db_path))}]},
        db_path,
        NOW,
        apply_jira=fail,
    )
    assert "did not update" in body["text"]
    connection = connect(db_path)
    status = connection.execute("SELECT status FROM approvals").fetchone()[0]
    connection.close()
    assert status == "pending"


def test_signed_click_is_accepted_and_a_bad_signature_is_rejected(tmp_path):
    db_path = tmp_path / "nudges.db"
    raw = urlencode(
        {
            "payload": json.dumps(
                {
                    "user": {"id": "U123"},
                    "actions": [{"action_id": "task_done", "value": "KAN-2"}],
                }
            )
        }
    ).encode("utf-8")
    timestamp = str(int(NOW.timestamp()))
    digest = hmac.new(
        SECRET.encode("utf-8"),
        f"v0:{timestamp}:{raw.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    status, body = handle_request(raw, timestamp, f"v0={digest}", SECRET, db_path, NOW.timestamp())
    assert status == 200
    assert "Done" in body["text"]

    status, _body = handle_request(raw, timestamp, "v0=nope", SECRET, db_path, NOW.timestamp())
    assert status == 401
