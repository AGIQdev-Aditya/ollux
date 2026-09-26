"""
ollux — PyWebView JavaScript Bridge API
Exposes secure native backend functions to the frontend web application.
Handles asynchronous streaming, threading, file dialogs, and SQLite persistence.
"""

import os
import json
import time
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import webview

from src.ollama_client import OllamaClient
from src.database import Database
from src.attachment_handler import process_file
from src.web_search import perform_web_search, format_search_context, should_skip_web_search, clean_search_query


class OlluxAPI:
    def __init__(self, db: Database, client: OllamaClient):
        self.db = db
        self.client = client
        self.window = None
        self._is_generating = False
        self._stream_lock = threading.Lock()
        self._stop_event = threading.Event()

    @property
    def _stop_requested(self) -> bool:
        """Compatibility property reflecting stop event state."""
        return self._stop_event.is_set()

    @_stop_requested.setter
    def _stop_requested(self, val: bool):
        if val:
            self._stop_event.set()
        else:
            self._stop_event.clear()

    def set_window(self, window):
        self.window = window

    # --- System & Model Management ---

    def check_connection(self) -> Dict[str, Any]:
        """Check Ollama daemon status."""
        return self.client.check_connection()

    def get_models(self) -> List[Dict[str, Any]]:
        """List all downloaded models."""
        return self.client.list_models()

    def delete_model(self, model_name: str) -> Dict[str, Any]:
        """Delete an installed model from disk."""
        return self.client.delete_model(model_name)

    def pull_model(self, model_name: str):
        """Asynchronously pull model with progress events."""
        def run_pull():
            def on_progress(data):
                if self.window:
                    payload = json.dumps(data)
                    self.window.evaluate_js(f"window.onModelPullProgress({payload})")
            
            success = self.client.pull_model(model_name, on_progress)
            if self.window:
                res = json.dumps({"status": "completed", "success": success, "model": model_name})
                self.window.evaluate_js(f"window.onModelPullComplete({res})")

        thread = threading.Thread(target=run_pull, daemon=True)
        thread.start()
        return {"status": "started", "model": model_name}

    # --- Sessions & History ---

    def get_sessions(self) -> List[Dict[str, Any]]:
        return self.db.list_sessions()

    def get_session_data(self, session_id: str) -> Dict[str, Any]:
        session = self.db.get_session(session_id)
        messages = self.db.get_messages(session_id)
        return {"session": session, "messages": messages}

    def create_session(self, title: str = "New Chat", model: str = "", thinking_level: str = "med") -> str:
        if not model:
            models = self.client.list_models()
            model = models[0]["name"] if models else "llama2-uncensored:7b"
        return self.db.create_session(title=title, model=model, thinking_level=thinking_level)

    def update_session(self, session_id: str, title: Optional[str] = None, model: Optional[str] = None, thinking_level: Optional[str] = None):
        self.db.update_session(session_id, title=title, model=model, thinking_level=thinking_level)
        return True

    def delete_session(self, session_id: str) -> bool:
        return self.db.delete_session(session_id)

    def toggle_pin_session(self, session_id: str) -> bool:
        return self.db.toggle_pin_session(session_id)

    def export_session_markdown(self, session_id: str) -> Dict[str, Any]:
        """Export session history as a beautifully formatted Markdown file."""
        if not self.window:
            return {"success": False, "error": "No active window"}
        session = self.db.get_session(session_id)
        if not session:
            return {"success": False, "error": "Session not found"}

        messages = self.db.get_messages(session_id)
        title = session.get("title", "Conversation")
        clean_title = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "conversation"

        dialog_type = getattr(getattr(webview, "FileDialog", None), "SAVE", getattr(webview, "SAVE_DIALOG", None))
        filepath = self.window.create_file_dialog(
            dialog_type,
            save_filename=f"{clean_title}.md",
            file_types=('Markdown (*.md)', 'All files (*.*)')
        )
        if not filepath:
            return {"success": False, "canceled": True}

        if isinstance(filepath, (list, tuple)):
            filepath = filepath[0]

        lines = [
            f"# {title}",
            f"- **Model**: {session.get('model', 'Unknown')}",
            f"- **Exported**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "---",
            ""
        ]

        for msg in messages:
            role_name = "🧑 User" if msg["role"] == "user" else "🦙 Assistant"
            lines.append(f"### {role_name}\n")
            if msg.get("thinking_content"):
                lines.append(f"> **Thinking Process**:\n> " + msg['thinking_content'].strip().replace("\n", "\n> ") + "\n")
            lines.append(msg["content"] + "\n")
            if msg.get("metrics") and msg["metrics"].get("eval_count"):
                m = msg["metrics"]
                lines.append(f"*⚡ {m.get('tokens_per_second', 0)} tok/s | {m.get('eval_count', 0)} tokens | {m.get('eval_duration_secs', 0)}s*\n")
            lines.append("---\n")

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return {"success": True, "path": filepath}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_setting(self, key: str, default: Any = None):
        return self.db.get_setting(key, default)

    def set_setting(self, key: str, value: Any):
        self.db.set_setting(key, value)
        return True

    # --- File Attachments ---

    def open_file_dialog(self) -> List[str]:
        """Show native GTK file picker dialog."""
        if not self.window:
            return []
        dialog_type = getattr(getattr(webview, "FileDialog", None), "OPEN", getattr(webview, "OPEN_DIALOG", None))
        result = self.window.create_file_dialog(
            dialog_type,
            allow_multiple=True,
            file_types=('All files (*.*)', 'PDF documents (*.pdf)', 'Image files (*.png;*.jpg;*.jpeg;*.webp)', 'Code and Text (*.txt;*.py;*.js;*.md;*.json;*.cpp;*.c;*.sh)')
        )
        return list(result) if result else []

    def parse_attachment(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Extract text or encode image from file path."""
        return process_file(filepath)

    def parse_attachment_b64(self, filename: str, b64_content: str) -> Optional[Dict[str, Any]]:
        """Extract text or document data from base64 buffer when path is sandboxed."""
        import base64
        import io
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
                pdf_bytes = base64.b64decode(b64_content)
                reader = PdfReader(io.BytesIO(pdf_bytes))
                pages_text = []
                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages_text.append(f"--- Page {i+1} ---\n{text.strip()}")
                return {
                    "name": filename,
                    "type": "pdf",
                    "size": f"{len(pdf_bytes)/1024:.1f} KB",
                    "pages": len(reader.pages),
                    "text": "\n\n".join(pages_text)
                }
            except Exception as e:
                return {"name": filename, "type": "error", "error": str(e)}
        return None

    # --- Chat Streaming & Web Search ---

    def stop_generation(self):
        """Signal generation loop to halt and immediately abort HTTP stream."""
        self._stop_event.set()
        with self._stream_lock:
            self._is_generating = False
        return True

    def send_message(
        self,
        session_id: str,
        content: str,
        model: str,
        thinking_level: str = "med",
        web_search: bool = False,
        attachments: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Main chat pipeline.
        Saves user message -> executes web search if toggled -> formats context -> streams tokens.
        """
        with self._stream_lock:
            if self._is_generating:
                return {"status": "busy"}
            self._is_generating = True
            self._stop_event.clear()

        attachments = attachments or []

        # 1. Store user message in DB
        self.db.add_message(
            session_id=session_id,
            role="user",
            content=content,
            attachments=attachments
        )

        # Auto-generate session title if it's the first message
        session = self.db.get_session(session_id)
        if session and (session.get("title") == "New Chat" or not session.get("title")):
            words = content.strip().split()
            first_title = " ".join(words[:5]) if words else "Conversation"
            if len(first_title) > 35:
                first_title = first_title[:32] + "..."
            self.db.update_session(session_id, title=first_title, model=model, thinking_level=thinking_level)
            if self.window:
                self.window.evaluate_js(f"window.onSessionRenamed({json.dumps({'id': session_id, 'title': first_title})})")

        # 2. Spawn worker thread for search & streaming
        def worker():
            search_context_prompt = ""
            search_sources = []

            # Retrieve conversation history
            history_rows = self.db.get_messages(session_id)
            prev_history = history_rows[:-1] if history_rows else []

            # Privacy Web Search (DuckDuckGo)
            if web_search:
                if not should_skip_web_search(content):
                    cleaned_q = clean_search_query(content, history=prev_history)
                    if cleaned_q:
                        if self.window:
                            self.window.evaluate_js(f"window.onSearchStatus({json.dumps(f'Searching web for: \"{cleaned_q}\"...')})")
                        try:
                            search_sources = perform_web_search(cleaned_q, max_results=5)
                            if search_sources:
                                search_context_prompt = format_search_context(cleaned_q, search_sources, model)
                                if self.window:
                                    sources_json = json.dumps(search_sources)
                                    self.window.evaluate_js(f"window.onWebSearchResults({sources_json})")
                        except Exception as e:
                            print("Search error:", e)

            # Build messages history for Ollama
            ollama_messages = []

            # If web search returned context, inject as system guidance (or prepend for legacy models)
            is_legacy = any(k in model.lower() for k in ["llama2", "alpaca", "vicuna"])
            if search_context_prompt and not is_legacy:
                ollama_messages.append({"role": "system", "content": search_context_prompt})

            # Check if any attachments contain document text or images
            attached_text_blocks = []
            estimated_attachment_tokens = 0
            for att in attachments:
                if att.get("type") in ["pdf", "text"] and att.get("text"):
                    name = att.get("name", "Document")
                    block = f"--- Document Content: {name} ---\n{att['text']}\n--- End of {name} ---"
                    attached_text_blocks.append(block)
                    estimated_attachment_tokens += len(block) // 3

            for idx, msg in enumerate(history_rows):
                msg_content = msg["content"]
                
                # If this is the last user message, prepend search context for legacy models and append attachments
                if idx == len(history_rows) - 1:
                    if is_legacy and search_context_prompt:
                        msg_content = f"{search_context_prompt}\n\nUser Question:\n{msg_content}"
                    if attached_text_blocks:
                        combined_docs = "\n\n".join(attached_text_blocks)
                        msg_content = f"{combined_docs}\n\nUser Question:\n{msg_content}"

                item = {"role": msg["role"], "content": msg_content}

                # Vision model image attachments
                images = []
                for att in msg.get("attachments", []):
                    if att.get("type") == "image" and att.get("base64"):
                        images.append(att["base64"])
                if images:
                    item["images"] = images

                ollama_messages.append(item)

            accumulated_content = []
            accumulated_thinking = []
            chunk_buffer = []
            chunk_lock = threading.Lock()
            last_flush = [time.time()]

            def flush_chunks():
                with chunk_lock:
                    if not chunk_buffer:
                        return
                    batch = list(chunk_buffer)
                    chunk_buffer.clear()
                    last_flush[0] = time.time()

                if self.window and not self._stop_event.is_set():
                    payload = json.dumps(batch)
                    self.window.evaluate_js(f"window.onStreamBatch({payload})")

            def on_chunk(chunk_data):
                if self._stop_event.is_set():
                    return
                chunk_data["session_id"] = session_id
                if chunk_data["type"] == "content":
                    accumulated_content.append(chunk_data["token"])
                elif chunk_data["type"] == "thinking":
                    accumulated_thinking.append(chunk_data["token"])

                now = time.time()
                with chunk_lock:
                    chunk_buffer.append(chunk_data)
                    should_flush = (now - last_flush[0] >= 0.016) or len(chunk_buffer) >= 6

                if should_flush:
                    flush_chunks()

            def on_complete(metrics):
                flush_chunks()
                full_content = "".join(accumulated_content)
                full_thinking = "".join(accumulated_thinking)

                # Store assistant response in DB
                self.db.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=full_content,
                    thinking_content=full_thinking,
                    metrics=metrics
                )

                if self.window:
                    payload = json.dumps({"session_id": session_id, "metrics": metrics})
                    self.window.evaluate_js(f"window.onStreamComplete({payload})")

                with self._stream_lock:
                    self._is_generating = False

            def on_error(err_str):
                if self.window:
                    payload = json.dumps({"session_id": session_id, "error": str(err_str)})
                    self.window.evaluate_js(f"window.onStreamError({payload})")
                with self._stream_lock:
                    self._is_generating = False

            # Launch streaming
            try:
                target_num_ctx = max(2048, estimated_attachment_tokens + 1024) if estimated_attachment_tokens > 0 else None
                
                self.client.stream_chat(
                    model=model,
                    messages=ollama_messages,
                    thinking_level=thinking_level,
                    num_ctx=target_num_ctx,
                    on_chunk=on_chunk,
                    on_complete=on_complete,
                    on_error=on_error,
                    stop_event=self._stop_event
                )
            finally:
                with self._stream_lock:
                    self._is_generating = False
                
                # Trim WebKit memory
                try:
                    import gi
                    gi.require_version("WebKit2", "4.1")
                    from gi.repository import WebKit2
                    # Run on GLib idle to ensure it executes in the main thread
                    from gi.repository import GLib
                    GLib.idle_add(lambda: WebKit2.WebContext.get_default().clear_cache() or False)
                except Exception:
                    pass

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return {"status": "started"}
