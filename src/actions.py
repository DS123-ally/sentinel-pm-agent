"""Phase 6: Done, Blocked, and Need more time buttons on nudge messages."""

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

from jira import ROOT, Task

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


def handle_action(
    payload: dict,
    db_path: Path = DB_PATH,
    now: datetime | None = None,
) -> dict:
    """Save the click. Jira is left alone until a later approval step."""
    action = (payload.get("actions") or [{}])[0]
    kind = ACTIONS.get(str(action.get("action_id") or ""))
    task_key = str(action.get("value") or "").strip()
    slack_user_id = str((payload.get("user") or {}).get("id") or "")
    if not kind or not task_key:
        return {"replace_original": False, "text": "That button was not recognized."}

    received_at = now or datetime.now(timezone.utc)
    connection = connect(db_path)
    record_reply(connection, task_key, kind, slack_user_id, received_at)
    connection.close()
    return {
        "replace_original": False,
        "text": (
            f"Recorded {task_key} as {LABELS[kind]}. "
            "Jira stays unchanged until a person approves."
        ),
    }


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
    body = handle_action(payload, db_path)
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


def _button(label: str, action_id: str, task_key: str, style: str | None = None) -> dict:
    button = {
        "type": "button",
        "text": {"type": "plain_text", "text": label},
        "action_id": action_id,
        "value": task_key,
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
