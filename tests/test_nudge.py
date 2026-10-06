"""Tests for Phase 4 nudges. No Slack call is made."""

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jira import Task
from nudge import (
    connect,
    format_nudge,
    is_quiet_hours,
    pending_by_person,
    record_nudge,
    sent_today,
)

TODAY = date(2026, 10, 6)
INDIA = ZoneInfo("Asia/Kolkata")


def make_task(
    key: str,
    assignee: str,
    due_date: str,
    last_updated: str = "2026-10-06",
    status: str = "To Do",
) -> Task:
    return Task(
        key=key,
        title=key,
        assignee=assignee,
        status=status,
        due_date=due_date,
        last_updated=last_updated,
    )


def test_quiet_hours_block_night_and_allow_afternoon():
    assert is_quiet_hours(datetime(2026, 10, 6, 22, 0, tzinfo=INDIA)) is True
    assert is_quiet_hours(datetime(2026, 10, 6, 7, 30, tzinfo=INDIA)) is True
    assert is_quiet_hours(datetime(2026, 10, 6, 13, 0, tzinfo=INDIA)) is False
    assert is_quiet_hours(datetime(2026, 10, 6, 9, 0, tzinfo=INDIA)) is False


def test_each_person_gets_only_their_open_tasks():
    tasks = [
        make_task("KAN-2", "Dinesh", "2026-10-01"),
        make_task("KAN-6", "Dinesh", "2026-10-06"),
        make_task("KAN-20", "Asha", "2026-10-01"),
        make_task("KAN-14", "Dinesh", "2026-09-20", status="Done"),
        make_task("KAN-1", "Unassigned", "2026-10-01"),
    ]
    grouped = pending_by_person(tasks, TODAY, set())
    assert [task.key for task in grouped["Dinesh"]] == ["KAN-2", "KAN-6"]
    assert [task.key for task in grouped["Asha"]] == ["KAN-20"]
    assert "Unassigned" not in grouped


def test_a_task_is_nudged_only_once_per_day():
    tasks = [make_task("KAN-2", "Dinesh", "2026-10-01")]
    grouped = pending_by_person(tasks, TODAY, {"KAN-2"})
    assert grouped == {}


def test_sqlite_remembers_nudges_for_the_day(tmp_path):
    task = make_task("KAN-2", "Dinesh", "2026-10-01")
    connection = connect(tmp_path / "nudges.db")
    assert sent_today(connection, TODAY) == set()
    record_nudge(connection, task, TODAY, "U123")
    assert sent_today(connection, TODAY) == {"KAN-2"}
    assert sent_today(connection, date(2026, 10, 7)) == set()
    connection.close()


def test_nudge_text_lists_only_the_given_tasks():
    tasks = [make_task("KAN-2", "Dinesh", "2026-10-01")]
    text = format_nudge(tasks, TODAY)
    assert "KAN-2" in text
    assert "overdue" in text
    assert "Asha" not in text
