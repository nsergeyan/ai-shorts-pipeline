"""Render every job in data/jobs/queue/ one by one, then move it to done/ or failed/.

    python run_queue.py

Each job runs as its own main.py process, so a crash in one video never stops the rest.
"""
import glob
import os
import shutil
import subprocess
import sys

from config import BASE_DIR, DATA_DIR

JOBS_DIR = os.path.join(DATA_DIR, "jobs")
QUEUE_DIR = os.path.join(JOBS_DIR, "queue")
DONE_DIR = os.path.join(JOBS_DIR, "done")
FAILED_DIR = os.path.join(JOBS_DIR, "failed")


def main():
    for d in (QUEUE_DIR, DONE_DIR, FAILED_DIR):
        os.makedirs(d, exist_ok=True)
    jobs = sorted(glob.glob(os.path.join(QUEUE_DIR, "*.json")))
    if not jobs:
        print("Queue is empty.")
        return
    done = 0
    for i, job in enumerate(jobs, 1):
        print(f"\n===== Job {i}/{len(jobs)}: {os.path.basename(job)} =====")
        # Output is not captured, so the pipeline logs stream live as before
        code = subprocess.run([sys.executable, "-u", os.path.join(BASE_DIR, "main.py"), job], cwd=BASE_DIR).returncode
        if code == 2:
            # Gemini daily limit: every later job would fail the same way, so keep them queued for tomorrow
            print(f"===== Gemini daily limit hit, {len(jobs) - i + 1} job(s) stay queued =====")
            break
        ok = code == 0
        shutil.move(job, DONE_DIR if ok else FAILED_DIR)
        done += ok
        print(f"===== {'DONE' if ok else 'FAILED'}: {os.path.basename(job)} =====")
    print(f"\nFinished: {done}/{len(jobs)} rendered. Failed jobs are in {FAILED_DIR}")


if __name__ == "__main__":
    main()
