import itertools
import re
import requests
from urllib.parse import urlparse

try:
    import trafilatura
except ImportError:
    trafilatura = None

GOOGLE_API_KEY = "AIzaSyCljgmfWD2H2Yv2M3KvadBCW_Kdn3OSan0"
GOOGLE_CX = "f6b8ba130056b4463"
GOOGLE_API_KEY_2 = "AIzaSyDUzS3-rI4EyXnUaPdYaFnxpch4RuOV2yA"
GOOGLE_CX_2 = "960182ae1d3f5432e"

_GOOGLE_KEY_PAIRS = []

# Load from globals — only if they exist
if 'GOOGLE_API_KEY' in globals() and 'GOOGLE_CX' in globals() and GOOGLE_API_KEY and GOOGLE_CX:
    _GOOGLE_KEY_PAIRS.append({
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CX,
    })

if 'GOOGLE_API_KEY_2' in globals() and 'GOOGLE_CX_2' in globals() and GOOGLE_API_KEY_2 and GOOGLE_CX_2:
    _GOOGLE_KEY_PAIRS.append({
        "key": GOOGLE_API_KEY_2,
        "cx": GOOGLE_CX_2,
    })

# Create infinite round-robin iterator
_key_cycle = itertools.cycle(_GOOGLE_KEY_PAIRS) if _GOOGLE_KEY_PAIRS else None

def _get_next_key_pair():
    """Get next (key, cx) pair. If none configured, return None."""
    global _key_cycle
    if not _key_cycle:
        return None
    return next(_key_cycle)


# How many results per Google page and how many pages to scan
GOOGLE_RESULTS_PER_PAGE = 10
MAX_GOOGLE_PAGES = 2  # Up to 30 results total


# -------------------------------------------------------------------
# FILTER / HEURISTICS — ONLY BLOCK OBVIOUS JUNK
# -------------------------------------------------------------------

# Social / video platforms
SOCIAL_DOMAINS = (
    "youtube.com", "youtu.be",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "x.com", "twitter.com",
    "pinterest.com",
    "linkedin.com",
    "reddit.com",
)

# Blog platforms (often low-quality for facts)
BLOG_DOMAINS = (
    "medium.com",
    "tumblr.com",
    "blogspot.com",
    "wordpress.com",
)

# Domains we always block (social + blogs)
BLOCKED_DOMAINS = SOCIAL_DOMAINS + BLOG_DOMAINS

# File extensions to skip
BLOCKED_EXTENSIONS = (
    ".pdf", ".doc", ".docx",
    ".ppt", ".pptx",
    ".xls", ".xlsx",
    ".zip", ".rar", ".7z",
    ".apk", ".exe",
)

# Paths that usually aren't real articles
BAD_PATH_KEYWORDS = (
    "/tag/", "/tags/",
    "/category/",
    "/search", "?s=",
    "/login", "/signup",
    "/account",
    "/privacy", "/terms",
)

# Minimum + maximum characters for extracted articles
MIN_ARTICLE_LENGTH = 300
MAX_ARTICLE_CHARS = 7000


# -------------------------------------------------------------------
# HELPER: CHECK IF PAGE IS WORTH SCRAPING
# -------------------------------------------------------------------

def _looks_like_useful_page(url: str, title: str, snippet: str) -> bool:
    """
    Skip obviously useless pages — nothing more.
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    # Block known junk domains
    if any(bad in domain for bad in BLOCKED_DOMAINS):
        return False

    # Skip file downloads
    if any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS):
        return False

    # Skip non-article paths
    if any(bad in path for bad in BAD_PATH_KEYWORDS):
        return False

    # Skip empty snippets
    if len(snippet.split()) < 5:
        return False

    return True


# -------------------------------------------------------------------
# HELPER: CALL GOOGLE API — WITH KEY ROTATION + 429 RETRY
# -------------------------------------------------------------------

def _google_search_page(query: str, start: int, num: int = GOOGLE_RESULTS_PER_PAGE, lang: str = "en"):
    """
    Fetch one page of Google Custom Search results — with key rotation + auto-retry on 429.
    """
    search_url = "https://www.googleapis.com/customsearch/v1"

    creds = _get_next_key_pair()
    if not creds:
        print("⚠️ No Google API keys configured!")
        return []

    print(f"   🔑 Using key: {creds['key'][:8]}...")

    params = {
        "key": creds["key"],
        "cx": creds["cx"],
        "q": query,
        "num": num,
        "start": start,
    }

    if lang == "ru":
        params["lr"] = "lang_ru"
    else:
        params["lr"] = "lang_en"

    try:
        r = requests.get(search_url, params=params, timeout=10)

        # AUTO-RETRY ON 429
        if r.status_code == 429:
            print(f"   ⚠️ Quota exhausted for key {creds['key'][:8]} — rotating...")
            creds = _get_next_key_pair()
            if creds:
                params["key"] = creds["key"]
                params["cx"] = creds["cx"]
                print(f"   🔄 Retrying with key: {creds['key'][:8]}...")
                r = requests.get(search_url, params=params, timeout=10)
            else:
                print("   ❌ All keys exhausted.")
                return []

        r.raise_for_status()
        data = r.json()

    except Exception as e:
        print(f"⚠️ Google search failed (start={start}): {e}")
        return []

    return data.get("items", []) or []


# -------------------------------------------------------------------
# HELPER: SANITIZE TEXT FOR TTS (REMOVE CHINESE/EMOJI/GARBAGE)
# -------------------------------------------------------------------

def _sanitize_for_tts(text: str, lang: str) -> str:
    """
    Strip any characters that could break TTS or cause weird output.
    Keep only safe chars for target language.
    """
    if not text:
        return text

    if lang == "ru":
        pattern = r'[^А-Яа-яЁё0-9\s\.,!?;:\-\"\'()—–]+'
    else:
        pattern = r'[^A-Za-z0-9\s\.,!?;:\-\"\'()]+'

    clean = re.sub(pattern, ' ', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


# -------------------------------------------------------------------
# MAIN FUNCTION — RAW. SIMPLE. POWERFUL.
# -------------------------------------------------------------------

def get_deep_research(query: str, lang: str = "en", max_results: int = 3) -> str:
    """
    NO BULLSHIT RESEARCH ENGINE.
    - Uses your RAW query exactly as typed.
    - Accepts 'lang' parameter: "en" or "ru"
    - Only skips obviously bad pages (social/blog/filetypes).
    - Sanitizes ONLY to protect TTS from garbage chars.
    """
    print(f"🔍 Deep Researching (Google API): '{query}'...")

    if not _GOOGLE_KEY_PAIRS:
        return "Error: No Google API keys configured."

    print(f"   🌐 Language: {lang.upper()}")

    combined_context = ""
    valid_count = 0
    seen_urls: set[str] = set()
    processed_count = 0

    for page_idx in range(MAX_GOOGLE_PAGES):
        if valid_count >= max_results:
            break

        start_index = page_idx * GOOGLE_RESULTS_PER_PAGE + 1
        items = _google_search_page(query, start=start_index, lang=lang)

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

            if not _looks_like_useful_page(link, title, snippet):
                if processed_count <= 10:
                    parsed = urlparse(link)
                    domain = parsed.netloc.lower()
                    path = parsed.path.lower()

                    skip_reason = None
                    if any(bad in domain for bad in BLOCKED_DOMAINS):
                        skip_reason = f"(blocked domain): {domain}"
                    elif any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS):
                        skip_reason = f"(file type): {path}"
                    elif any(bad in path for bad in BAD_PATH_KEYWORDS):
                        skip_reason = f"(non-article path): {path}"
                    elif len(snippet.split()) < 5:
                        skip_reason = "(too little snippet text)"

                    if skip_reason:
                        print(f"      ❌ Skipping {skip_reason}")
                continue

            print(f"   👉 Found: {title}...")

            try:
                downloaded = trafilatura.fetch_url(link)
                text = None
                if downloaded:
                    raw_text = trafilatura.extract(
                        downloaded,
                        include_comments=False,
                        include_tables=False,
                        include_links=False,
                        favor_recall=True,
                        deduplicate=True,
                    )
                    if raw_text:
                        text = _sanitize_for_tts(raw_text, lang)

                if text and len(text) >= MIN_ARTICLE_LENGTH:
                    original_len = len(text)
                    if original_len > MAX_ARTICLE_CHARS:
                        text = text[:MAX_ARTICLE_CHARS]
                        print(f"      ✅ Trimmed to {len(text)} chars (from {original_len})")
                    else:
                        print(f"      ✅ Full article: {len(text)} chars")

                    combined_context += (
                        f"\nSOURCE: {title}\nURL: {link}\nCONTENT:\n{text}\n"
                    )
                    valid_count += 1
                    continue

                else:
                    print("      ⚠️ Text too short, falling back to snippet")

            except Exception as e:
                if processed_count <= 10:
                    print(f"      ⚠️ Scrape failed: {e}")

            if snippet:
                snippet_clean = _sanitize_for_tts(snippet, lang)
                combined_context += (
                    f"\nSOURCE: {title}\nURL: {link}\nSNIPPET:\n{snippet_clean}\n"
                )
                valid_count += 1

    if valid_count == 0:
        print("   ℹ️  No quality sources found.")

    return combined_context.strip() if combined_context.strip() else "No relevant data found."