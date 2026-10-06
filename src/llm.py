"""One function that calls an LLM. Date rules do not live here."""

import os
import sys
import time

import requests
from dotenv import load_dotenv

from jira import ROOT


def complete(prompt: str) -> str:
    """Send one prompt and return the model's text."""
    load_dotenv(ROOT / ".env")
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    google_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if openai_key and openai_key != "your-openai-key":
        return _openai(prompt, openai_key)
    if google_key and google_key != "your-google-key":
        return _google(prompt, google_key)
    print("Add OPENAI_API_KEY or GOOGLE_API_KEY to the .env file, then run this again.")
    sys.exit(1)


def _openai(prompt: str, api_key: str) -> str:
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _google(prompt: str, api_key: str) -> str:
    models = [
        os.getenv("GOOGLE_MODEL", "gemini-2.5-flash-lite"),
        "gemini-flash-latest",
        "gemini-2.5-flash",
    ]
    last_status = 0
    last_body = ""
    for model in models:
        for attempt in range(2):
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=60,
            )
            if response.ok:
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
            last_status = response.status_code
            last_body = response.text.replace(api_key, "[key]")[:300]
            if response.status_code not in (404, 429, 500, 503):
                print(f"Google rejected the model request ({last_status}). {last_body}")
                sys.exit(1)
            time.sleep(2)
    print(f"Google rejected the model request ({last_status}). {last_body}")
    sys.exit(1)
