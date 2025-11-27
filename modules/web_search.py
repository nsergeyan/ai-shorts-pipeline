# modules/web_search.py

import requests
import trafilatura
import re
from urllib.parse import urlparse

# -------------------------------------------------------------------
# GOOGLE SEARCH CONFIG
# -------------------------------------------------------------------

# You can keep these hard-coded or move them to environment variables
GOOGLE_API_KEY = "AIzaSyCljgmfWD2H2Yv2M3KvadBCW_Kdn3OSan0"
GOOGLE_CX = "f6b8ba130056b4463"

# How many results per Google page and how many pages to scan
GOOGLE_RESULTS_PER_PAGE = 10
MAX_GOOGLE_PAGES = 5  # Up to 30 results total (10 * 3)

# -------------------------------------------------------------------
# FILTER / HEURISTICS
# -------------------------------------------------------------------

# Social / video / low-value for scraping
SOCIAL_DOMAINS = (
    "youtube.com", "youtu.be",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "x.com", "twitter.com",
    "pinterest.com",
    "linkedin.com"
)

# Blog / fanfic / "noname essay" type sites you said you don't want
BLOG_DOMAINS = (
    "medium.com",
    "tumblr.com",
    "blogspot.com",
    "wordpress.com",
)

# Domains we always block (social + blogs)
BLOCKED_DOMAINS = SOCIAL_DOMAINS + BLOG_DOMAINS

BLOCKED_EXTENSIONS = (
    ".pdf", ".doc", ".docx",
    ".ppt", ".pptx",
    ".xls", ".xlsx",
    ".zip", ".rar", ".7z",
    ".apk", ".exe",
)

BAD_PATH_KEYWORDS = (
    "/tag/", "/tags/",
    "/category/",
    "/search", "?s=",
    "/login", "/signup",
    "/account",
    "/privacy", "/terms",
)

# Minimum + maximum characters for extracted articles
MIN_ARTICLE_LENGTH = 400  # lowered a bit so short wiki pages still count
MAX_ARTICLE_CHARS = 6000  # HARD cap per source for your prompt

# Very generic words to ignore when extracting main keywords
GENERIC_QUERY_WORDS = {
    "interesting", "interest", "facts", "fact",
    "about", "from", "mind", "blowing", "unknown",
    "shocking", "crazy", "top", "best", "worst",
    "things", "thing", "you", "need", "know",
    "history", "story", "moment", "moments",
    "short", "shorts", "video", "script",
    "the", "and", "or", "for", "with", "vs",
    "of", "in", "on", "to", "a", "an",
}


# -------------------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------------------

def _extract_main_keywords(query: str) -> set[str]:
    """
    Extract non-generic keywords from the query.
    Example:
        "Interesting facts about Alastor from hazbin hotel mind blowing unknown facts"
        -> {"alastor", "hazbin", "hotel"}
    """
    words = re.findall(r"[a-zA-Z0-9]+", query.lower())
    return {
        w for w in words
        if len(w) > 2 and w not in GENERIC_QUERY_WORDS
    }


def _get_primary_keyword(main_keywords: set[str]) -> str | None:
    """
    Choose a primary keyword (usually the name) from extracted keywords.
    Simple rule: longest word that survived the generic filter.
    Example: {"alastor", "hazbin", "hotel"} -> "alastor"
    """
    if not main_keywords:
        return None
    return max(main_keywords, key=len)


def _looks_like_useful_page(url: str, title: str, snippet: str) -> bool:
    """
    Quick heuristic to filter out useless pages before scraping.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    # --- EXTRA FILTERS (NO FANON / NON-CANON WIKIS) ---
    # Block any "Fanon Wiki" style pages
    if "fanon wiki" in (title or "").lower():
        return False

    # Block the specific "Journey to the Light" wiki (non-canon)
    if "journey-to-the-light" in domain or "journey_to_the_light" in domain:
        return False
    if "journey-to-the-light" in path or "journey_to_the_light" in path:
        return False
    # --------------------------------------------------

    # Block known junk / social / non-article domains
    if any(bad in domain for bad in BLOCKED_DOMAINS):
        return False

    # Skip obviously non-HTML resources
    if any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS):
        return False

    # Skip search/tag/login/privacy/etc pages
    if any(bad in path for bad in BAD_PATH_KEYWORDS):
        return False

    # If Google snippet is basically empty, it's usually junk
    if len(snippet.split()) < 5:
        return False

    return True


def _google_search_page(query: str, start: int, num: int = GOOGLE_RESULTS_PER_PAGE):
    """
    Call Google Custom Search for a single page.
    """
    search_url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX,
        "q": query,
        "num": num,
        "start": start,
        "lr": "lang_en",
    }

    try:
        r = requests.get(search_url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"⚠️ Google search failed (start={start}): {e}")
        return []

    return data.get("items", []) or []


# -------------------------------------------------------------------
# MAIN FUNCTION (what your other code imports)
# -------------------------------------------------------------------

def get_deep_research(query: str, max_results: int = 3) -> str:
    """
    Run Google Custom Search and scrape up to `max_results` *useful* pages.

    Improvements vs your old version:
    - Cleans the query (removes 'interesting facts', etc.) before searching.
    - Searches multiple pages (up to MAX_GOOGLE_PAGES) until it finds enough.
    - Filters out social/video + blog platforms (Medium, Tumblr...).
    - Requires the primary name (e.g. 'alastor') in title/snippet and body.
    - Trims each article to MAX_ARTICLE_CHARS.
    """
    print(f"🔍 Deep Researching (Google API): '{query}'...")

    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return "Error: Google API keys not set."

    # Extract keywords and primary keyword from the noisy query
    main_keywords = _extract_main_keywords(query)
    primary_kw = _get_primary_keyword(main_keywords)

    if main_keywords:
        print(f"   🔑 Main keywords for relevance: {', '.join(sorted(main_keywords))}")
    if primary_kw:
        print(f"   ⭐ Primary name to match: {primary_kw}")

    # Build a cleaner query for Google (helps avoid weird results)
    if main_keywords:
        clean_query = " ".join(sorted(main_keywords))
    else:
        clean_query = query

    combined_context = ""
    valid_count = 0
    seen_urls: set[str] = set()
    processed_count = 0

    # Iterate over multiple Google pages
    for page_idx in range(MAX_GOOGLE_PAGES):
        if valid_count >= max_results:
            break

        start_index = page_idx * GOOGLE_RESULTS_PER_PAGE + 1
        items = _google_search_page(clean_query, start=start_index)

        # No more results from Google
        if not items:
            break

        for item in items:
            if valid_count >= max_results:
                break

            title = (item.get("title") or "").strip()
            link = (item.get("link") or "").strip()
            snippet = (item.get("snippet") or "").strip()

            if not link or link in seen_urls:
                continue

            seen_urls.add(link)
            processed_count += 1

            # First, check if this looks like a usable article
            if not _looks_like_useful_page(link, title, snippet):
                # Only show skip reason for first few items to avoid spam
                if processed_count <= 10:
                    parsed = urlparse(link)
                    domain = parsed.netloc.lower()
                    path = parsed.path.lower()

                    # Determine reason for skipping
                    if any(bad in domain for bad in BLOCKED_DOMAINS):
                        print(f"      ❌ Skipping (blocked domain): {domain}")
                    elif any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS):
                        print(f"      ❌ Skipping (file type): {path}")
                    elif any(bad in path for bad in BAD_PATH_KEYWORDS):
                        print(f"      ❌ Skipping (non-article path): {path}")
                    elif len(snippet.split()) < 5:
                        print("      ❌ Skipping (too little snippet text)")
                continue

            # Require the primary keyword (e.g. "alastor") in title+snippet for strong relevance
            if primary_kw:
                haystack = (title + " " + snippet).lower()
                if primary_kw not in haystack:
                    if processed_count <= 10:  # Limit verbose output
                        print(
                            f"      ❌ Skipping (title/snippet doesn't mention main name "
                            f"'{primary_kw}'): {title[:50]}..."
                        )
                    continue

            print(f"   👉 Found: {title}...")

            # Try to scrape article text
            try:
                downloaded = trafilatura.fetch_url(link)
                text = None
                if downloaded:
                    text = trafilatura.extract(
                        downloaded,
                        include_comments=False,
                        include_tables=False,
                        include_links=False,
                        favor_recall=True,
                        deduplicate=True,
                    )

                if text and len(text) >= MIN_ARTICLE_LENGTH:
                    body_lower = text.lower()

                    # Ensure article body also mentions the primary keyword
                    if primary_kw and primary_kw not in body_lower:
                        if processed_count <= 10:  # Limit verbose output
                            print(
                                "      ❌ Skipping article "
                                f"(content doesn't mention main name '{primary_kw}')."
                            )
                        continue

                    original_len = len(text)
                    if original_len > MAX_ARTICLE_CHARS:
                        text = text[:MAX_ARTICLE_CHARS]
                        print(
                            f"      ✅ Read full article (trimmed from {original_len} "
                            f"to {len(text)} chars)."
                        )
                    else:
                        print(f"      ✅ Read full article ({len(text)} chars).")

                    combined_context += (
                        f"\nSOURCE: {title}\nURL: {link}\nFULL INFO: {text}\n"
                    )
                    valid_count += 1
                    continue

                else:
                    print("      ⚠️ Extracted text too short or empty, using snippet.")

            except Exception as e:
                if processed_count <= 10:  # Limit verbose output
                    print(f"      ⚠️ Failed to extract content: {e}")

            # Fallback to snippet (still checked for primary_kw earlier)
            if snippet:
                combined_context += (
                    f"\nSOURCE: {title}\nURL: {link}\nSUMMARY: {snippet}\n"
                )
                valid_count += 1

    if valid_count == 0:
        print("   ℹ️  No relevant articles found after filtering.")

    return combined_context if combined_context else "No data found."