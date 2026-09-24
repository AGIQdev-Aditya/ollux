"""
ollux — PyWebView JavaScript Bridge API
Exposes secure native backend functions to the frontend web application.
Handles asynchronous streaming, threading, file dialogs, and SQLite persistence.
"""

import os
import json
import threading
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
        self._stop_requested = False

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
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=('All files (*.*)', 'PDF (*.pdf)', 'Images (*.png;*.jpg;*.jpeg;*.webp)', 'Text / Code (*.txt;*.py;*.js;*.md;*.json;*.cpp;*.c;*.sh)')
        )
        return list(result) if result else []

    def parse_attachment(self, filepath: str) -> Optional[Dict[str, Any]]:
        """Extract text or encode image from file path."""
        return process_file(filepath)

    # --- Chat Streaming & Web Search ---

    def stop_generation(self):
        """Signal generation loop to halt."""
        self._stop_requested = True
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
        if self._is_generating:
            return {"status": "busy"}

        self._is_generating = True
        self._stop_requested = False
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

            # Privacy Web Search (DuckDuckGo)
            if web_search:
                if not should_skip_web_search(content):
                    cleaned_q = clean_search_query(content)
                    if self.window:
                        self.window.evaluate_js(f"window.onSearchStatus({json.dumps(f'Searching web for: \"{cleaned_q}\"...')})")
                    try:
                        search_sources = perform_web_search(content, max_results=5)
                        if search_sources:
                            search_context_prompt = format_search_context(content, search_sources, model)
                            if self.window:
                                sources_json = json.dumps(search_sources)
                                self.window.evaluate_js(f"window.onWebSearchResults({sources_json})")
                    except Exception as e:
                        print("Search error:", e)

            # Build messages history for Ollama
            history_rows = self.db.get_messages(session_id)
            ollama_messages = []

            # If web search returned context, inject as system guidance
            if search_context_prompt:
                ollama_messages.append({"role": "system", "content": search_context_prompt})

            # Check if any attachments contain document text or images
            attached_text_blocks = []
            for att in attachments:
                if att.get("type") in ["pdf", "text"] and att.get("text"):
                    name = att.get("name", "Document")
                    attached_text_blocks.append(f"--- Document Content: {name} ---\n{att['text']}\n--- End of {name} ---")

            for idx, msg in enumerate(history_rows):
                msg_content = msg["content"]
                
                # If this is the last user message, append attached document text
                if idx == len(history_rows) - 1 and attached_text_blocks:
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

            def on_chunk(chunk_data):
                if self._stop_requested:
                    return
                if chunk_data["type"] == "content":
                    accumulated_content.append(chunk_data["token"])
                elif chunk_data["type"] == "thinking":
                    accumulated_thinking.append(chunk_data["token"])

                if self.window:
                    payload = json.dumps(chunk_data)
                    self.window.evaluate_js(f"window.onStreamChunk({payload})")

            def on_complete(metrics):
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
                    payload = json.dumps(metrics)
                    self.window.evaluate_js(f"window.onStreamComplete({payload})")

                self._is_generating = False

            def on_error(err_str):
                if self.window:
                    self.window.evaluate_js(f"window.onStreamError({json.dumps(err_str)})")
                self._is_generating = False

            # Launch streaming
            self.client.stream_chat(
                model=model,
                messages=ollama_messages,
                thinking_level=thinking_level,
                on_chunk=on_chunk,
                on_complete=on_complete,
                on_error=on_error
            )

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return {"status": "started"}
