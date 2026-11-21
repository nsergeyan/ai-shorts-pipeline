"""What a channel already made, so generated scripts never repeat a topic.

Reads the live accounts (schedule.json "history_urls") with yt-dlp, titles and views, no
login, then adds our own jobs that are queued, rendered or still private. Each account is
cached for HISTORY_CACHE_HOURS and the cache is used when a fetch fails.

    python -m modules.posted_history anime    # prints the list the prompt gets
"""
import glob
import json
import os
import re
import sys
import time

from yt_dlp import YoutubeDL

from config import BASE_DIR, DATA_DIR

JOBS_DIR = os.path.join(DATA_DIR, "jobs")
# Outside JOBS_DIR, whose */*.json files are all jobs
CACHE_DIR = os.path.join(DATA_DIR, "history_cache")
HISTORY_CACHE_HOURS = 6
# Hand-kept history from before the automation (and posts the accounts no longer show)
SEED_DIR = os.path.join(BASE_DIR, "prompts", "used_videos")
MAX_POSTS = 150


def _normalize(title):
    """Compare titles without hashtags, case or punctuation, so a caption matches its job."""
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"#\S+", "", title.lower())).strip()


def _fetch(url):
    """Posts of one account, newest first: [{"title", "views"}]."""
    opts = {"quiet": True, "extract_flat": True, "skip_download": True, "playlistend": MAX_POSTS}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    posts = []
    for entry in info.get("entries") or []:
        # TikTok cuts its title with "...", the full caption is the description. YouTube has no description here
        title = (entry.get("description") or entry.get("title") or "").strip()
        if title:
            posts.append({"title": title, "views": entry.get("view_count")})
    return posts


def _cached_fetch(url):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_") + ".json")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < HISTORY_CACHE_HOURS * 3600:
        with open(cache) as f:
            return json.load(f)
    try:
        posts = _fetch(url)
        if posts:
            with open(cache, "w") as f:
                json.dump(posts, f, indent=1, ensure_ascii=False)
        return posts
    except Exception as e:
        print(f"Could not read {url}: {e}")
        if os.path.exists(cache):
            with open(cache) as f:
                return json.load(f)
        return []


def _short_views(n):
    if n is None:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M views"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K views".replace(".0K", "K")
    return f"{n} views"


def _seed(channel):
    """prompts/used_videos/<channel>.txt, oldest first, one "title, 2.4K views" per line."""
    path = os.path.join(SEED_DIR, f"{channel}.txt")
    if not os.path.exists(path):
        return []
    posts = []
    with open(path) as f:
        for line in f:
            match = re.fullmatch(r"(.*?)(?:,\s*([\d.]+)([KM]?) views)?", line.strip())
            if not match.group(1):
                continue
            views = None
            if match.group(2):
                views = int(float(match.group(2)) * {"": 1, "K": 1_000, "M": 1_000_000}[match.group(3)])
            posts.append({"title": match.group(1), "views": views})
    return posts


def used_videos(channel, cfg):
    """Titles oldest first: the seed list, live posts (with views), then our jobs not live yet.
    A title that shows up twice keeps its first place and takes the newest view count."""
    seen, history = {}, []

    def add(post):
        key = _normalize(post["title"])
        if not key:
            return
        if key in seen:
            if post["views"] is not None:
                seen[key]["views"] = post["views"]
            return
        seen[key] = post
        history.append(post)

    for post in _seed(channel):
        add(post)
    for url in cfg.get("history_urls", []):
        if "_HANDLE" in url:
            print(f"schedule.json: fill in the real handle for {url}")
            continue
        # yt-dlp lists newest first, the prompts want oldest at the top
        for post in reversed(_cached_fetch(url)):
            add(post)
    for path in sorted(glob.glob(os.path.join(JOBS_DIR, "*", "*.json")), key=os.path.basename):
        try:
            with open(path) as f:
                job = json.load(f)
        except Exception:
            continue
        if isinstance(job, dict) and job.get("channel") == channel and job.get("title"):
            add({"title": job["title"], "views": None})
    return history


def format_used_videos(posts):
    """One line per video, "title, 2.4K views", in the shape the prompts' lists use."""
    lines = []
    for post in posts:
        views = _short_views(post["views"])
        lines.append(f"{post['title']}, {views}" if views else post["title"])
    return "\n".join(lines) or "(none yet)"


if __name__ == "__main__":
    from modules.uploader import load_schedule
    name = sys.argv[1] if len(sys.argv) > 1 else "anime"
    print(format_used_videos(used_videos(name, load_schedule()[name])))
