"""Morning run: one channel digest, then personal nudges."""

from digest import send_today
from nudge import send_nudges


if __name__ == "__main__":
    send_today()
    send_nudges()
