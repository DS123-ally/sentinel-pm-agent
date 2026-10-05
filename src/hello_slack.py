"""Phase 0 check: post one hello message to your Slack channel."""

import os
import sys

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def main() -> None:
    load_dotenv()
    token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel = os.getenv("SLACK_CHANNEL", "#pm-agent").strip()

    if not token or token == "xoxb-your-bot-token":
        print("Add your real SLACK_BOT_TOKEN to the .env file, then run this again.")
        sys.exit(1)

    client = WebClient(token=token)
    try:
        client.chat_postMessage(
            channel=channel,
            text="Hello from the PM Agent. Phase 0 is working.",
        )
    except SlackApiError as error:
        print(f"Slack rejected the message: {error.response['error']}")
        sys.exit(1)

    print(f"Posted hello to {channel}")


if __name__ == "__main__":
    main()
