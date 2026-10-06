"""Phase 5: LangGraph flow with three nodes — fetch, analyze, notify."""

import json
from dataclasses import asdict
from typing import Callable

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from digest import post_digest
from jira import Task, fetch_tasks_with_comments
from llm import complete
from nudge import format_nudge, send_nudges
from risk import group_risks

LLM = Callable[[str], str]


class AgentState(TypedDict, total=False):
    tasks: list[dict]
    risks: dict[str, list[dict]]
    blockers: list[dict]
    notified: bool


def build_graph(llm: LLM | None = None) -> object:
    """Fetch Jira, find risks and blockers, then post Slack messages."""
    model = llm or complete

    def fetch_node(state: AgentState) -> AgentState:
        tasks = fetch_tasks_with_comments()
        return {"tasks": [asdict(task) for task in tasks]}

    def analyze_node(state: AgentState) -> AgentState:
        tasks = [_task(item) for item in state.get("tasks", [])]
        risks = group_risks(tasks)
        blockers = [read_blocker(task, model) for task in tasks if not _is_done(task)]
        return {
            "risks": {name: [asdict(task) for task in items] for name, items in risks.items()},
            "blockers": blockers,
        }

    def notify_node(state: AgentState) -> AgentState:
        risks = {name: [_task(item) for item in items] for name, items in state.get("risks", {}).items()}
        blockers = state.get("blockers", [])
        tasks = [_task(item) for item in state.get("tasks", [])]
        post_digest(risks, blockers=blockers)

        def render(person_tasks: list[Task], today) -> str:
            return friendly_nudge(person_tasks, today, model)

        send_nudges(tasks=tasks, render=render)
        _print_blockers(blockers)
        return {"notified": True}

    graph = StateGraph(AgentState)
    graph.add_node("fetch", fetch_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("notify", notify_node)
    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "analyze")
    graph.add_edge("analyze", "notify")
    graph.add_edge("notify", END)
    return graph.compile()


def read_blocker(task: Task, llm: LLM) -> dict:
    """Ask the model if comments say this task is blocked. Dates are not used."""
    if not task.comments.strip():
        return _blocker(task, False, "")
    raw = llm(_blocker_prompt(task))
    blocked, reason = parse_blocker(raw)
    return _blocker(task, blocked, reason)


def parse_blocker(raw: str) -> tuple[bool, str]:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        return False, ""
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return False, ""
    blocked = bool(data.get("blocked"))
    reason = str(data.get("reason") or "").strip()
    if not blocked:
        return False, ""
    return True, reason


def friendly_nudge(tasks: list[Task], today, llm: LLM) -> str:
    """Ask the model for a warmer DM. Fall back if it drops a task key."""
    plain = format_nudge(tasks, today)
    try:
        text = llm(_nudge_prompt(plain)).strip()
    except Exception:
        return plain
    if not text or any(task.key not in text for task in tasks):
        return plain
    return text if text.endswith("\n") else text + "\n"


def run_agent() -> AgentState:
    result = build_graph().invoke({})
    return result


def _blocker_prompt(task: Task) -> str:
    return (
        "You read Jira comments and decide if the task is blocked.\n"
        "Blocked means the comments say work cannot continue.\n"
        "A past due date is not enough. Ignore dates.\n"
        'Reply with JSON only: {"blocked": true or false, "reason": "short reason or empty"}\n\n'
        f"Task: {task.key} {task.title}\n"
        f"Comments:\n{task.comments}"
    )


def _nudge_prompt(plain: str) -> str:
    return (
        "Rewrite this Slack direct message so it sounds friendly and short.\n"
        "Keep every task key exactly as written. Do not add or remove tasks.\n\n"
        f"{plain}"
    )


def _blocker(task: Task, blocked: bool, reason: str) -> dict:
    return {
        "key": task.key,
        "title": task.title,
        "assignee": task.assignee,
        "blocked": blocked,
        "reason": reason,
    }


def _task(data: dict) -> Task:
    fields = Task.__dataclass_fields__
    return Task(**{name: data.get(name, "") for name in fields})


def _is_done(task: Task) -> bool:
    return task.status.strip().lower() == "done"


def _print_blockers(blockers: list[dict]) -> None:
    flagged = [item for item in blockers if item.get("blocked")]
    print(f"Blocked in comments ({len(flagged)})")
    if not flagged:
        print("  none")
        return
    for item in flagged:
        print(f"  {item['key']}  {item['title']}  {item['reason']}")


if __name__ == "__main__":
    run_agent()
