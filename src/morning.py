"""Morning run: the LangGraph agent fetches, analyzes, and notifies."""

import sys

from agent import run_agent

DIGEST_HOUR = 9


def run_scheduled() -> None:
    """Keep this window open. Runs the full morning job at 9:00 India time."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_agent,
        CronTrigger(hour=DIGEST_HOUR, minute=0, timezone="Asia/Kolkata"),
    )
    print(
        "Morning run scheduled for 9:00 AM India time. "
        "It sends the digest, nudges, and blocker check. Leave this window open."
    )
    scheduler.start()


if __name__ == "__main__":
    if "--daily" in sys.argv:
        run_scheduled()
    else:
        run_agent()
