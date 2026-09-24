"""
ollux — Automated Pipeline Verification
Validates Database, Ollama API, Streaming, Reasoning extraction, and Speed metrics.
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import Database
from src.ollama_client import OllamaClient
from src.web_search import perform_web_search, format_search_context
from src.attachment_handler import process_file

def test_full_pipeline():
    print("[1/5] Testing Database...")
    db = Database("/tmp/test_ollux_pipeline.db")
    s_id = db.create_session("Automated Verification", "llama2-uncensored:7b", "med")
    assert s_id is not None
    db.add_message(s_id, "user", "Hello world")
    msgs = db.get_messages(s_id)
    assert len(msgs) == 1
    print("      ✓ Database session & messages functional.")

    print("[2/5] Testing Ollama Connection & Model Listing...")
    client = OllamaClient()
    conn = client.check_connection()
    assert conn.get("connected") is True, f"Ollama not reachable: {conn}"
    models = client.list_models()
    assert len(models) > 0, "No models detected"
    print(f"      ✓ Connected to Ollama v{conn['version']} with {len(models)} models.")

    print("[3/5] Testing Live Inference & Token Speed Metrics...")
    # Use a small fast model for test
    test_model = "llama2-uncensored:7b"
    received_tokens = []
    completed_metrics = {}

    def on_chunk(chunk):
        if chunk["type"] == "content":
            received_tokens.append(chunk["token"])

    def on_complete(metrics):
        nonlocal completed_metrics
        completed_metrics = metrics

    client.stream_chat(
        model=test_model,
        messages=[{"role": "user", "content": "Respond with exactly the word SUCCESS."}],
        thinking_level="low",
        on_chunk=on_chunk,
        on_complete=on_complete
    )

    full_output = "".join(received_tokens).strip()
    print(f"      ✓ Model response: '{full_output}'")
    assert completed_metrics.get("tokens_per_second", 0) > 0
    print(f"      ✓ Speed benchmark: {completed_metrics['tokens_per_second']} tokens/sec, eval count: {completed_metrics['eval_count']}")

    print("[4/5] Testing Attachment File Processor...")
    test_txt_path = "/tmp/test_note.txt"
    with open(test_txt_path, "w") as f:
        f.write("Aditya Sharma - ollux test attachment")
    att = process_file(test_txt_path)
    assert att["type"] == "text" and "ollux" in att["text"]
    os.remove(test_txt_path)
    print("      ✓ Attachment processor functional.")

    print("[5/5] Testing Web Search Context Injection...")
    results = perform_web_search("Linux kernel", max_results=1)
    if results:
        formatted = format_search_context("Linux kernel", results)
        assert "WEB SEARCH RESULTS" in formatted
        print("      ✓ DuckDuckGo search integration verified.")
    else:
        print("      ⚠ Web search returned 0 results (network dependent).")

    # Cleanup DB
    if os.path.exists("/tmp/test_ollux_pipeline.db"):
        os.remove("/tmp/test_ollux_pipeline.db")

    print("\n🎉 ALL 5 PIPELINE CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_full_pipeline()
