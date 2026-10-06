"""Slack buttons and the approval step before any Jira write."""

import hashlib
import hmac
import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from jira import ROOT, Task, apply_decision

DB_PATH = ROOT / "data" / "nudges.db"

ACTIONS = {
    "task_done": "done",
    "task_blocked": "blocked",
    "task_need_time": "need_time",
}
LABELS = {
    "done": "Done",
    "blocked": "Blocked",
    "need_time": "Need more time",
}
MAX_AGE_SECONDS = 60 * 5

app = FastAPI()


def nudge_blocks(text: str, tasks: list[Task]) -> list[dict]:
    """Slack blocks: the nudge text, then three buttons for each task."""
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text.strip()}}
    ]
    for task in tasks:
        blocks.append(
            {
                "type": "actions",
                "block_id": task.key,
                "elements": [
                    _button("Done", "task_done", task.key, "primary"),
                    _button("Blocked", "task_blocked", task.key, "danger"),
                    _button("Need more time", "task_need_time", task.key),
                ],
            }
        )
    return blocks


def verify_slack_signature(
    raw_body: bytes,
    timestamp: str,
    signature: str,
    secret: str,
    now: float | None = None,
) -> bool:
    """True when the body matches Slack's signing secret and is recent."""
    if not secret or not timestamp or not signature:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = datetime.now(timezone.utc).timestamp() if now is None else now
    if abs(current - sent_at) > MAX_AGE_SECONDS:
        return False
    digest = hmac.new(
        secret.encode("utf-8"),
        f"v0:{timestamp}:{raw_body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"v0={digest}", signature)


def parse_payload(raw_body: bytes) -> dict:
    raw = parse_qs(raw_body.decode("utf-8")).get("payload", [""])[0]
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_key TEXT NOT NULL,
            action TEXT NOT NULL,
            slack_user_id TEXT NOT NULL,
            received_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_key TEXT NOT NULL,
            action TEXT NOT NULL,
            slack_user_id TEXT NOT NULL,
            status TEXT NOT NULL,
            received_at TEXT NOT NULL
        )
        """
    )
    return connection


def record_reply(
    connection: sqlite3.Connection,
    task_key: str,
    action: str,
    slack_user_id: str,
    received_at: datetime,
) -> None:
    connection.execute(
        """
        INSERT INTO replies (task_key, action, slack_user_id, received_at)
        VALUES (?, ?, ?, ?)
        """,
        (task_key, action, slack_user_id, received_at.isoformat()),
    )
    connection.commit()


def approval_blocks(task_key: str, kind: str, approval_id: int) -> list[dict]:
    """Channel message asking a person to approve one decision."""
    text = f"*{task_key}* was marked *{LABELS[kind]}*. Approve before Jira changes."
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "block_id": f"approval-{approval_id}",
            "elements": [
                _button("Approve", "approve_request", str(approval_id), "primary"),
                _button("Reject", "reject_request", str(approval_id), "danger"),
            ],
        },
    ]


def handle_action(
    payload: dict,
    db_path: Path = DB_PATH,
    now: datetime | None = None,
    post_channel=None,
    apply_jira=None,
) -> dict:
    """Save a task click for approval, or apply a decision after Approve."""
    action = (payload.get("actions") or [{}])[0]
    action_id = str(action.get("action_id") or "")
    if action_id in ("approve_request", "reject_request"):
        return _decide(action_id, action.get("value"), db_path, apply_jira or apply_decision)

    kind = ACTIONS.get(action_id)
    task_key = str(action.get("value") or "").strip()
    slack_user_id = str((payload.get("user") or {}).get("id") or "")
    if not kind or not task_key:
        return {"replace_original": False, "text": "That button was not recognized."}

    received_at = now or datetime.now(timezone.utc)
    connection = connect(db_path)
    record_reply(connection, task_key, kind, slack_user_id, received_at)
    cursor = connection.execute(
        """
        INSERT INTO approvals (task_key, action, slack_user_id, status, received_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (task_key, kind, slack_user_id, received_at.isoformat()),
    )
    approval_id = int(cursor.lastrowid)
    connection.commit()
    connection.close()

    notice = (
        f"Recorded {task_key} as {LABELS[kind]}. "
        "Jira stays unchanged until a person approves."
    )
    blocks = approval_blocks(task_key, kind, approval_id)
    if post_channel is not None:
        try:
            post_channel(blocks[0]["text"]["text"], blocks)
        except Exception as error:
            return {
                "replace_original": False,
                "text": f"{notice} The approval message was not posted. {error}",
            }
    return {"replace_original": False, "text": notice}


def _decide(action_id: str, raw_id, db_path: Path, apply_jira) -> dict:
    try:
        approval_id = int(str(raw_id).strip())
    except (TypeError, ValueError):
        return {"replace_original": False, "text": "That button was not recognized."}

    connection = connect(db_path)
    row = connection.execute(
        "SELECT task_key, action, status FROM approvals WHERE id = ?",
        (approval_id,),
    ).fetchone()
    if row is None:
        connection.close()
        return {"replace_original": False, "text": "That button was not recognized."}
    task_key, kind, status = row
    if status != "pending":
        connection.close()
        return {"replace_original": False, "text": f"{task_key} was already {status}."}

    if action_id == "reject_request":
        connection.execute(
            "UPDATE approvals SET status = 'rejected' WHERE id = ? AND status = 'pending'",
            (approval_id,),
        )
        connection.commit()
        connection.close()
        return {
            "replace_original": True,
            "text": f"Rejected. {task_key} was not changed in Jira.",
        }

    try:
        apply_jira(task_key, kind)
    except Exception as error:
        connection.close()
        return {
            "replace_original": False,
            "text": f"Jira did not update {task_key}. {error}",
        }
    connection.execute(
        "UPDATE approvals SET status = 'approved' WHERE id = ? AND status = 'pending'",
        (approval_id,),
    )
    connection.commit()
    connection.close()
    return {"replace_original": True, "text": _approved_text(task_key, kind)}


def _approved_text(task_key: str, kind: str) -> str:
    if kind == "done":
        return f"Approved. {task_key} was moved to Done in Jira."
    if kind == "blocked":
        return f"Approved. A blocked comment was added to {task_key} in Jira."
    return f"Approved. A comment was added to {task_key} in Jira asking for more time."


def handle_request(
    raw_body: bytes,
    timestamp: str,
    signature: str,
    secret: str,
    db_path: Path = DB_PATH,
    now: float | None = None,
) -> tuple[int, dict]:
    if not verify_slack_signature(raw_body, timestamp, signature, secret, now):
        return 401, {"text": "Slack signature check failed."}
    return 200, handle_action(parse_payload(raw_body), db_path)


@app.post("/slack/actions")
async def slack_actions(request: Request) -> JSONResponse:
    load_dotenv(ROOT / ".env")
    raw_body = await request.body()
    status, body = handle_request(
        raw_body,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
        os.getenv("SLACK_SIGNING_SECRET", "").strip(),
    )
    return JSONResponse(status_code=status, content=body)


def on_socket_request(client, request, db_path: Path = DB_PATH) -> None:
    """Ack a Socket Mode click, save it, then confirm in the Slack thread."""
    from slack_sdk.socket_mode.response import SocketModeResponse

    client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))
    if getattr(request, "type", "") != "interactive":
        return
    payload = request.payload if isinstance(request.payload, dict) else {}
    body = handle_action(payload, db_path, post_channel=_poster_from(client))
    response_url = str(payload.get("response_url") or "")
    if not response_url:
        print(body["text"])
        return
    try:
        requests.post(response_url, json=body, timeout=10)
    except requests.RequestException as error:
        print(f"Saved the click, but Slack did not accept the reply: {error}")


def run_socket_mode(app_token: str) -> None:
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient

    bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    client = SocketModeClient(app_token=app_token, web_client=WebClient(token=bot_token))
    client.socket_mode_request_listeners.append(on_socket_request)
    print("Socket Mode is on. Listening for button clicks. Leave this window open.")
    client.connect()
    threading.Event().wait()


def _poster_from(client):
    web = getattr(client, "web_client", None)
    if web is None:
        return None
    load_dotenv(ROOT / ".env")
    channel = os.getenv("SLACK_CHANNEL", "#pm-agent").strip() or "#pm-agent"

    def post(text: str, blocks: list[dict]) -> None:
        web.chat_postMessage(channel=channel, text=text, blocks=blocks)

    return post


def _button(label: str, action_id: str, value: str, style: str | None = None) -> dict:
    button = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
        "value": value,
    }
    if style:
        button["style"] = style
    return button


if __name__ == "__main__":
    load_dotenv(ROOT / ".env")
    app_token = os.getenv("SLACK_APP_TOKEN", "").strip()
    if not app_token or app_token == "xapp-your-app-token":
        print("Add SLACK_APP_TOKEN to the .env file, then run this again.")
        print("Socket Mode is enabled in Slack, so a Request URL is not used.")
        sys.exit(1)
    run_socket_mode(app_token)
