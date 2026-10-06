"""Phase 1: fetch Jira issues and turn them into Task objects."""

import os
from dataclasses import dataclass
from datetime import datetime

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth


@dataclass
class Task:
    key: str
    title: str
    assignee: str
    status: str
    due_date: str
    last_updated: str
    assignee_email: str = ""


def fetch_tasks() -> list[Task]:
    """Fetch every issue in the Jira project named in .env."""
    load_dotenv()
    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    email = os.environ["JIRA_EMAIL"]
    token = os.environ["JIRA_API_TOKEN"]
    project_key = os.environ["JIRA_PROJECT_KEY"]

    auth = HTTPBasicAuth(email, token)
    url = f"{base_url}/rest/api/3/search/jql"
    tasks: list[Task] = []
    next_page_token: str | None = None

    while True:
        params: dict[str, str | int] = {
            "jql": f"project = {project_key} ORDER BY key ASC",
            "maxResults": 50,
            "fields": "summary,assignee,status,duedate,updated",
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        response = requests.get(url, params=params, auth=auth, timeout=30)
        response.raise_for_status()
        payload = response.json()

        for issue in payload.get("issues", []):
            tasks.append(_to_task(issue))

        next_page_token = payload.get("nextPageToken")
        if payload.get("isLast", True) or not next_page_token:
            break

    return tasks


def _to_task(issue: dict) -> Task:
    fields = issue.get("fields", {})
    assignee = fields.get("assignee") or {}
    status = fields.get("status") or {}
    return Task(
        key=issue.get("key", ""),
        title=fields.get("summary") or "(no title)",
        assignee=assignee.get("displayName") or "Unassigned",
        status=status.get("name") or "Unknown",
        due_date=fields.get("duedate") or "-",
        last_updated=_short_date(fields.get("updated")),
        assignee_email=assignee.get("emailAddress") or "",
    )


def _short_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return value[:10]


def print_tasks(tasks: list[Task]) -> None:
    headers = ("Key", "Title", "Assignee", "Status", "Due", "Updated")
    rows = [
        (task.key, task.title, task.assignee, task.status, task.due_date, task.last_updated)
        for task in tasks
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows)) if rows else len(headers[index])
        for index in range(len(headers))
    ]

    def format_row(values: tuple[str, ...]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(values))

    print(format_row(headers))
    print("-+-".join("-" * width for width in widths))
    if not rows:
        print("No tasks found.")
        return
    for row in rows:
        print(format_row(row))
    print(f"\n{len(rows)} task(s)")


if __name__ == "__main__":
    print_tasks(fetch_tasks())
