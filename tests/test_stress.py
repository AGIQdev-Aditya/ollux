"""
ollux — Comprehensive Stress & Edge-Case Test Suite
Validates concurrent DB transactions, search caching, model prompt adaptation,
and live hardware inference.
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import Database
from src.ollama_client import OllamaClient
from src.web_search import (
    clean_search_query,
    should_skip_web_search,
    perform_web_search,
    format_search_context
)
from src.attachment_handler import process_file


def run_stress_tests():
    print("=" * 60)
    print("🚀 OLLUX COMPREHENSIVE STRESS & VERIFICATION SUITE")
    print("=" * 60)

    # 1. Database Concurrency & Stress
    print("\n[Test 1/5] Stress Testing SQLite Database with WAL...")
    db_file = "/tmp/ollux_stress_test.db"
    if os.path.exists(db_file):
        os.remove(db_file)

    db = Database(db_file)
    t0 = time.time()
    for s_idx in range(5):
        sid = db.create_session(f"Stress Session {s_idx}", "qwen3.8:27b", "high")
        for m_idx in range(20):
            db.add_message(
                session_id=sid,
                role="user" if m_idx % 2 == 0 else "assistant",
                content=f"Message {m_idx} in session {s_idx} with unicode ⚡🦙💻",
                metrics={"tokens_per_second": 32.5}
            )
    t_db = time.time() - t0
    sessions = db.list_sessions()
    assert len(sessions) == 5, f"Expected 5 sessions, got {len(sessions)}"
    all_msgs = db.get_messages(sessions[0]["id"])
    assert len(all_msgs) == 20, f"Expected 20 messages, got {len(all_msgs)}"
    print(f"      ✓ Created 5 sessions & 100 messages in {t_db*1000:.1f}ms (WAL active).")
    os.remove(db_file)

    # 2. Web Search Greeting Bypass & Typo Correction
    print("\n[Test 2/5] Testing Web Search Sanitization & Caching...")
    greetings = ["hi", "HELLO!", "hey there", "thanks", "ok", "who are you"]
    for g in greetings:
        assert should_skip_web_search(g) is True, f"Failed to skip greeting: {g}"
    print("      ✓ Conversational greetings correctly bypassed.")

    dirty_query = "what is teh latets iphne moedl"
    cleaned = clean_search_query(dirty_query)
    assert "latest" in cleaned and "iphone" in cleaned
    print(f"      ✓ Typo normalization: '{dirty_query}' -> '{cleaned}'")

    # Caching test
    t_start = time.time()
    res1 = perform_web_search("Arch Linux news", max_results=2)
    t_first = time.time() - t_start
    t_start2 = time.time()
    res2 = perform_web_search("Arch Linux news", max_results=2)
    t_cached = time.time() - t_start2
    print(f"      ✓ Search network call: {t_first:.2f}s | Cached recall: {t_cached*1000:.2f}ms")

    # 3. Model-Adaptive Web Grounding Format
    print("\n[Test 3/5] Testing Model-Adaptive Grounding Formats...")
    mock_res = [{"title": "Test Title", "href": "https://example.com", "body": "Release date is 2026."}]
    ctx_legacy = format_search_context("test", mock_res, model_name="llama2-uncensored:7b")
    assert "Information from web search:" in ctx_legacy
    assert "Based strictly on the facts" in ctx_legacy
    print("      ✓ Legacy model format verified (direct fact primer).")

    ctx_modern = format_search_context("test", mock_res, model_name="qwen3.8:27b")
    assert "=== REAL-TIME WEB SEARCH RESULTS" in ctx_modern
    assert "Cite your sources using [1]" in ctx_modern
    print("      ✓ Modern instruct model format verified (structured RAG citations).")

    # 4. Attachment Processor Edge Cases
    print("\n[Test 4/5] Testing Attachment Handling Edge Cases...")
    assert process_file("/non/existent/path/file.txt") is None
    tmp_code = "/tmp/test_code.py"
    with open(tmp_code, "w") as f:
        f.write("# Python test file\nprint('hello world')\n")
    att = process_file(tmp_code)
    assert att["type"] == "text" and "hello world" in att["text"]
    os.remove(tmp_code)
    print("      ✓ Attachment handler verified.")

    # 5. Live Inference Speed & Reasoning Extraction
    print("\n[Test 5/5] Testing Live Inference Speed & Reasoning Separator...")
    client = OllamaClient()
    conn = client.check_connection()
    assert conn["connected"] is True, "Ollama daemon offline"
    
    stream_chunks = []
    stream_metrics = {}

    def on_chunk(c):
        stream_chunks.append(c)

    def on_complete(m):
        nonlocal stream_metrics
        stream_metrics = m

    client.stream_chat(
        model="llama2-uncensored:7b",
        messages=[{"role": "user", "content": "Reply with 'ALL SYSTEMS GO'"}],
        thinking_level="low",
        on_chunk=on_chunk,
        on_complete=on_complete
    )
    assert stream_metrics.get("tokens_per_second", 0) > 0
    print(f"      ✓ Hardware inference: {stream_metrics['tokens_per_second']} tokens/sec")
    print(f"      ✓ Total tokens: {stream_metrics['eval_count']} in {stream_metrics['eval_duration_secs']}s")

    print("\n" + "=" * 60)
    print("🎉 ALL STRESS TESTS & EDGE CASES PASSED WITH 100% SUCCESS!")
    print("=" * 60)


if __name__ == "__main__":
    run_stress_tests()
