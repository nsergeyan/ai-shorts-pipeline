# modules/tiktok_checker.py
import requests
import json
import os
from typing import List, Set

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# In-memory cache (same idea as YouTube)
existing_tiktok_topics_cache = {}

from yt_dlp import YoutubeDL

def get_tiktok_videos(username: str, max_results: int = 50):
    try:
        url = f"https://www.tiktok.com/@{username}"

        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        entries = info.get("entries", [])
        captions = []

        for entry in entries:
            desc = entry.get("description", "")
            if desc:
                captions.append(desc.lower())
            if len(captions) >= max_results:
                break

        return captions

    except Exception as e:
        print(f"⚠️ TikTok yt-dlp error: {e}")
        return []


def load_existing_topics(cache_file: str) -> Set[str]:
    try:
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return set(line.strip().lower() for line in f if line.strip())
    except:
        pass
    return set()


def save_existing_topics(topics: List[str], cache_file: str):
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            for topic in topics:
                f.write(f"{topic}\n")
    except Exception as e:
        print(f"⚠️ Failed to save TikTok cache: {e}")


def get_existing_tiktok_topics_by_language(language: str,tiktok_channels: dict,force_refresh: bool = False) -> Set[str]:
    global existing_tiktok_topics_cache

    cache_key = f"tiktok_{language}"
    cache_file = f"tiktok_topics_cache_{language}.txt"

    if not force_refresh and cache_key in existing_tiktok_topics_cache:
        return existing_tiktok_topics_cache[cache_key]

    cached = load_existing_topics(cache_file)
    if cached and not force_refresh:
        existing_tiktok_topics_cache[cache_key] = cached
        return cached

    channel_config = tiktok_channels.get(language, {})
    username = channel_config.get("username")

    if not username:
        return set()

    captions = get_tiktok_videos(username, max_results=100)
    topics = set(captions)

    existing_tiktok_topics_cache[cache_key] = topics
    save_existing_topics(list(topics), cache_file)
    return topics


def check_duplicate_tiktok_topic(topic: str, existing_topics: Set[str]) -> bool:
    if not topic or not existing_topics:
        return False

    topic = topic.lower()
    for existing in existing_topics:
        if topic in existing or existing in topic:
            return True
    return False