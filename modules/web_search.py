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
# UNIVERSAL QUALITY FILTERING (NO UNIVERSE-SPECIFIC INFO)
# -------------------------------------------------------------------

SOCIAL_DOMAINS = ("youtube.com", "youtu.be", "instagram.com", "facebook.com", "tiktok.com", "x.com", "twitter.com",
                  "pinterest.com", "linkedin.com", "reddit.com")
BLOG_DOMAINS = ("medium.com", "tumblr.com", "blogspot.com", "wordpress.com")
BLOCKED_DOMAINS = SOCIAL_DOMAINS + BLOG_DOMAINS
QUALITY_SOURCES = ("fandom.com", "gamepedia.com", "wikipedia.org", "wikia.org")

BLOCKED_EXTENSIONS = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".rar", ".7z", ".apk", ".exe")
BAD_PATH_KEYWORDS = ("/tag/", "/tags/", "/category/", "/search", "?s=", "/login", "/signup", "/account", "/privacy",
                     "/terms")

# -------------------------------------------------------------------
# UNIVERSAL CONTAMINATION DETECTION (AUTOMATIC LEARNING)
# -------------------------------------------------------------------

# Common contamination patterns that appear across ALL domains
COMMON_CONTAMINATION_PATTERNS = [
    # Social media/marketing spam
    "click here", "buy now", "subscribe", "follow us", "like share",
    # E-commerce
    "shop now", "discount", "sale", "free shipping",
    # Low-quality content
    "lorem ipsum", "dummy text", "placeholder", "coming soon",
    # Adult content indicators
    "xxx", "porn", "sex", "nude"
]


def _extract_meaningful_terms(query: str) -> list:
    """Extract meaningful terms that represent the core topic"""
    # Remove very common words but keep context
    common_words = {"the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was",
                    "were"}

    # Extract words and clean them
    words = re.findall(r'\w+', query.lower())
    meaningful_terms = [w for w in words if len(w) > 2 and w not in common_words]

    return meaningful_terms


def _calculate_similarity_score(text: str, target_terms: list) -> float:
    """Calculate how relevant text is to target terms (0.0 to 1.0)"""
    if not target_terms:
        return 1.0

    text_lower = text.lower()
    matches = 0
    total_weight = 0

    for term in target_terms:
        term_weight = len(term)  # Longer terms are more specific
        total_weight += term_weight

        # Count occurrences (title matches worth more)
        occurrences = text_lower.count(term.lower())
        matches += occurrences * term_weight

    # Normalize score
    if total_weight == 0:
        return 1.0

    # Cap at 1.0 but allow higher scores for very relevant content
    return min(matches / total_weight, 1.0)


def _detect_contamination(text: str, title: str) -> tuple[bool, float]:
    """
    Universal contamination detection
    Returns (is_contaminated, contamination_score)
    """
    combined_text = (title + " " + text).lower()

    # Check for common contamination patterns
    contamination_score = 0

    for pattern in COMMON_CONTAMINATION_PATTERNS:
        if pattern in combined_text:
            contamination_score += 1

    # Check for excessive commercial language
    commercial_words = ["buy", "sell", "price", "cost", "deal", "offer", "coupon"]
    commercial_count = sum(1 for word in commercial_words if word in combined_text)
    contamination_score += commercial_count * 0.5

    # High contamination score means likely spam/irrelevant
    is_contaminated = contamination_score > 2.0

    return is_contaminated, contamination_score


def _is_quality_source(url: str, title: str, snippet: str) -> bool:
    """Universal quality source detection without universe bias"""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    # Basic blocking
    if any(bad in domain for bad in BLOCKED_DOMAINS):
        return False
    if any(path.endswith(ext) for ext in BLOCKED_EXTENSIONS):
        return False
    if any(bad in path for bad in BAD_PATH_KEYWORDS):
        return False
    if len(snippet.split()) < 3:  # Very short snippets
        return False

    # Prefer known quality sources
    if any(quality_domain in domain for quality_domain in QUALITY_SOURCES):
        return True

    # Accept other sources if they have decent titles/snippets
    return len(title) > 10 and len(snippet) > 50


# -------------------------------------------------------------------
# UNIVERSAL SEARCH & SCRAPE ENGINE
# -------------------------------------------------------------------

def _google_search_page(query: str, start: int, num: int = GOOGLE_RESULTS_PER_PAGE, lang: str = "en"):
    search_url = "https://www.googleapis.com/customsearch/v1"
    creds = _get_next_key_pair()
    if not creds: return []

    print(f"   🔑 Using key: {creds['key'][:8]}...")

    # Universal search strategy - ALWAYS search in English for best sources
    search_query = f"site:fandom.com OR site:wikipedia.org OR site:gamepedia.com {query}"

    # Always search in English regardless of output language
    params = {
        "key": creds["key"],
        "cx": creds["cx"],
        "q": search_query,
        "num": num,
        "start": start,
        "lr": "lang_en"  # FIXED: Always search in English for consistent quality sources
    }

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

    # Extract meaningful terms from query
    target_terms = _extract_meaningful_terms(query)
    print(f"   🎯 Target Terms: {target_terms}")

    combined_context = ""
    valid_count = 0
    seen_urls = set()

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

            # Quality source check (universe-neutral)
            if not _is_quality_source(link, title, snippet):
                print(f"      ❌ Low quality source: {title}")
                continue

            # Contamination check (universal)
            is_contaminated, contam_score = _detect_contamination(snippet, title)
            if is_contaminated:
                print(f"      ❌ Contaminated content: {title} (Score: {contam_score:.1f})")
                continue

            # Relevance check based on target terms
            similarity_score = _calculate_similarity_score(title + " " + snippet, target_terms)

            # Exact term matches get priority
            exact_matches = sum(1 for term in target_terms if term.lower() in (title + " " + snippet).lower())
            has_exact_match = exact_matches > 0

            if has_exact_match or similarity_score >= 0.1:
                print(f"   👉 Checking: {title} (Similarity: {similarity_score:.2f})")
            else:
                print(f"      ❌ Low similarity: {title} (Score: {similarity_score:.2f})")
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
                    # Final quality check on full content
                    clean_text = _sanitize_for_tts(text, lang)

                    # Check contamination on full text
                    is_contaminated_full, _ = _detect_contamination(clean_text[:1000], title)
                    if is_contaminated_full:
                        print(f"      ⚠️ Full content contaminated")
                        continue

                    # Check relevance on full content
                    full_similarity = _calculate_similarity_score(clean_text[:5000], target_terms)

                    if has_exact_match or full_similarity >= 0.05:  # Very lenient
                        # Truncate with better preservation
                        if len(clean_text) > MAX_ARTICLE_CHARS:
                            clean_text = clean_text[:MAX_ARTICLE_CHARS]
                            print(f"      ✅ Scraped & Trimmed: {len(clean_text)} chars")
                        else:
                            print(f"      ✅ Scraped Full: {len(clean_text)} chars")

                        combined_context += f"\nSOURCE: {title}\nURL: {link}\nCONTENT:\n{clean_text}\n"
                        valid_count += 1
                    else:
                        print(f"      ⚠️ Full content not relevant (Score: {full_similarity:.2f})")
                else:
                    # Use snippet for exact matches
                    if has_exact_match and similarity_score >= 0.2:
                        print("      ⚠️ No text extracted, using high-quality snippet")
                        clean_snippet = _sanitize_for_tts(snippet, lang)
                        combined_context += f"\nSOURCE: {title}\nURL: {link}\nSNIPPET:\n{clean_snippet}\n"
                        valid_count += 1
                    else:
                        print("      ⚠️ Low-quality result, skipping")

            except Exception as e:
                print(f"      ⚠️ Error: {e}")

    if valid_count == 0:
        print("   ℹ️  No relevant sources found. Providing fallback context.")
        # Fallback: return basic information
        return f"Research context for: {query}\nNo detailed sources available. Using general knowledge about the topic."

    return combined_context.strip()