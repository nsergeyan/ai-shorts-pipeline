"""Nightly run: top up each channel's queue to its videos_per_day, then render the queue.

    python daily.py

launchd starts this at 02:00 (setup_schedule.py). publish.py posts the renders later.
Jobs still queued from a night that hit the Gemini limit count toward today's number.
"""
import datetime
import os

import generate_scripts
import publish
import run_queue
from modules.uploader import load_schedule


def main():
    print(f"===== Daily run {datetime.datetime.now():%Y-%m-%d %H:%M} =====")
    os.makedirs(generate_scripts.QUEUE_DIR, exist_ok=True)
    schedule = load_schedule()
    needed = {ch: max(0, schedule[ch]["videos_per_day"] - generate_scripts._queued_count(ch)) for ch in schedule}
    print(f"Scripts to write: {needed}")

    # Alternate channels so a Gemini limit halfway through still leaves each channel something
    while any(needed.values()):
        for channel in schedule:
            if needed[channel]:
                needed[channel] -= 1
                try:
                    generate_scripts.generate(channel)
                except Exception as e:
                    print(f"Script generation failed for {channel}: {e}")

    run_queue.main()
    # Gives the new renders their post times now, so the morning log shows the plan
    publish.main()


if __name__ == "__main__":
    main()
