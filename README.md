# Sentinel

Sentinel is an AI project management agent that keeps your team on schedule. It connects to Jira (Asana coming soon) and Slack, monitors tasks against deadlines and milestones, spots blockers hidden in comments, and sends timely nudges to the right people.

## Why Sentinel?

Project updates are scattered across tools, and deadlines slip when nobody notices in time. Sentinel brings the signals together and acts on them.

## Features

- Daily Slack digest of overdue, due-soon, stale and blocked tasks
- Personal nudges with rate limits and quiet hours
- LLM-based blocker detection from task comments
- Interactive Slack buttons (Done / Blocked / Need more time)
- Human approval before any change is written to Jira

## Tech stack

LangGraph, Python, FastAPI, Jira API, Slack API, SQLite

## Status

A button click is posted in the Slack channel with Approve and Reject. Only the Slack user in `SLACK_APPROVER_ID` can approve. Jira changes only after that approval. Need more time asks for a new due date and writes that date to Jira.

## Setup

1. Copy `.env.example` to `.env`.
2. Fill in your Slack bot token and Jira site, email, API token, and project key.
3. Create a virtual environment and install the packages:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

Post a hello message to Slack:

```powershell
python src\hello_slack.py
```

Print every task in the Jira project:

```powershell
python src\jira.py
```

Run the morning agent once (digest, nudges, and blocker check):

```powershell
python src\morning.py
```

Leave a window open so the same job runs every day at 9:00 AM India time. `python src\digest.py --daily` starts that same job.

```powershell
python src\morning.py --daily
```

Listen for button clicks. With Socket Mode on, Slack does not use a Request URL. Create an app-level token with the `connections:write` scope, put it in `.env` as `SLACK_APP_TOKEN`, then run:

```powershell
python src\actions.py
```
