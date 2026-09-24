"""
ollux — Privacy-First Web Search Integration
Queries web sources via DuckDuckGo without API keys, accounts, or trackers.
Includes query sanitization, greeting bypass, and structured ground-truth formatting.
"""

import re
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
    r"\bmoedl\b": "model"
}


def clean_search_query(user_query: str) -> Optional[str]:
    """Sanitize and formulate a high-yield web search query from user prompt."""
    if should_skip_web_search(user_query):
        return None

    query = user_query.strip().lower()

    # Apply common typo corrections
    for pattern, replacement in TYPO_FIXES.items():
        query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)

    # Strip conversational filler prefixes
    filler_patterns = [
        r"^(can you\s+)?tell me\s+(about\s+)?",
        r"^(what|who|where|when|which)\s+is\s+(the\s+)?",
        r"^(what|who|where|when|which)\s+are\s+(the\s+)?",
        r"^(do you know\s+)?what\s+(is\s+)?",
        r"^search\s+(the\s+web\s+for\s+|for\s+)?",
        r"^look\s+up\s+",
        r"^please\s+",
    ]
    for pat in filler_patterns:
        query = re.sub(pat, "", query, flags=re.IGNORECASE).strip()

    # Remove trailing punctuation
    query = query.strip("?!.,;:")

    # If asking for "latest" or "newest", ensure context keywords are included
    if "latest" in query or "newest" in query or "recent" in query:
        if "iphone" in query and "apple" not in query:
            query = f"{query} apple"

    return query if len(query) >= 3 else user_query.strip()


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
                return results
    except Exception:
        pass

    return results


def format_search_context(query: str, results: List[Dict[str, str]], model_name: str = "") -> str:
    """Format search results into model-adaptive ground-truth prompt."""
    if not results:
        return ""

    is_legacy_model = any(k in model_name.lower() for k in ["llama2", "alpaca", "vicuna"])

    if is_legacy_model:
        # Simplified direct fact-injection format for smaller/legacy models
        lines = ["Information from web search:"]
        for idx, item in enumerate(results, 1):
            lines.append(f"- Fact {idx}: {item['title']} - {item['body']}")
        lines.append(f"\nQuestion: {query}")
        lines.append("Based strictly on the facts above, here is the direct answer:")
        return "\n".join(lines)

    # Modern instruct models (Qwen 2.5/3.8, Nemotron, Llama 3+, Mistral)
    context_lines = [
        f'=== REAL-TIME WEB SEARCH RESULTS FOR: "{query}" ===',
        "You are an intelligent assistant answering with live web access.",
        "Below are the verified search results. Base your answer directly on these facts.\n"
    ]
    for idx, item in enumerate(results, 1):
        context_lines.append(f"[{idx}] Source: {item['title']}\nURL: {item['href']}\nContent: {item['body']}\n")

    context_lines.append(
        "=== INSTRUCTIONS ==="
        "\n1. State the exact answer directly in your first sentence based on the search results."
        "\n2. Highlight specific model names, version numbers, and release dates."
        "\n3. Keep your explanation concise and direct without unnecessary filler."
        "\n4. Cite your sources using [1], [2] brackets."
    )
    return "\n".join(context_lines)
