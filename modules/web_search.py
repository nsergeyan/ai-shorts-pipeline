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
# Your existing key setup
_GOOGLE_KEY_PAIRS = []
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
MAX_ARTICLE_CHARS = 8000

# -------------------------------------------------------------------
# UNIVERSAL BLOCKING SYSTEM
# -------------------------------------------------------------------

SOCIAL_DOMAINS = ("youtube.com", "youtu.be", "instagram.com", "facebook.com", "tiktok.com", "x.com", "twitter.com",
                  "pinterest.com", "linkedin.com", "reddit.com")
BLOG_DOMAINS = ("medium.com", "tumblr.com", "blogspot.com", "wordpress.com")
BLOCKED_DOMAINS = SOCIAL_DOMAINS + BLOG_DOMAINS
GAME_WIKI_DOMAINS = ("fandom.com", "gamepedia.com", "wikia.org")

BLOCKED_EXTENSIONS = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".rar", ".7z", ".apk", ".exe")
BAD_PATH_KEYWORDS = ("/tag/", "/tags/", "/category/", "/search", "?s=", "/login", "/signup", "/account", "/privacy",
                     "/terms")

# Universal contamination blockers (works for any universe)
UNIVERSAL_CONTAMINATION_TERMS = [
    # Comics/Marvel contamination
    "marvel", "agents of shield", "mcu", "bullseye", "poindexter", "comics", "comic",
    "superhero", "avengers", "x-men",
    # Sci-fi contamination
    "star wars", "star trek", "warhammer", "dungeons and dragons", "d&d",
    "world of warcraft", "wow", "mechwarrior",
    # Other games contamination
    "league of legends", "overwatch", "fortnite", "minecraft", "roblox"
]


# -------------------------------------------------------------------
# SMART UNIVERSE DETECTION & ADAPTATION
# -------------------------------------------------------------------

def _extract_core_query_terms(query: str) -> list:
    """Extract the essential terms that define what we're looking for"""
    # Remove generic terms
    generic_terms = {"wiki", "lore", "universe", "fandom", "page", "the", "and", "is", "in", "to", "of", "it"}

    # Extract words
    words = re.findall(r'\w+', query.lower())
    core_terms = [w for w in words if len(w) > 2 and w not in generic_terms]

    return core_terms


def _detect_primary_universe(query: str) -> str:
    """Smart universe detection based on query context"""
    query_lower = query.lower()

    # Look for universe indicators in the query
    universe_indicators = {
        "stalker": ["stalker", "s.t.a.l.k.e.r", "zone", "anomaly", "pripyat"],
        "fallout": ["fallout", "vault", "vault-tec", "nuka"],
        "scp": ["scp", "foundation", "anomalous", "containment"],
        "metro": ["metro", "station", "reich", "hansa"]
    }

    # Score each universe
    universe_scores = {}
    for universe, indicators in universe_indicators.items():
        score = sum(1 for indicator in indicators if indicator in query_lower)
        if score > 0:
            universe_scores[universe] = score

    # Return highest scoring universe, or "general" if none
    if universe_scores:
        return max(universe_scores, key=universe_scores.get)

    return "general"


def _is_content_relevant(text: str, title: str, query_terms: list, primary_universe: str) -> tuple[bool, float]:
    """
    Smart relevance detection that works for any universe
    Returns (is_relevant, confidence_score)
    """
    if not query_terms:
        return True, 1.0

    text_lower = text.lower()
    title_lower = title.lower()

    # Check for contamination first
    contamination_score = 0
    for contaminant in UNIVERSAL_CONTAMINATION_TERMS:
        if contaminant in text_lower:
            # But allow if it's actually about our primary universe
            universe_indicators = {
                "stalker": ["stalker", "zone", "anomaly", "artifact"],
                "fallout": ["fallout", "vault", "nuka", "wasteland"],
                "scp": ["scp", "foundation", "containment"],
                "metro": ["metro", "station", "reich"]
            }

            # If we have a primary universe, check if content relates to it
            if primary_universe in universe_indicators:
                universe_terms = universe_indicators[primary_universe]
                if not any(term in text_lower for term in universe_terms):
                    contamination_score += 1
            else:
                contamination_score += 1

    # If heavily contaminated, reject
    if contamination_score > 2:
        return False, 0.0

    # Calculate relevance score based on query terms
    hits = 0
    total_terms = len(query_terms)

    for term in query_terms:
        # Title matches worth more
        if term in title_lower:
            hits += 2
        elif term in text_lower:
            hits += 1

    # Normalize score
    max_possible = total_terms * 2  # Title weight
    relevance_score = min(hits / max_possible, 1.0) if max_possible > 0 else 1.0

    # Apply contamination penalty
    final_score = max(relevance_score - (contamination_score * 0.1), 0.0)

    # Minimum threshold for relevance
    is_relevant = final_score >= 0.15

    return is_relevant, final_score


def _looks_like_quality_source(url: str, title: str, snippet: str) -> bool:
    """Universal quality source detection"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    # Basic blocking
    if any(bad in domain for bad in BLOCKED_DOMAINS): return False
    if any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS): return False
    if any(bad in path for bad in BAD_PATH_KEYWORDS): return False
    if len(snippet.split()) < 5: return False

    # Prefer quality sources
    quality_indicators = GAME_WIKI_DOMAINS + ("wikipedia.org",)
    if any(quality_domain in domain for quality_domain in quality_indicators):
        return True

    # Accept other sources if they seem legitimate
    return True


# -------------------------------------------------------------------
# UNIVERSAL SEARCH & SCRAPE ENGINE
# -------------------------------------------------------------------

def _google_search_page(query: str, start: int, num: int = GOOGLE_RESULTS_PER_PAGE, lang: str = "en"):
    search_url = "https://www.googleapis.com/customsearch/v1"
    creds = _get_next_key_pair()
    if not creds: return []

    print(f"   🔑 Using key: {creds['key'][:8]}...")

    # Smart query construction
    if "fandom" in query.lower():
        search_query = query  # Already specific
    else:
        search_query = f"site:fandom.com OR site:wikipedia.org {query}"

    params = {"key": creds["key"], "cx": creds["cx"], "q": search_query, "num": num, "start": start}
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

    # Extract core query terms and detect universe
    query_terms = _extract_core_query_terms(query)
    primary_universe = _detect_primary_universe(query)

    print(f"   🎯 Core Terms: {query_terms}")
    print(f"   🎮 Primary Universe: {primary_universe}")

    combined_context = ""
    valid_count = 0
    seen_urls = set()

    # Try multiple search strategies
    search_queries = [
        f"site:fandom.com {query}",  # Fandom first
        query,  # General search
        f"{query} lore wiki"  # Alternative format
    ]

    for search_query in search_queries:
        if valid_count >= max_results: break

        for page_idx in range(MAX_GOOGLE_PAGES):
            if valid_count >= max_results: break

            items = _google_search_page(search_query, start=(page_idx * GOOGLE_RESULTS_PER_PAGE) + 1, lang=lang)
            if not items:
                if search_query != search_queries[-1]:  # Not the last strategy
                    continue
                else:
                    break

            for item in items:
                if valid_count >= max_results: break

                title = (item.get("title") or "").strip()
                link = (item.get("link") or "").strip()
                snippet = (item.get("snippet") or "").strip()

                if not link or link in seen_urls: continue
                seen_urls.add(link)

                # Quality source check
                if not _looks_like_quality_source(link, title, snippet):
                    print(f"      ❌ Low quality source: {title}")
                    continue

                # Smart relevance check
                is_relevant, score = _is_content_relevant(snippet, title, query_terms, primary_universe)

                # Special handling for exact matches
                exact_match = any(term.lower() in title.lower() for term in query_terms)

                if exact_match and score >= 0.1:
                    print(f"   👉 Checking EXACT MATCH: {title} (Score: {score:.2f})...")
                elif is_relevant:
                    print(f"   👉 Checking: {title} (Score: {score:.2f})...")
                else:
                    print(f"      ❌ Irrelevant: {title} (Score: {score:.2f})")
                    continue

                try:
                    downloaded = trafilatura.fetch_url(link)
                    text = None
                    if downloaded:
                        text = trafilatura.extract(
                            downloaded,
                            include_comments=False,
                            include_tables=False,
                            include_links=False,
                            favor_recall=False,
                            deduplicate=True,
                        )

                    if text:
                        # Final relevance check on full content
                        clean_text = _sanitize_for_tts(text, lang)
                        is_content_relevant_final, content_score = _is_content_relevant(
                            clean_text[:5000], title, query_terms, primary_universe
                        )

                        # Accept if it's relevant or an exact match
                        if is_content_relevant_final or exact_match:
                            # Truncate with better preservation
                            if len(clean_text) > MAX_ARTICLE_CHARS:
                                clean_text = clean_text[:MAX_ARTICLE_CHARS]
                                print(f"      ✅ Scraped & Trimmed: {len(clean_text)} chars")
                            else:
                                print(f"      ✅ Scraped Full: {len(clean_text)} chars")

                            combined_context += f"\nSOURCE: {title}\nURL: {link}\nCONTENT:\n{clean_text}\n"
                            valid_count += 1
                        else:
                            print(f"      ⚠️ Content not relevant (Score: {content_score:.2f})")
                    else:
                        # Use snippet for exact matches
                        if exact_match and score >= 0.3:
                            print("      ⚠️ No text extracted, using high-quality snippet")
                            clean_snippet = _sanitize_for_tts(snippet, lang)
                            combined_context += f"\nSOURCE: {title}\nURL: {link}\nSNIPPET:\n{clean_snippet}\n"
                            valid_count += 1
                        else:
                            print("      ⚠️ Low-quality result, skipping")

                except Exception as e:
                    print(f"      ⚠️ Error: {e}")

        if valid_count > 0:
            break  # Success with this search strategy

    if valid_count == 0:
        print("   ℹ️  No relevant sources found. Providing fallback context.")
        # Fallback: return basic information
        return f"Research context for: {query}\nNo detailed sources available. Using general knowledge about the topic."

    return combined_context.strip()