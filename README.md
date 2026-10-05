# Sentinel

Sentinel is an AI project management agent that keeps your team on schedule.
It connects to Jira (Asana coming soon) and Slack, monitors tasks against
deadlines and milestones, spots blockers hidden in comments, and sends
timely nudges to the right people.

## Why Sentinel?
Project updates are scattered across tools, and deadlines slip when nobody
notices in time. Sentinel brings the signals together and acts on them.

## Features
- Daily Slack digest of overdue, due-soon, stale and blocked tasks
- Personal nudges with rate limits and quiet hours
- LLM-based blocker detection from task comments
- Interactive Slack buttons (Done / Blocked / Need more time)
- Human approval before any change is written to Jira

## Tech Stack
LangGraph, Python, FastAPI, Jira API, Slack API, SQLite

## Status
Early development (Phase 1: reading Jira data)
