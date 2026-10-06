"""Tests for the Phase 3 Slack digest text. No Slack call is made."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jira import Task
from digest import format_digest

TODAY = date(2026, 10, 6)


def make_task(key: str, title: str, due_date: str, assignee: str = "Dinesh") -> Task:
    return Task(
        key=key,
        title=title,
        assignee=assignee,
        status="To Do",
        due_date=due_date,
        last_updated="2026-10-06",
    )


def test_daily_command_runs_the_full_morning_job(monkeypatch):
    called = []
    monkeypatch.setattr("morning.run_scheduled", lambda: called.append("morning"))
    from digest import run_daily

    run_daily()
    assert called == ["morning"]


def test_digest_lists_each_risk_group():
    groups = {
        "overdue": [make_task("KAN-2", "Write test plan", "2026-10-01")],
        "due_soon": [make_task("KAN-6", "Review API design", "2026-10-06")],
        "stale": [],
    }
    text = format_digest(groups, TODAY)
    assert "*PM Agent daily digest* — 2026-10-06" in text
    assert "*Overdue (1)*" in text
    assert "• KAN-2 Write test plan — due 2026-10-01 (Dinesh)" in text
    assert "*Due soon (1)*" in text
    assert "• KAN-6 Review API design — due 2026-10-06 (Dinesh)" in text
    assert "*Stale (0)*" in text
    assert "• none" in text
