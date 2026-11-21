"""Install (or remove) the two launchd jobs that run the channels on their own.

    python setup_schedule.py          # install or update
    python setup_schedule.py remove   # stop the automation

daily:   02:00 every night, writes scripts and renders them (daily.py)
publish: every 30 minutes, posts renders whose time slot has arrived (publish.py)

launchd is macOS's built-in scheduler. If the Mac is asleep at 02:00, the job runs when
it wakes. Logs go to data/jobs/logs/.
"""
import os
import plistlib
import subprocess
import sys

from config import BASE_DIR, DATA_DIR

AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
LOG_DIR = os.path.join(DATA_DIR, "jobs", "logs")
DAILY_HOUR = 2
PUBLISH_EVERY = 30 * 60

JOBS = {
    "com.youtuber.daily": ("daily.py", {"StartCalendarInterval": {"Hour": DAILY_HOUR, "Minute": 0}}),
    "com.youtuber.publish": ("publish.py", {"StartInterval": PUBLISH_EVERY}),
}


def _launchctl(*args):
    subprocess.run(["launchctl", *args], check=False, capture_output=True)


def install():
    os.makedirs(AGENTS_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    for label, (script, timing) in JOBS.items():
        name = os.path.splitext(script)[0]
        plist = {
            "Label": label,
            # caffeinate -i keeps the Mac awake for the whole run, -u streams the log unbuffered
            "ProgramArguments": ["/usr/bin/caffeinate", "-i", sys.executable, "-u", os.path.join(BASE_DIR, script)],
            "WorkingDirectory": BASE_DIR,
            # launchd starts with a bare PATH, so copy this shell's one (claude, ffmpeg, npx live in it)
            "EnvironmentVariables": {"PATH": os.environ["PATH"]},
            "StandardOutPath": os.path.join(LOG_DIR, f"{name}.log"),
            "StandardErrorPath": os.path.join(LOG_DIR, f"{name}.log"),
            **timing,
        }
        path = os.path.join(AGENTS_DIR, f"{label}.plist")
        with open(path, "wb") as f:
            plistlib.dump(plist, f)
        _launchctl("bootout", domain, path)  # unload the old version, if any
        result = subprocess.run(["launchctl", "bootstrap", domain, path], capture_output=True, text=True)
        status = "installed" if result.returncode == 0 else f"FAILED: {result.stderr.strip()}"
        print(f"{label}: {status} ({path})")
    print(f"\nLogs: {LOG_DIR}")


def remove():
    domain = f"gui/{os.getuid()}"
    for label in JOBS:
        path = os.path.join(AGENTS_DIR, f"{label}.plist")
        _launchctl("bootout", domain, path)
        if os.path.exists(path):
            os.remove(path)
        print(f"{label}: removed")


if __name__ == "__main__":
    remove() if sys.argv[1:] == ["remove"] else install()
