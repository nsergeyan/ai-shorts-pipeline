"""Write video scripts with Claude Code (subscription, not the API) and save them as job files.

    python generate_scripts.py anime 2
    python generate_scripts.py sports 1
    python generate_scripts.py anime --print   # filled prompt only, to paste into a chat by hand

Each job lands in data/jobs/queue/ for run_queue.py to render.
"""
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

from config import BASE_DIR, DATA_DIR
from modules.posted_history import used_videos, format_used_videos
from modules.uploader import load_schedule

PROMPTS = {
    "anime": os.path.join(BASE_DIR, "prompts", "specifixprompt"),
    "sports": os.path.join(BASE_DIR, "prompts", "testsport.txt"),
}
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
QUEUE_DIR = os.path.join(JOBS_DIR, "queue")
CLAUDE_TIMEOUT = 20 * 60  # web search runs take several minutes
REQUIRED_KEYS = ("topic", "specific_subject", "title", "script", "youtube_queries")


TRENDING_SERIES = (
    "Pick the subject first: use web search to find which anime, series or movie is trending RIGHT NOW "
    "(a new season or episode, a movie in theaters or just out on streaming, a finale, a viral trailer "
    "or a big announcement, all from the last two weeks). Live-action shows and movies count. "
    "Only a big name a regular viewer would know, with enough clips, scenes or trailers on YouTube "
    "to cut a video from. Then find an idea about it."
)


def _pick_series(cfg, slot, used):
    """The prompt's series line: today's trending pick, or the evergreen series used least recently."""
    plan = cfg.get("series_plan")
    if not plan:
        return None
    if plan[slot % len(plan)] == "trending":
        return TRENDING_SERIES

    def last_used(series):
        # Index of the newest used video about this series, -1 if never
        hits = [i for i, post in enumerate(used)
                if any(k in post["title"].lower() for k in series["match"])]
        return hits[-1] if hits else -1

    pick = min(cfg["evergreen_series"], key=last_used)
    return f"Find a {pick['name']} idea."


def _build_prompt(channel, slot=0):
    """Fill {{DATE}}, {{USED_VIDEOS}} and {{SERIES}}. slot is the video's number in today's plan."""
    cfg = load_schedule()[channel]
    with open(PROMPTS[channel]) as f:
        prompt = f.read()
    used = used_videos(channel, cfg)
    series = _pick_series(cfg, slot, used)
    if "{{SERIES}}" in prompt and not series:
        raise ValueError(f"{PROMPTS[channel]} has {{{{SERIES}}}} but schedule.json has no series_plan for {channel}")
    prompt = prompt.replace("{{DATE}}", datetime.date.today().strftime("%B %d %Y"))
    prompt = prompt.replace("{{USED_VIDEOS}}", format_used_videos(used))
    if series:
        prompt = prompt.replace("{{SERIES}}", series)
    return prompt


def _ask_claude(prompt):
    """Run Claude Code headless and return its final answer text."""
    result = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--allowedTools", "WebSearch,WebFetch"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT,
        # Outside the repo so the project CLAUDE.md (pipeline docs) is not loaded into the writer's context
        cwd=tempfile.gettempdir(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()[:500]}")
    reply = json.loads(result.stdout)
    if reply.get("is_error"):
        raise RuntimeError(f"claude error: {reply.get('result')}")
    return reply["result"]


def _parse_job(text):
    """Pull the JSON object out of the answer, even if it is wrapped in a code fence or a sentence."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON in answer:\n{text[:500]}")
    job = json.loads(text[start:end + 1])
    missing = [k for k in REQUIRED_KEYS if not job.get(k)]
    if missing:
        raise ValueError(f"Job is missing {missing}")
    return job


def _queued_count(channel):
    count = 0
    for path in glob.glob(os.path.join(QUEUE_DIR, "*.json")):
        try:
            with open(path) as f:
                count += json.load(f).get("channel") == channel
        except Exception:
            pass
    return count


def generate(channel):
    # Each new script takes the next slot of the series plan (trending, evergreen, ...)
    slot = _queued_count(channel)
    print(f"Writing a {channel} script with Claude Code (slot {slot})...")
    job = _parse_job(_ask_claude(_build_prompt(channel, slot)))
    job.setdefault("channel", channel)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", job["title"]).strip("_")[:50]
    path = os.path.join(QUEUE_DIR, f"{datetime.datetime.now():%Y-%m-%d_%H%M%S}_{slug}.json")
    with open(path, "w") as f:
        json.dump(job, f, indent=2, ensure_ascii=False)
    print(f"Queued: {job['title']}\n  -> {path}")
    return path


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in PROMPTS:
        sys.exit(f"Usage: python generate_scripts.py [{'|'.join(PROMPTS)}] [count]")
    os.makedirs(QUEUE_DIR, exist_ok=True)
    if "--print" in sys.argv:
        print(_build_prompt(sys.argv[1], _queued_count(sys.argv[1])))
        sys.exit(0)
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    failures = 0
    for _ in range(count):
        try:
            generate(sys.argv[1])
        except Exception as e:
            failures += 1
            print(f"Script generation failed: {e}")
    sys.exit(1 if failures == count else 0)
