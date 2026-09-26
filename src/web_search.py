"""
ollux — Privacy-First Web Search Integration
Queries web sources via DuckDuckGo without API keys, accounts, or trackers.
Includes query sanitization, greeting bypass, and structured ground-truth formatting.
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional

GREETING_PATTERNS = [
    r"^(hi|hello|hey|hola|sup|yo|greetings)(\s+(there|buddy|bro|friend|bot|assistant))?$",
    r"^(good\s+(morning|evening|afternoon|day|night))$",
    r"^(thank\s*you|thanks(\s+(a\s+lot|so\s+much))?)$",
    r"^(ok|okay|k|cool|alright|fine|yes|no|yeah|nah)$",
    r"^(bye|goodbye|see\s+ya|farewell)$",
    r"^(who\s+are\s+you|what\s+can\s+you\s+do|how\s+are\s+you(\s+doing)?)$"
]


def should_skip_web_search(user_query: str) -> bool:
    """Check if query is purely conversational and does not need web search."""
    normalized = user_query.strip().lower().strip("!.?,")
    if len(normalized) < 2:
        return True
    for pat in GREETING_PATTERNS:
        if re.match(pat, normalized):
            return True
    return False


TYPO_FIXES = {
    r"\bteh\b": "the",
    r"\blatets\b": "latest",
    r"\blatest\b": "latest",
    r"\bwat\b": "what",
    r"\btaht\b": "that",
    r"\bwich\b": "which",
    r"\biphne\b": "iphone",
    r"\bmoedl\b": "model",
    r"\bserach\b": "search",
    r"\bchek\b": "check",
    r"\bplewase\b": "please",
    r"\bplz\b": "please",
    r"\brn\b": "current",
}

DIRECTIVE_PATTERNS = [
    r"\b(check|search|look\s*up|verify|find|google|browse)\s*(the\s+web|online|internet)?\b",
    r"\b(and\s+)?(then\s+)?tell\s+me(\s+about)?\b",
    r"\b(can\s+you\s+)?(tell\s+me|show\s+me|give\s+me)\b",
    r"\bwhat\s+(is|are)\s+(the\s+)?\b",
    r"\bdo\s+you\s+know\b",
    r"\bplease\b",
    r"^\s*so\s+",
]


def clean_search_query(user_query: str, history: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """
    Sanitize and formulate a high-yield web search query from user prompt.
    If the prompt is a follow-up directive (e.g. 'check the web and tell me'),
    intelligently resolves the subject from conversation history.
    """
    if should_skip_web_search(user_query):
        return None

    query = user_query.strip().lower()

    # Apply common typo corrections
    for pattern, replacement in TYPO_FIXES.items():
        query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)

    # Strip conversational and search directives
    for pat in DIRECTIVE_PATTERNS:
        query = re.sub(pat, " ", query, flags=re.IGNORECASE).strip()

    # Normalize whitespace and trailing punctuation
    query = re.sub(r"[?!.,;:]+", " ", query).strip()
    query = re.sub(r"\s+", " ", query).strip()

    # If empty or only generic filler remains, resolve subject from previous user turns
    if len(query) < 3 or query in ["it", "that", "them", "about that", "again", "now", "current"]:
        if history:
            for msg in reversed(history):
                if msg.get("role") == "user":
                    prev_clean = clean_search_query(msg.get("content", ""))
                    if prev_clean and len(prev_clean) >= 3:
                        query = f"{prev_clean} {query}".strip()
                        break

    if not query or len(query) < 2:
        query = user_query.strip()

    # If asking for "latest" or "newest", add current year and brand context
    if any(k in query for k in ["latest", "newest", "current", "recent"]):
        curr_year = str(datetime.now().year)
        if curr_year not in query:
            query = f"{query} {curr_year}"
        if "iphone" in query and "apple" not in query:
            query = f"{query} apple"

    return query


_MAX_SEARCH_CACHE_SIZE = 100
_search_cache: Dict[str, Any] = {}


def perform_web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Search DuckDuckGo for live query context.
    Returns list of dicts with title, href, and body.
    Includes in-memory caching to avoid redundant network calls.
    """
    import time

    cleaned = clean_search_query(query)
    if not cleaned:
        return []

    cache_key = f"{cleaned}:{max_results}"
    now = time.time()
    if cache_key in _search_cache:
        cached_entry = _search_cache[cache_key]
        if now - cached_entry["time"] < 300:  # 5 min TTL
            return cached_entry["results"]

    results = []

    # 1. Primary: modern ddgs library with 4s timeout
    try:
        from ddgs import DDGS
        with DDGS(timeout=4) as ddgs:
            raw = list(ddgs.text(cleaned, max_results=max_results))
            for item in raw:
                body = item.get("body", "").strip()
                if body and len(body) > 30:
                    results.append({
                        "title": item.get("title", "").strip(),
                        "href": item.get("href", "").strip(),
                        "body": body
                    })
            if results:
                if len(_search_cache) >= _MAX_SEARCH_CACHE_SIZE:
                    oldest_key = min(_search_cache.keys(), key=lambda k: _search_cache[k]["time"])
                    _search_cache.pop(oldest_key, None)
                _search_cache[cache_key] = {"results": results, "time": now}
                return results
    except Exception:
        pass

    # 2. Secondary fallback: duckduckgo_search
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(cleaned, max_results=max_results))
            for item in raw:
                body = item.get("body", "").strip()
                if body and len(body) > 30:
                    results.append({
                        "title": item.get("title", "").strip(),
                        "href": item.get("href", "").strip(),
                        "body": body
                    })
            if results:
                if len(_search_cache) >= _MAX_SEARCH_CACHE_SIZE:
                    oldest_key = min(_search_cache.keys(), key=lambda k: _search_cache[k]["time"])
                    _search_cache.pop(oldest_key, None)
                _search_cache[cache_key] = {"results": results, "time": now}
                return results
    except Exception:
        pass

    return results


def format_search_context(query: str, results: List[Dict[str, str]], model_name: str = "") -> str:
    """Format search results into model-adaptive ground-truth prompt."""
    if not results:
        return ""

    is_legacy_model = any(k in model_name.lower() for k in ["llama2", "alpaca", "vicuna"])

    today_str = datetime.now().strftime("%A, %B %d, %Y")
    current_year = datetime.now().year

    if is_legacy_model:
        # Simplified direct fact-injection format for smaller/legacy models
        lines = [
            f"Information from web search: (Current Date: {today_str})"
        ]
        for idx, item in enumerate(results, 1):
            lines.append(f"- Fact {idx}: {item['title']} - {item['body']}")
        lines.append(f"\nQuestion: {query}")
        lines.append("Based strictly on the facts above, here is the direct answer:")
        return "\n".join(lines)

    # Modern instruct models (Qwen 2.5/3.8, Nemotron, Llama 3+, Mistral)
    context_lines = [
        f'=== REAL-TIME WEB SEARCH RESULTS FOR: "{query}" ===',
        f"TEMPORAL ANCHOR: Today's Date is {today_str} (Year {current_year}).",
        "You are an intelligent assistant with live web access.",
        f"Below are the verified live search results. Prioritize the newest releases, models, and specifications from {current_year - 1}-{current_year}.\n"
    ]
    for idx, item in enumerate(results, 1):
        context_lines.append(f"[{idx}] Source: {item['title']}\nURL: {item['href']}\nContent: {item['body']}\n")

    context_lines.append(
        "=== INSTRUCTIONS ==="
        "\n1. State the exact answer directly in your first sentence based on the live search results."
        "\n2. Highlight specific model names, version numbers, and release dates."
        "\n3. Keep your explanation concise and direct without unnecessary filler."
        "\n4. Cite your sources using [1], [2] brackets."
    )
    return "\n".join(context_lines)
