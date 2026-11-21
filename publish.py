"""Upload rendered videos, scheduled for their time slot. daily.py runs this after the night's
renders, and launchd every 30 minutes to retry anything that failed.

    python publish.py

A job in data/jobs/done/ first gets the next free post time of its channel (schedule.json).
It is then uploaded right away to every account the channel lists, with that time set as the
scheduled publish time, so YouTube and TikTok release it on their own and the Mac does not
need to be on then. A slot that has already passed is posted immediately. When every account
has the video, the job moves to data/jobs/published/. Each upload is saved into the job right
away, so a crash or a retry never posts the same video twice.
"""
import datetime
import glob
import json
import os
import shutil

from config import DATA_DIR
from modules import tiktok_uploader
from modules.uploader import load_schedule, mac_notify, upload_youtube

JOBS_DIR = os.path.join(DATA_DIR, "jobs")
DONE_DIR = os.path.join(JOBS_DIR, "done")
PUBLISHED_DIR = os.path.join(JOBS_DIR, "published")
FAILED_DIR = os.path.join(JOBS_DIR, "failed")
MAX_ATTEMPTS = 3  # per platform, then the job goes to failed/
# TikTok schedules 15 minutes to 10 days ahead; the margins keep clear of both ends
SCHEDULE_LEAD = datetime.timedelta(minutes=20)
SCHEDULE_MAX_AHEAD = datetime.timedelta(days=9)
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


def _publish(path, job, accounts, when=None):
    """Upload to every account that does not have it yet; when=None posts now, else schedules."""
    video = job.get("video_path")
    if not video or not os.path.exists(video):
        print(f"Video file missing for {job['title']}: {video}")
        shutil.move(path, FAILED_DIR)
        return
    job.setdefault("published", {})
    job.setdefault("publish_errors", {})
    print(f"\n{'Scheduling for ' + when.strftime('%b %d %H:%M') if when else 'Posting now'}: {job['title']}")
    for platform in PLATFORMS:
        cfg = accounts.get(platform)
        if not cfg or platform in job["published"]:
            continue
        try:
            if platform == "youtube":
                job["published"][platform] = upload_youtube(
                    video, job["title"], job.get("description") or job["title"], job.get("tags"), cfg,
                    job.get("thumbnail_path"), publish_at=when)
            else:
                # TikTok has one caption: the title, then the description's teaser and hashtags
                caption = f"{job['title']}\n\n{job['description']}" if job.get("description") else job["title"]
                tiktok_uploader.post(video, caption, cfg.get("privacy", "public"), job.get("thumbnail_path"),
                                     schedule_at=when)
                job["published"][platform] = datetime.datetime.now().isoformat(timespec="seconds")
        except Exception as e:
            job["publish_errors"][platform] = job["publish_errors"].get(platform, 0) + 1
            print(f"  {platform} upload failed ({job['publish_errors'][platform]}/{MAX_ATTEMPTS}): {e}")
            if platform == "youtube" and "invalid_grant" in str(e):
                mac_notify("Shorts: YouTube login expired",
                           f"Uploads to {job['channel']} are stuck. Run: python -m modules.uploader login youtube {job['channel']}")
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
        if not job.get("post_at"):
            continue
        slot = datetime.datetime.fromisoformat(job["post_at"])
        if slot <= now:
            _publish(path, job, schedule[job["channel"]])
        elif now + SCHEDULE_LEAD <= slot <= now + SCHEDULE_MAX_AHEAD:
            _publish(path, job, schedule[job["channel"]], when=slot)
        # Otherwise the slot is too close to schedule (next run posts it) or too far ahead for TikTok


if __name__ == "__main__":
    main()
