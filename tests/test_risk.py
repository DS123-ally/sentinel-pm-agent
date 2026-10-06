"""Tests for Phase 2 risk rules. Dates are fixed so the checks do not change tomorrow."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jira import Task
from risk import group_risks, is_due_soon, is_overdue, is_stale

TODAY = date(2026, 10, 6)


def make_task(
    key: str,
    due_date: str,
    last_updated: str,
    status: str = "To Do",
) -> Task:
    return Task(
        key=key,
        title=key,
        assignee="Dinesh",
        status=status,
        due_date=due_date,
        last_updated=last_updated,
    )


def test_overdue_when_due_date_is_before_today():
    task = make_task("KAN-2", "2026-10-01", "2026-10-06")
    assert is_overdue(task, TODAY) is True


def test_due_today_is_not_overdue():
    task = make_task("KAN-6", "2026-10-06", "2026-10-06")
    assert is_overdue(task, TODAY) is False


def test_due_soon_covers_today_through_two_days():
    due_today = make_task("KAN-6", "2026-10-06", "2026-10-06")
    due_in_two_days = make_task("KAN-7", "2026-10-08", "2026-10-06")
    due_in_three_days = make_task("KAN-11", "2026-10-09", "2026-10-06")
    assert is_due_soon(due_today, TODAY) is True
    assert is_due_soon(due_in_two_days, TODAY) is True
    assert is_due_soon(due_in_three_days, TODAY) is False


def test_stale_when_last_update_was_three_days_ago():
    stale = make_task("KAN-20", "2026-10-20", "2026-10-03")
    fresh = make_task("KAN-21", "2026-10-20", "2026-10-04")
    assert is_stale(stale, TODAY) is True
    assert is_stale(fresh, TODAY) is False


def test_done_tasks_are_never_flagged():
    task = make_task("KAN-14", "2026-09-20", "2026-09-01", status="Done")
    assert is_overdue(task, TODAY) is False
    assert is_due_soon(task, TODAY) is False
    assert is_stale(task, TODAY) is False


def test_missing_dates_are_not_flagged():
    task = make_task("KAN-1", "-", "-")
    assert is_overdue(task, TODAY) is False
    assert is_due_soon(task, TODAY) is False
    assert is_stale(task, TODAY) is False


def test_group_risks_sorts_each_category():
    tasks = [
        make_task("KAN-2", "2026-10-01", "2026-10-06"),
        make_task("KAN-6", "2026-10-06", "2026-10-06"),
        make_task("KAN-20", "2026-10-20", "2026-10-01"),
        make_task("KAN-14", "2026-09-20", "2026-09-01", status="Done"),
    ]
    groups = group_risks(tasks, TODAY)
    assert [task.key for task in groups["overdue"]] == ["KAN-2"]
    assert [task.key for task in groups["due_soon"]] == ["KAN-6"]
    assert [task.key for task in groups["stale"]] == ["KAN-20"]
