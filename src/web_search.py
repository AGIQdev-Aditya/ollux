"""
ollux — Privacy-First Web Search Integration
Queries web sources via DuckDuckGo without API keys, accounts, or trackers.
Injects concise context snippets with citations for the local model.
"""

from typing import List, Dict, Any


def perform_web_search(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """
    Search DuckDuckGo for live query context.
    Returns list of dicts with title, href, and body.
    """
    results = []
    
    # 1. Primary: modern ddgs library
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
            for item in raw:
                results.append({
                    "title": item.get("title", ""),
                    "href": item.get("href", ""),
                    "body": item.get("body", "")
                })
            if results:
                return results
    except Exception:
        pass

    # 2. Secondary fallback: duckduckgo_search
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
            for item in raw:
                results.append({
                    "title": item.get("title", ""),
                    "href": item.get("href", ""),
                    "body": item.get("body", "")
                })
            if results:
                return results
    except Exception:
        pass

    return results


def format_search_context(query: str, results: List[Dict[str, str]]) -> str:
    """Format search results into a clean grounding prompt for Ollama."""
    if not results:
        return ""
    
    context_lines = [f'--- WEB SEARCH RESULTS FOR: "{query}" ---']
    for idx, item in enumerate(results, 1):
        context_lines.append(f"[{idx}] {item['title']}\nURL: {item['href']}\nSnippet: {item['body']}\n")
    context_lines.append(
        "--- END SEARCH RESULTS ---\n"
        "Instructions: Ground your answer in the web search results above. Use [1], [2] citations where appropriate."
    )
    return "\n".join(context_lines)
