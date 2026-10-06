"""Phase 3: post one daily risk digest to Slack."""

import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from jira import Task, fetch_tasks
from risk import group_risks

ROOT = Path(__file__).resolve().parents[1]
DIGEST_HOUR = 9
LABELS = (
    ("overdue", "Overdue"),
    ("due_soon", "Due soon"),
    ("stale", "Stale"),
)


def format_digest(
    groups: dict[str, list[Task]],
    today: date | None = None,
    blockers: list[dict] | None = None,
) -> str:
    """Turn the three risk groups into one Slack message."""
    current = today or date.today()
    lines = [f"*PM Agent daily digest* — {current.isoformat()}", ""]
    for key, label in LABELS:
        tasks = groups[key]
        lines.append(f"*{label} ({len(tasks)})*")
        if not tasks:
            lines.append("• none")
        else:
            for task in tasks:
                lines.append(
                    f"• {task.key} {task.title} — due {task.due_date} ({task.assignee})"
                )
        lines.append("")
    if blockers is not None:
        flagged = [item for item in blockers if item.get("blocked")]
        lines.append(f"*Blocked in comments ({len(flagged)})*")
        if not flagged:
            lines.append("• none")
        else:
            for item in flagged:
                lines.append(f"• {item['key']} {item['title']} — {item['reason']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def post_digest(
    groups: dict[str, list[Task]],
    today: date | None = None,
    blockers: list[dict] | None = None,
) -> None:
    """Send the digest to the Slack channel named in .env."""
    load_dotenv(ROOT / ".env")
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel = os.getenv("SLACK_CHANNEL", "#pm-agent").strip()
    if not token or token == "xoxb-your-bot-token":
        print("Add your real SLACK_BOT_TOKEN to the .env file, then run this again.")
        sys.exit(1)

    text = format_digest(groups, today, blockers)
    client = WebClient(token=token)
    try:
        client.chat_postMessage(channel=channel, text=text)
    except SlackApiError as error:
        print(f"Slack rejected the message: {error.response['error']}")
        sys.exit(1)
    print(f"Posted digest to {channel}")


def send_today() -> None:
    post_digest(group_risks(fetch_tasks()))


def run_daily() -> None:
    """Keep this window open. Posts once every morning at 9:00 India time."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()
    scheduler.add_job(
        send_today,
        CronTrigger(hour=DIGEST_HOUR, minute=0, timezone="Asia/Kolkata"),
    )
    print("Daily digest scheduled for 9:00 AM India time. Leave this window open.")
    scheduler.start()


if __name__ == "__main__":
    if "--daily" in sys.argv:
        run_daily()
    else:
        send_today()
