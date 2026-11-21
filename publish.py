"""Post rendered videos at their time slot. launchd runs this every 30 minutes.

    python publish.py

A job in data/jobs/done/ first gets the next free post time of its channel (schedule.json).
Once that time has passed it goes to every account the channel lists, and when all of them
have it, the job moves to data/jobs/published/. Each upload is saved into the job right away,
so a crash or a retry never posts the same video twice.
"""
import datetime
import glob
import json
import os
import shutil

from config import DATA_DIR
from modules.uploader import load_schedule, upload_youtube, upload_tiktok

JOBS_DIR = os.path.join(DATA_DIR, "jobs")
DONE_DIR = os.path.join(JOBS_DIR, "done")
PUBLISHED_DIR = os.path.join(JOBS_DIR, "published")
FAILED_DIR = os.path.join(JOBS_DIR, "failed")
MAX_ATTEMPTS = 3  # per platform, then the job goes to failed/
PLATFORMS = ("youtube", "tiktok")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _save(path, job):
    with open(path, "w") as f:
        json.dump(job, f, indent=2, ensure_ascii=False)


def _next_free_slot(post_times, taken, now):
    """Earliest post time from now on that no other video of the channel has."""
    day = now.date()
    for _ in range(60):
        for t in sorted(post_times):
            slot = datetime.datetime.combine(day, datetime.time.fromisoformat(t))
            if slot >= now and slot.isoformat() not in taken:
                return slot.isoformat()
        day += datetime.timedelta(days=1)
    raise RuntimeError("No free slot in the next 60 days")


def _assign_slots(schedule, now):
    paths = sorted(glob.glob(os.path.join(DONE_DIR, "*.json")))
    jobs = {p: _load(p) for p in paths}
    published = [_load(p) for p in glob.glob(os.path.join(PUBLISHED_DIR, "*.json"))]
    for path, job in jobs.items():
        if job.get("post_at") or job.get("channel") not in schedule:
            continue
        taken = {j.get("post_at") for j in list(jobs.values()) + published if j.get("channel") == job["channel"]}
        job["post_at"] = _next_free_slot(schedule[job["channel"]]["post_times"], taken, now)
        _save(path, job)
        print(f"Scheduled {job['title']} for {job['post_at']}")
    return jobs


def _publish(path, job, accounts):
    video = job.get("video_path")
    if not video or not os.path.exists(video):
        print(f"Video file missing for {job['title']}: {video}")
        shutil.move(path, FAILED_DIR)
        return
    job.setdefault("published", {})
    job.setdefault("publish_errors", {})
    print(f"\nPosting: {job['title']}")
    for platform in PLATFORMS:
        cfg = accounts.get(platform)
        if not cfg or platform in job["published"]:
            continue
        try:
            if platform == "youtube":
                job["published"][platform] = upload_youtube(
                    video, job["title"], job.get("description") or job["title"], job.get("tags"), cfg,
                    job.get("thumbnail_path"))
            else:
                # TikTok has one caption: the title, then the description's teaser and hashtags
                caption = f"{job['title']}\n\n{job['description']}" if job.get("description") else job["title"]
                job["published"][platform] = upload_tiktok(video, caption, cfg, job.get("cover_ms"))
        except Exception as e:
            job["publish_errors"][platform] = job["publish_errors"].get(platform, 0) + 1
            print(f"  {platform} upload failed ({job['publish_errors'][platform]}/{MAX_ATTEMPTS}): {e}")
        _save(path, job)

    pending = [p for p in PLATFORMS if accounts.get(p) and p not in job["published"]]
    if not pending:
        shutil.move(path, PUBLISHED_DIR)
    elif all(job["publish_errors"].get(p, 0) >= MAX_ATTEMPTS for p in pending):
        print(f"  Giving up on {pending}, moved to failed/")
        shutil.move(path, FAILED_DIR)


def main():
    for d in (DONE_DIR, PUBLISHED_DIR, FAILED_DIR):
        os.makedirs(d, exist_ok=True)
    schedule = load_schedule()
    now = datetime.datetime.now()
    jobs = _assign_slots(schedule, now)
    for path, job in jobs.items():
        if job.get("post_at") and datetime.datetime.fromisoformat(job["post_at"]) <= now:
            _publish(path, job, schedule[job["channel"]])


if __name__ == "__main__":
    main()
