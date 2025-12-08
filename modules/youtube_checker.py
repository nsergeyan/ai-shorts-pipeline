# modules/youtube_checker.py
import requests
import os
from typing import List, Set
from urllib.parse import quote

# Get your YouTube API key from environment variables or config
YOUTUBE_API_KEY = "REDACTED_API_KEY"


def get_youtube_videos(channel_id: str = None, username: str = None, max_results: int = 50) -> List[str]:
    """
    Fetch all video titles from a YouTube channel
    Either provide channel_id OR username
    """
    if not YOUTUBE_API_KEY or YOUTUBE_API_KEY == "YOUR_YOUTUBE_API_KEY_HERE":
        print("⚠️ YouTube API key not set. Skipping duplicate check.")
        return []

    try:
        # Build search query
        if channel_id:
            search_url = f"https://www.googleapis.com/youtube/v3/search"
            params = {
                'key': YOUTUBE_API_KEY,
                'channelId': channel_id,
                'part': 'snippet',
                'maxResults': max_results,
                'type': 'video'
            }
        elif username:
            search_url = f"https://www.googleapis.com/youtube/v3/channels"
            params = {
                'key': YOUTUBE_API_KEY,
                'forUsername': username,
                'part': 'contentDetails'
            }
            # First get channel ID from username
            response = requests.get(search_url, params=params)
            if response.status_code == 200:
                items = response.json().get('items', [])
                if items:
                    channel_id = items[0]['id']
                    # Then get videos
                    search_url = f"https://www.googleapis.com/youtube/v3/search"
                    params = {
                        'key': YOUTUBE_API_KEY,
                        'channelId': channel_id,
                        'part': 'snippet',
                        'maxResults': max_results,
                        'type': 'video'
                    }
                else:
                    return []
            else:
                return []
        else:
            print("⚠️ Please provide either channel_id or username")
            return []

        # Get videos
        response = requests.get(search_url, params=params)
        if response.status_code == 200:
            videos = response.json().get('items', [])
            titles = [video['snippet']['title'].lower() for video in videos]
            return titles
        else:
            print(f"⚠️ YouTube API error: {response.status_code}")
            return []

    except Exception as e:
        print(f"⚠️ YouTube checker error: {e}")
        return []


def check_duplicate_topic(topic: str, existing_titles: List[str], threshold: float = 0.8) -> bool:
    """
    Check if a topic already exists in YouTube videos
    Returns True if duplicate found
    """
    if not existing_titles:
        return False

    topic_lower = topic.lower()

    # Exact match check
    for title in existing_titles:
        if topic_lower in title or title in topic_lower:
            return True

    # TODO: Add fuzzy matching for similar topics
    return False


def load_existing_topics(cache_file: str = "youtube_topics_cache.txt") -> Set[str]:
    """Load cached topics from file"""
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return set(line.strip().lower() for line in f.readlines())
    except:
        pass
    return set()


def save_existing_topics(topics: List[str], cache_file: str = "youtube_topics_cache.txt"):
    """Save topics to cache file"""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            for topic in topics:
                f.write(f"{topic}\n")
    except Exception as e:
        print(f"⚠️ Failed to save topics cache: {e}")