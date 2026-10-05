"""Reverse-engineer a competitor channel's Shorts scripts.

Lists the channel's Shorts, pulls auto-captions for the most and least viewed
ones, and writes them to data/research/<handle>_transcripts.txt with an
analysis prompt on top, ready to paste into any AI.

Usage: python modules/competitor_analyzer.py <channel_handle>
"""
import json
import os
import sys
import time

from yt_dlp import YoutubeDL

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR

RESEARCH_DIR = os.path.join(DATA_DIR, "research")
TOP_N = 15
BOTTOM_N = 5
SLEEP_BETWEEN = 3  # seconds between caption fetches, keeps YouTube calm

ANALYSIS_PROMPT = (
    "These are transcripts of YouTube Shorts from one channel, labelled TOP (most viewed) "
    "or BOTTOM (least viewed). Extract the script blueprint:\n"
    "1. Hook types used in the first sentence (curiosity gap, second-person POV, bold claim, question...)\n"
    "2. Typical word count and how many words before the main reveal\n"
    "3. Structure beats, in order\n"
    "4. Ending types (question, payoff, open loop, punchline)\n"
    "5. Recurring phrases or sentence patterns\n"
    "6. MOST IMPORTANT: what TOP videos do that BOTTOM videos do not\n"
    "Answer in markdown, be concrete, quote examples."
)


def list_shorts(handle: str) -> list:
    """Return [{id, title, views}] for a channel's Shorts, metadata only, most viewed first."""
    opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/@{handle}/shorts", download=False)
    shorts = [
        {"id": e["id"], "title": e.get("title", ""), "views": e.get("view_count") or 0}
        for e in info.get("entries", [])
    ]
    return sorted(shorts, key=lambda s: s["views"], reverse=True)


def fetch_transcript(video_id: str) -> str:
    """Pull English captions (manual first, then auto) as json3 and flatten to plain text."""
    with YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/shorts/{video_id}", download=False)
        tracks = info.get("subtitles", {}).get("en") or info.get("automatic_captions", {}).get("en") or []
        json3 = next((t["url"] for t in tracks if t.get("ext") == "json3"), None)
        if not json3:
            return ""
        data = json.loads(ydl.urlopen(json3).read())
    words = [seg.get("utf8", "") for ev in data.get("events", []) for seg in ev.get("segs", [])]
    return " ".join("".join(words).split())


def analyze(handle: str):
    shorts = list_shorts(handle)
    print(f"🔍 Found {len(shorts)} Shorts on @{handle}")

    # Bottom group comes from what's left after the top, so the two never overlap on small channels
    top = shorts[:TOP_N]
    bottom = shorts[TOP_N:][-BOTTOM_N:]
    picked = [("TOP", s) for s in top] + [("BOTTOM", s) for s in bottom]

    blocks = []
    for group, s in picked:
        try:
            text = fetch_transcript(s["id"])
        except Exception as e:
            print(f"⚠️ {s['id']} caption fetch failed: {e}")
            text = ""
        print(f"{group:<6} {s['views']:>12,}  {s['title'][:50]}  ({len(text.split())} words)")
        if text:
            blocks.append(f"[{group}] views={s['views']} title={s['title']}\n{text}")
        time.sleep(SLEEP_BETWEEN)

    if not blocks:
        print("❌ No transcripts found, nothing to analyze")
        return

    os.makedirs(RESEARCH_DIR, exist_ok=True)
    out = os.path.join(RESEARCH_DIR, f"{handle}_transcripts.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"{ANALYSIS_PROMPT}\n\nChannel: @{handle}, {len(blocks)} transcripts\n\n")
        f.write("\n\n".join(blocks))
    print(f"✅ Saved to {out}, copy it into any AI or ask Claude to analyze it")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python modules/competitor_analyzer.py <channel_handle>")
    analyze(sys.argv[1].lstrip("@"))
