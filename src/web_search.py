"""
ollux — Privacy-First Web Search Integration
Queries web sources via DuckDuckGo without API keys, accounts, or trackers.
Includes query sanitization, greeting bypass, and structured ground-truth formatting.
"""

import re
from typing import List, Dict, Any, Optional

# Conversational greetings where web search should never be triggered
GREETING_WORDS = {
    "hi", "hello", "hey", "hola", "sup", "yo", "thanks", "thank you",
    "ok", "okay", "bye", "good morning", "good evening", "good afternoon",
    "how are you", "who are you", "what can you do", "test"
}

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


def should_skip_web_search(user_query: str) -> bool:
    """Check if query is purely conversational and does not need web search."""
    normalized = user_query.strip().lower().strip("!.?,")
    return normalized in GREETING_WORDS or len(normalized) < 3


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


def perform_web_search(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Search DuckDuckGo for live query context.
    Returns list of dicts with title, href, and body.
    """
    cleaned = clean_search_query(query)
    if not cleaned:
        return []

    results = []

    # 1. Primary: modern ddgs library
    try:
        from ddgs import DDGS
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


def format_search_context(query: str, results: List[Dict[str, str]]) -> str:
    """Format search results into a clean, authoritative ground-truth prompt."""
    if not results:
        return ""

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
