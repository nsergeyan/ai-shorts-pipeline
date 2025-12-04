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
# Load from globals
if 'GOOGLE_API_KEY' in globals() and 'GOOGLE_CX' in globals() and GOOGLE_API_KEY and GOOGLE_CX:
    _GOOGLE_KEY_PAIRS.append({"key": GOOGLE_API_KEY, "cx": GOOGLE_CX})

if 'GOOGLE_API_KEY_2' in globals() and 'GOOGLE_CX_2' in globals() and GOOGLE_API_KEY_2 and GOOGLE_CX_2:
    _GOOGLE_KEY_PAIRS.append({"key": GOOGLE_API_KEY_2, "cx": GOOGLE_CX_2})

_key_cycle = itertools.cycle(_GOOGLE_KEY_PAIRS) if _GOOGLE_KEY_PAIRS else None


def _get_next_key_pair():
    global _key_cycle
    if not _key_cycle: return None
    return next(_key_cycle)


GOOGLE_RESULTS_PER_PAGE = 10
MAX_GOOGLE_PAGES = 2

# -------------------------------------------------------------------
# DOMAIN BLOCKING
# -------------------------------------------------------------------

SOCIAL_DOMAINS = ("youtube.com", "youtu.be", "instagram.com", "facebook.com", "tiktok.com", "x.com", "twitter.com",
                  "pinterest.com", "linkedin.com", "reddit.com")
BLOG_DOMAINS = ("medium.com", "tumblr.com", "blogspot.com", "wordpress.com")
BLOCKED_DOMAINS = SOCIAL_DOMAINS + BLOG_DOMAINS

BLOCKED_EXTENSIONS = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".rar", ".7z", ".apk", ".exe")
BAD_PATH_KEYWORDS = ("/tag/", "/tags/", "/category/", "/search", "?s=", "/login", "/signup", "/account", "/privacy",
                     "/terms")

MIN_ARTICLE_LENGTH = 400
MAX_ARTICLE_CHARS = 8000

# -------------------------------------------------------------------
# NEW: RELEVANCE HEURISTICS
# -------------------------------------------------------------------

# Words that don't help us distinguish "Kratos" from "Striker"
GENERIC_STOP_WORDS = {
    "wiki", "fandom", "lore", "character", "page", "the", "and", "is", "in", "to", "of", "it",
    "wikia", "article", "search", "home", "about", "community", "app", "boss"  # 'Boss' is tricky, handled below
}


def _get_query_keywords(query: str) -> set[str]:
    """Extract important unique words from the query to act as fingerprints."""
    # clean and split
    words = re.findall(r'\w+', query.lower())
    # filter out generic stop words, but keep distinct nouns
    keywords = {w for w in words if len(w) > 2 and w not in GENERIC_STOP_WORDS}

    # EDGE CASE: If query is "Helluva Boss", we removed "boss", put it back if it's a specific title
    if "boss" in query.lower() and "helluva" in query.lower():
        keywords.add("boss")

    return keywords


def _calculate_relevance_score(text: str, title: str, keywords: set[str]) -> float:
    """
    Returns a score (0.0 to 1.0) representing how relevant the text is to the keywords.
    """
    if not keywords:
        return 1.0  # No keywords to check against

    text_lower = text.lower()
    title_lower = title.lower()

    hits = 0
    for kw in keywords:
        # Title matches are worth more
        if kw in title_lower:
            hits += 2
        # Body matches
        elif kw in text_lower:
            hits += 1

    # Ideal score: Every keyword appears at least once.
    # We accept if we found at least ~50% of the significance.
    max_possible = len(keywords) * 1.5  # slightly lenient
    score = min(hits / max_possible, 1.0)

    return score


# -------------------------------------------------------------------
# SEARCH & SCRAPE LOGIC
# -------------------------------------------------------------------

def _looks_like_useful_page(url: str, title: str, snippet: str) -> bool:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    if any(bad in domain for bad in BLOCKED_DOMAINS): return False
    if any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS): return False
    if any(bad in path for bad in BAD_PATH_KEYWORDS): return False
    if len(snippet.split()) < 5: return False
    return True


def _google_search_page(query: str, start: int, num: int = GOOGLE_RESULTS_PER_PAGE, lang: str = "en"):
    search_url = "https://www.googleapis.com/customsearch/v1"
    creds = _get_next_key_pair()
    if not creds: return []

    print(f"   🔑 Using key: {creds['key'][:8]}...")
    params = {"key": creds["key"], "cx": creds["cx"], "q": query, "num": num, "start": start}
    if lang == "ru":
        params["lr"] = "lang_ru"
    else:
        params["lr"] = "lang_en"

    try:
        r = requests.get(search_url, params=params, timeout=10)
        if r.status_code == 429:
            print(f"   ⚠️ Quota exhausted, rotating...")
            creds = _get_next_key_pair()
            if creds:
                params["key"] = creds["key"]
                params["cx"] = creds["cx"]
                r = requests.get(search_url, params=params, timeout=10)
            else:
                return []
        r.raise_for_status()
        return r.json().get("items", []) or []
    except Exception as e:
        print(f"⚠️ Google search error: {e}")
        return []


def _sanitize_for_tts(text: str, lang: str) -> str:
    if not text: return text
    pattern = r'[^А-Яа-яЁё0-9\s\.,!?;:\-\"\'()—–]+' if lang == "ru" else r'[^A-Za-z0-9\s\.,!?;:\-\"\'()]+'
    clean = re.sub(pattern, ' ', text)
    return re.sub(r'\s+', ' ', clean).strip()


def get_deep_research(query: str, lang: str = "en", max_results: int = 3) -> str:
    print(f"🔍 Deep Researching: '{query}'...")

    if not _GOOGLE_KEY_PAIRS:
        return "Error: No Google API keys configured."

    # 1. EXTRACT KEYWORDS FOR VALIDATION
    query_keywords = _get_query_keywords(query)
    print(f"   🎯 Target Keywords: {query_keywords}")

    combined_context = ""
    valid_count = 0
    seen_urls = set()
    processed_count = 0

    for page_idx in range(MAX_GOOGLE_PAGES):
        if valid_count >= max_results: break

        items = _google_search_page(query, start=(page_idx * GOOGLE_RESULTS_PER_PAGE) + 1, lang=lang)
        if not items: break

        for item in items:
            if valid_count >= max_results: break

            title = (item.get("title") or "").strip()
            link = (item.get("link") or "").strip()
            snippet = (item.get("snippet") or "").strip()

            if not link or link in seen_urls: continue
            seen_urls.add(link)
            processed_count += 1

            if not _looks_like_useful_page(link, title, snippet):
                continue

            # 2. PRE-FETCH RELEVANCE CHECK (Title Match)
            # If title is "Kratos" and keywords are "Striker", score will be low.
            pre_score = _calculate_relevance_score(snippet, title, query_keywords)
            if pre_score < 0.3:  # Strict filter on snippet/title
                print(f"      ❌ Skipping irrelevant result: {title} (Score: {pre_score:.2f})")
                continue

            print(f"   👉 Checking: {title}...")

            try:
                downloaded = trafilatura.fetch_url(link)
                text = None
                if downloaded:
                    text = trafilatura.extract(
                        downloaded,
                        include_comments=False,
                        include_tables=False,
                        include_links=False,
                        favor_recall=False,  # Changed to False to reduce navigation junk
                        deduplicate=True,
                    )

                if text:
                    # 3. CONTENT RELEVANCE CHECK
                    # Does the FULL text actually mention our keywords?
                    clean_text = _sanitize_for_tts(text, lang)
                    content_score = _calculate_relevance_score(clean_text[:3000], title, query_keywords)

                    if content_score < 0.5:
                        print(
                            f"      ⚠️ Scraped text irrelevant (Score: {content_score:.2f}). Likely a navigation/sidebar error.")
                        continue

                    # Truncate
                    if len(clean_text) > MAX_ARTICLE_CHARS:
                        clean_text = clean_text[:MAX_ARTICLE_CHARS]
                        print(f"      ✅ Scraped & Trimmed: {len(clean_text)} chars")
                    else:
                        print(f"      ✅ Scraped Full: {len(clean_text)} chars")

                    combined_context += f"\nSOURCE: {title}\nURL: {link}\nCONTENT:\n{clean_text}\n"
                    valid_count += 1
                else:
                    # Fallback to snippet if it passed relevance
                    print("      ⚠️ No text extracted, using snippet")
                    clean_snippet = _sanitize_for_tts(snippet, lang)
                    combined_context += f"\nSOURCE: {title}\nURL: {link}\nSNIPPET:\n{clean_snippet}\n"
                    valid_count += 1

            except Exception as e:
                print(f"      ⚠️ Error: {e}")

    if valid_count == 0:
        print("   ℹ️  No relevant sources found.")

    return combined_context.strip() or "No relevant data found."