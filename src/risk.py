"""Phase 2: flag at-risk tasks with plain date rules."""

from datetime import date, timedelta

from jira import Task, fetch_tasks

DONE_STATUSES = {"done"}
DUE_SOON_DAYS = 2
STALE_DAYS = 3


def is_overdue(task: Task, today: date | None = None) -> bool:
    """True when an open task's due date is before today."""
    if _is_done(task):
        return False
    due = _parse_date(task.due_date)
    if due is None:
        return False
    return due < _today(today)


def is_due_soon(task: Task, today: date | None = None) -> bool:
    """True when an open task is due today or within the next 48 hours."""
    if _is_done(task):
        return False
    due = _parse_date(task.due_date)
    if due is None:
        return False
    current = _today(today)
    return current <= due <= current + timedelta(days=DUE_SOON_DAYS)


def is_stale(task: Task, today: date | None = None) -> bool:
    """True when an open task has not been updated in 3 days."""
    if _is_done(task):
        return False
    updated = _parse_date(task.last_updated)
    if updated is None:
        return False
    return (_today(today) - updated).days >= STALE_DAYS


def group_risks(tasks: list[Task], today: date | None = None) -> dict[str, list[Task]]:
    """Sort open tasks into overdue, due soon, and stale."""
    return {
        "overdue": [task for task in tasks if is_overdue(task, today)],
        "due_soon": [task for task in tasks if is_due_soon(task, today)],
        "stale": [task for task in tasks if is_stale(task, today)],
    }


def print_risks(groups: dict[str, list[Task]]) -> None:
    labels = {
        "overdue": "Overdue",
        "due_soon": "Due soon (within 48 hours)",
        "stale": "Stale (no update in 3 days)",
    }
    for name in ("overdue", "due_soon", "stale"):
        tasks = groups[name]
        print(f"{labels[name]} ({len(tasks)})")
        if not tasks:
            print("  none")
        for task in tasks:
            print(f"  {task.key}  {task.title}  due {task.due_date}  updated {task.last_updated}")
        print()


def _is_done(task: Task) -> bool:
    return task.status.strip().lower() in DONE_STATUSES


def _parse_date(value: str) -> date | None:
    if not value or value == "-":
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _today(today: date | None) -> date:
    return today or date.today()


if __name__ == "__main__":
    print_risks(group_risks(fetch_tasks()))
