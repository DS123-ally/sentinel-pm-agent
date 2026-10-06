"""Phase 4: DM each person about their own at-risk tasks, once per task per day."""

import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from actions import nudge_blocks
from jira import Task, fetch_tasks
from risk import group_risks, is_due_soon, is_overdue, is_stale

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "nudges.db"
INDIA = ZoneInfo("Asia/Kolkata")
QUIET_START_HOUR = 21
QUIET_END_HOUR = 8


def is_quiet_hours(now: datetime) -> bool:
    """True from 9:00 PM through 7:59 AM India time."""
    local = now.astimezone(INDIA) if now.tzinfo else now
    return local.hour >= QUIET_START_HOUR or local.hour < QUIET_END_HOUR


def at_risk_tasks(tasks: list[Task], today: date | None = None) -> list[Task]:
    """Open tasks that are overdue, due soon, or stale. Each task appears once."""
    groups = group_risks(tasks, today)
    chosen: list[Task] = []
    seen: set[str] = set()
    for name in ("overdue", "due_soon", "stale"):
        for task in groups[name]:
            if task.key not in seen:
                seen.add(task.key)
                chosen.append(task)
    return chosen


def pending_by_person(
    tasks: list[Task],
    today: date,
    already_sent: set[str],
) -> dict[str, list[Task]]:
    """Group tasks that still need a nudge today. Skip unassigned tasks."""
    grouped: dict[str, list[Task]] = {}
    for task in at_risk_tasks(tasks, today):
        if task.assignee == "Unassigned" or task.key in already_sent:
            continue
        grouped.setdefault(task.assignee, []).append(task)
    return grouped


def format_nudge(tasks: list[Task], today: date) -> str:
    """One direct message listing only this person's tasks."""
    lines = ["*Your at-risk tasks*", ""]
    for task in tasks:
        lines.append(
            f"• {task.key} {task.title} — {_reasons(task, today)}, due {task.due_date}"
        )
    return "\n".join(lines) + "\n"


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS nudges (
            task_key TEXT NOT NULL,
            sent_on TEXT NOT NULL,
            assignee TEXT NOT NULL,
            slack_user_id TEXT NOT NULL,
            PRIMARY KEY (task_key, sent_on)
        )
        """
    )
    return connection


def sent_today(connection: sqlite3.Connection, today: date) -> set[str]:
    rows = connection.execute(
        "SELECT task_key FROM nudges WHERE sent_on = ?",
        (today.isoformat(),),
    ).fetchall()
    return {row[0] for row in rows}


def record_nudge(
    connection: sqlite3.Connection,
    task: Task,
    today: date,
    slack_user_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO nudges (task_key, sent_on, assignee, slack_user_id)
        VALUES (?, ?, ?, ?)
        """,
        (task.key, today.isoformat(), task.assignee, slack_user_id),
    )
    connection.commit()


def find_slack_user(client: WebClient, task: Task) -> str | None:
    """Match a Jira assignee to a Slack user by email, then by name."""
    email = task.assignee_email.strip().casefold()
    if email:
        try:
            found = client.users_lookupByEmail(email=task.assignee_email.strip())
            return found["user"]["id"]
        except SlackApiError:
            pass

    cursor = None
    wanted_name = task.assignee.strip().casefold()
    while True:
        params: dict[str, str | int] = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        response = client.users_list(**params)
        for member in response.get("members", []):
            if member.get("is_bot") or member.get("deleted") or member.get("id") == "USLACKBOT":
                continue
            profile = member.get("profile") or {}
            member_email = (profile.get("email") or "").casefold()
            names = {
                (member.get("real_name") or "").casefold(),
                (profile.get("real_name") or "").casefold(),
                (profile.get("display_name") or "").casefold(),
            }
            if (email and member_email == email) or wanted_name in names:
                return member["id"]
        cursor = (response.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            return None


def send_dm(
    client: WebClient,
    slack_user_id: str,
    text: str,
    blocks: list[dict] | None = None,
) -> None:
    opened = client.conversations_open(users=slack_user_id)
    channel = opened["channel"]["id"]
    message: dict = {"channel": channel, "text": text}
    if blocks:
        message["blocks"] = blocks
    client.chat_postMessage(**message)


def send_nudges(
    now: datetime | None = None,
    db_path: Path = DB_PATH,
    tasks: list[Task] | None = None,
    render=None,
) -> None:
    """Send one DM per person. Skip night hours and tasks already nudged today."""
    current = now or datetime.now(INDIA)
    today = current.date() if current.tzinfo is None else current.astimezone(INDIA).date()
    if is_quiet_hours(current):
        print("Quiet hours (9:00 PM to 8:00 AM). No nudges sent.")
        return

    load_dotenv(ROOT / ".env")
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not token or token == "xoxb-your-bot-token":
        print("Add your real SLACK_BOT_TOKEN to the .env file, then run this again.")
        sys.exit(1)

    if tasks is None:
        tasks = fetch_tasks()
    write_message = render or format_nudge
    connection = connect(db_path)
    grouped = pending_by_person(tasks, today, sent_today(connection, today))
    if not grouped:
        print("No new nudges. Everyone was already messaged about today's tasks.")
        connection.close()
        return

    client = WebClient(token=token)
    user_ids: dict[str, str] = {}
    for assignee, person_tasks in grouped.items():
        slack_user_id = user_ids.get(assignee)
        if slack_user_id is None:
            slack_user_id = find_slack_user(client, person_tasks[0]) or ""
            user_ids[assignee] = slack_user_id
        if not slack_user_id:
            print(f"No Slack user found for {assignee}. Skipped {len(person_tasks)} task(s).")
            continue
        try:
            message = write_message(person_tasks, today)
            send_dm(client, slack_user_id, message, nudge_blocks(message, person_tasks))
        except SlackApiError as error:
            print(f"Slack rejected the nudge for {assignee}: {error.response['error']}")
            continue
        for task in person_tasks:
            record_nudge(connection, task, today, slack_user_id)
        print(f"Nudged {assignee} about {len(person_tasks)} task(s).")
    connection.close()


def _reasons(task: Task, today: date) -> str:
    labels = []
    if is_overdue(task, today):
        labels.append("overdue")
    if is_due_soon(task, today):
        labels.append("due soon")
    if is_stale(task, today):
        labels.append("stale")
    return ", ".join(labels)


if __name__ == "__main__":
    send_nudges()
