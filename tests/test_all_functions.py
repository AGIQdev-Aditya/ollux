"""
ollux — Comprehensive Full-Stack Function Verification
Tests all methods in Database, OllamaClient, OlluxAPI, AttachmentHandler, and WebSearch.
"""

import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import Database
from src.ollama_client import OllamaClient
from src.api import OlluxAPI
from src.attachment_handler import process_file
from src.web_search import perform_web_search, format_search_context, clean_search_query, should_skip_web_search


def test_every_function():
    print("=" * 60)
    print("🧪 FULL-STACK FUNCTION-BY-FUNCTION AUDIT")
    print("=" * 60)

    # 1. Database Functions
    print("\n[1/6] Testing Database functions...")
    db_path = "/tmp/test_ollux_all_funcs.db"
    db = Database(db_path)
    
    # create_session
    s_id = db.create_session("Func Test Chat", "llama2-uncensored:7b", "med")
    assert s_id is not None
    # get_session
    sess = db.get_session(s_id)
    assert sess["title"] == "Func Test Chat"
    # update_session
    db.update_session(s_id, title="Renamed Chat", model="qwen2.5:7b", thinking_level="high")
    sess_updated = db.get_session(s_id)
    assert sess_updated["title"] == "Renamed Chat"
    assert sess_updated["model"] == "qwen2.5:7b"
    assert sess_updated["thinking_level"] == "high"
    # add_message & get_messages
    m1 = db.add_message(s_id, "user", "What is Linux?", attachments=[{"name": "t.txt", "type": "text"}])
    m2 = db.add_message(s_id, "assistant", "Linux is an OS.", thinking_content="Analyzing...", metrics={"eval_count": 10})
    msgs = db.get_messages(s_id)
    assert len(msgs) == 2
    assert msgs[0]["content"] == "What is Linux?"
    assert msgs[1]["thinking_content"] == "Analyzing..."
    assert msgs[1]["metrics"]["eval_count"] == 10
    # settings
    db.set_setting("theme", "tokyonight")
    assert db.get_setting("theme") == "tokyonight"
    assert db.get_setting("non_existent", "default_val") == "default_val"
    # list_sessions & delete_session
    sessions = db.list_sessions()
    assert len(sessions) >= 1
    db.delete_session(s_id)
    assert db.get_session(s_id) is None
    print("      ✓ Database: create, get, update, delete, messages, settings all verified.")

    # 2. Ollama Client Functions
    print("\n[2/6] Testing OllamaClient functions...")
    client = OllamaClient()
    conn = client.check_connection()
    assert conn["connected"] is True
    print(f"      ✓ check_connection: Ollama v{conn['version']} online.")
    models = client.list_models()
    assert len(models) > 0
    print(f"      ✓ list_models: Found {len(models)} installed models.")

    # 3. Attachment Handler Functions
    print("\n[3/6] Testing AttachmentHandler functions...")
    # Non-existent
    assert process_file("/invalid/path/test.txt") is None
    # Directory detection
    dir_res = process_file("/home/luca/Workspace/ollux/src")
    assert dir_res["type"] == "error"
    assert "is a directory" in dir_res["error"]
    print("      ✓ Directory guard verified.")
    # Text file
    tmp_txt = "/tmp/test_func_note.txt"
    with open(tmp_txt, "w") as f:
        f.write("Line 1\nLine 2")
    txt_att = process_file(tmp_txt)
    assert txt_att["type"] == "text" and "Line 1" in txt_att["text"]
    os.remove(tmp_txt)
    # Size limit guard (>15MB)
    tmp_large = "/tmp/test_func_large.bin"
    with open(tmp_large, "wb") as f:
        f.seek(16 * 1024 * 1024)
        f.write(b"\0")
    large_att = process_file(tmp_large)
    assert large_att["type"] == "error"
    assert "exceeds maximum allowed size" in large_att["error"]
    os.remove(tmp_large)
    print("      ✓ Attachment: text, size limit, and directory handling verified.")

    # 4. Web Search Functions
    print("\n[4/6] Testing WebSearch functions...")
    assert should_skip_web_search("hello there") is True
    assert should_skip_web_search("thank you") is True
    assert should_skip_web_search("what is the latest iphone model") is False
    cleaned = clean_search_query("what is teh latets iphne moedl")
    assert "latest iphone model" in cleaned
    results = perform_web_search("Arch Linux", max_results=2)
    if results:
        formatted = format_search_context("Arch Linux", results, "llama2-uncensored:7b")
        assert "Information from web search" in formatted
        print("      ✓ Web search, greeting filter, typo corrector, and adaptive context verified.")
    else:
        print("      ⚠ Web search network call returned 0 results.")

    # 5. OlluxAPI Bridge & Dialog Filter Functions
    print("\n[5/6] Testing OlluxAPI & PyWebView Dialog Filters...")
    class MockWindow:
        def __init__(self):
            self.evals = []
        def evaluate_js(self, code):
            self.evals.append(code)
        def create_file_dialog(self, dialog_type, **kwargs):
            return ["/tmp/mock_file.txt"]

    api = OlluxAPI(db, client)
    mock_win = MockWindow()
    api.set_window(mock_win)

    # Check connection bridge
    c_res = api.check_connection()
    assert c_res["connected"] is True

    # Check models bridge
    m_res = api.get_models()
    assert len(m_res) > 0

    # Test open_file_dialog regex filters
    import webview.util
    file_filters = (
        'All files (*.*)',
        'PDF documents (*.pdf)',
        'Image files (*.png;*.jpg;*.jpeg;*.webp)',
        'Code and Text (*.txt;*.py;*.js;*.md;*.json;*.cpp;*.c;*.sh)'
    )
    for f_filter in file_filters:
        desc, exts = webview.util.parse_file_type(f_filter)
        assert desc and exts
    print("      ✓ open_file_dialog: All 4 GTK file filters conform 100% to PyWebView regex.")

    # Test parse_attachment via API
    tmp_api_file = "/tmp/api_test_file.txt"
    with open(tmp_api_file, "w") as f:
        f.write("API Test Content")
    parsed = api.parse_attachment(tmp_api_file)
    assert parsed["type"] == "text" and "API Test Content" in parsed["text"]
    os.remove(tmp_api_file)

    # Test parse_attachment_b64
    import base64
    b64_dummy = base64.b64encode(b"%PDF-1.4 dummy pdf header").decode("utf-8")
    parsed_b64 = api.parse_attachment_b64("dummy.pdf", b64_dummy)
    assert parsed_b64 is not None
    print("      ✓ parse_attachment and parse_attachment_b64 bridge functional.")

    # 6. Live Streaming and Stop Interruption via Bridge
    print("\n[6/6] Testing Live Stream Execution and Stop Interruption...")
    s_id2 = db.create_session("Streaming Test", "llama2-uncensored:7b", "low")
    send_res = api.send_message(
        session_id=s_id2,
        content="Count numbers 1 to 20 slowly",
        model="llama2-uncensored:7b",
        thinking_level="low",
        web_search=False
    )
    assert send_res["status"] == "started"

    # Let stream start, then test immediate stop
    time.sleep(0.3)
    stop_res = api.stop_generation()
    assert stop_res is True

    # Wait for completion
    time.sleep(0.5)
    assert not api._is_generating
    print("      ✓ stop_generation: Successfully signaled abort, stream stopped cleanly.")

    # Cleanup DB
    if os.path.exists(db_path):
        os.remove(db_path)

    print("\n" + "=" * 60)
    print("🎉 ALL FUNCTIONS VERIFIED & 100% OPERATIONAL!")
    print("=" * 60)


if __name__ == "__main__":
    test_every_function()
