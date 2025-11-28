import requests
import trafilatura
from urllib.parse import urlparse

# --- GOOGLE CONFIG ---
GOOGLE_API_KEY = "AIzaSyCljgmfWD2H2Yv2M3KvadBCW_Kdn3OSan0"
GOOGLE_CX = "f6b8ba130056b4463"

BLOCKED_DOMAINS = [
    "reddit.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "tiktok.com", "pinterest.com"
]


def _is_useful_link(url, title):
    """Filters out bad domains and non-canon wikis."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    title = (title or "").lower()

    if any(x in domain for x in BLOCKED_DOMAINS): return False
    if "fanon" in title or "fanon" in domain: return False
    if "journey-to-the-light" in domain or "journey-to-the-light" in path: return False

    return True


def get_deep_research(query: str, max_results: int = 3) -> str:
    print(f"🔍 Deep Researching (Google API): '{query}'...")

    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": GOOGLE_API_KEY, "cx": GOOGLE_CX, "q": query, "num": 8}

    try:
        data = requests.get(url, params=params).json()
    except Exception as e:
        print(f"⚠️ Google Search Error: {e}")
        return "No context available."

    items = data.get("items", [])
    if not items: return "No results found."

    combined_text = ""
    count = 0

    for item in items:
        if count >= max_results: break

        link = item.get("link")
        title = item.get("title")
        snippet = item.get("snippet", "")

        if not _is_useful_link(link, title):
            print(f"      ❌ Skipping: {title}")
            continue

        print(f"   👉 Reading: {title}...")
        try:
            downloaded = trafilatura.fetch_url(link)
            if downloaded:
                text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
                if text and len(text) > 300:
                    # Limit to 2500 chars per source to keep prompt focused
                    combined_text += f"\nSOURCE: {title}\nINFO: {text[:2500]}\n"
                    count += 1
                else:
                    # Fallback to snippet if scraping fails
                    combined_text += f"\nSOURCE: {title}\nINFO: {snippet}\n"
                    count += 1
        except:
            continue

    return combined_text if combined_text else "No deep info found."