"""
ollux — Native Ollama Client Engine
Handles communication with the local Ollama API (localhost:11434).
Streaming, reasoning separation (native + tag based), model lifecycle, and live inference benchmarking.
"""

import json
import time
import requests
from typing import Dict, Any, Optional, Callable


class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host.rstrip("/")

    def check_connection(self) -> Dict[str, Any]:
        """Check if local Ollama daemon is reachable."""
        try:
            r = requests.get(f"{self.host}/api/version", timeout=2)
            if r.status_code == 200:
                data = r.json()
                return {"connected": True, "version": data.get("version", "unknown")}
        except Exception as e:
            return {"connected": False, "error": str(e)}
        return {"connected": False, "error": "Unreachable"}

    def list_models(self) -> list:
        """Fetch all installed models with parsed metadata."""
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            if r.status_code != 200:
                return []
            
            models = []
            for item in r.json().get("models", []):
                size_bytes = item.get("size", 0)
                size_gb = size_bytes / (1024 ** 3)
                size_str = f"{size_gb:.1f} GB" if size_gb >= 1 else f"{size_bytes / (1024 ** 2):.0f} MB"
                
                details = item.get("details", {})
                models.append({
                    "name": item.get("name"),
                    "size": size_str,
                    "size_bytes": size_bytes,
                    "modified_at": item.get("modified_at", ""),
                    "format": details.get("format", ""),
                    "family": details.get("family", ""),
                    "parameter_size": details.get("parameter_size", ""),
                    "quantization_level": details.get("quantization_level", "")
                })
            return models
        except Exception:
            return []

    def pull_model(self, model_name: str, progress_callback: Callable[[Dict[str, Any]], None]) -> bool:
        """Pull a model with live streaming progress."""
        try:
            r = requests.post(
                f"{self.host}/api/pull",
                json={"name": model_name, "stream": True},
                stream=True,
                timeout=1800
            )
            for line in r.iter_lines():
                if line:
                    data = json.loads(line)
                    progress_callback(data)
                    if data.get("status") == "success":
                        return True
            return True
        except Exception as e:
            progress_callback({"status": "error", "error": str(e)})
            return False

    def delete_model(self, model_name: str) -> Dict[str, Any]:
        """Delete an installed model."""
        try:
            r = requests.delete(
                f"{self.host}/api/delete",
                json={"name": model_name},
                timeout=10
            )
            return {"success": r.status_code == 200}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_model_context_length(self, model_name: str) -> int:
        """Fetch model's context window limit from Ollama /api/show or default."""
        if not hasattr(self, "_ctx_cache"):
            self._ctx_cache = {}
        if model_name in self._ctx_cache:
            return self._ctx_cache[model_name]
        try:
            r = requests.post(f"{self.host}/api/show", json={"name": model_name}, timeout=3.0)
            if r.status_code == 200:
                data = r.json()
                info = data.get("model_info", {})
                ctx = next((v for k, v in info.items() if "context_length" in k), None)
                if ctx and isinstance(ctx, (int, float)):
                    self._ctx_cache[model_name] = int(ctx)
                    return int(ctx)
        except Exception:
            pass
        self._ctx_cache[model_name] = 4096
        return 4096

    def stream_chat(
        self,
        model: str,
        messages: list,
        thinking_level: str = "med",
        num_ctx: Optional[int] = None,
        on_chunk: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        stop_event: Optional[Any] = None,
        on_request_ready: Optional[Callable[[requests.Response], None]] = None
    ):
        """
        Stream a chat response from Ollama.
        Supports both native Ollama v0.33+ 'thinking' field and legacy <think>...</think> tags.
        Calculates real-time tokens/sec performance metrics on completion.
        """
        # Map thinking level to sampling parameters
        params = {
            "low": {"temperature": 0.2, "top_p": 0.5, "num_predict": 1024},
            "med": {"temperature": 0.6, "top_p": 0.8, "num_predict": 2048},
            "high": {"temperature": 0.85, "top_p": 0.95, "num_predict": 4096}
        }.get(thinking_level.lower(), {"temperature": 0.6, "top_p": 0.8, "num_predict": 2048})
        
        if num_ctx is not None and num_ctx > 2048:
            params["num_ctx"] = num_ctx

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": params
        }

        try:
            start_wall_time = time.time()
            r = requests.post(f"{self.host}/api/chat", json=payload, stream=True, timeout=300)
            
            if on_request_ready and callable(on_request_ready):
                on_request_ready(r)

            if r.status_code != 200:
                if on_error:
                    on_error(f"Ollama API returned HTTP {r.status_code}: {r.text}")
                return

            in_thinking_block = False
            thinking_buffer = ""
            content_buffer = ""
            pending_tag_buffer = ""
            first_token_time = None
            stopped_early = False
            completed = False

            for line in r.iter_lines():
                if stop_event and stop_event.is_set():
                    stopped_early = True
                    try:
                        r.close()
                    except Exception:
                        pass
                    break

                if not line:
                    continue
                
                chunk = json.loads(line)
                if first_token_time is None:
                    first_token_time = time.time()

                msg = chunk.get("message", {})
                native_thinking = msg.get("thinking", "")
                content_token = msg.get("content", "")

                # 1. Native Ollama v0.33+ thinking tokens
                if native_thinking:
                    thinking_buffer += native_thinking
                    if on_chunk:
                        on_chunk({"type": "thinking", "token": native_thinking})

                # 2. Tag-based thinking (<think>...</think>) inside content (handles split tokens)
                if content_token:
                    pending_tag_buffer += content_token
                    while pending_tag_buffer:
                        if not in_thinking_block:
                            if "<think>" in pending_tag_buffer:
                                parts = pending_tag_buffer.split("<think>", 1)
                                if parts[0]:
                                    content_buffer += parts[0]
                                    if on_chunk:
                                        on_chunk({"type": "content", "token": parts[0]})
                                in_thinking_block = True
                                pending_tag_buffer = parts[1]
                            else:
                                matched_len = 0
                                for k in range(1, min(len(pending_tag_buffer) + 1, 7)):
                                    if "<think>".startswith(pending_tag_buffer[-k:]):
                                        matched_len = k
                                if matched_len > 0:
                                    emit_part = pending_tag_buffer[:-matched_len]
                                    pending_tag_buffer = pending_tag_buffer[-matched_len:]
                                    if emit_part:
                                        content_buffer += emit_part
                                        if on_chunk:
                                            on_chunk({"type": "content", "token": emit_part})
                                    break
                                else:
                                    content_buffer += pending_tag_buffer
                                    if on_chunk:
                                        on_chunk({"type": "content", "token": pending_tag_buffer})
                                    pending_tag_buffer = ""
                        else:
                            if "</think>" in pending_tag_buffer:
                                parts = pending_tag_buffer.split("</think>", 1)
                                if parts[0]:
                                    thinking_buffer += parts[0]
                                    if on_chunk:
                                        on_chunk({"type": "thinking", "token": parts[0]})
                                in_thinking_block = False
                                pending_tag_buffer = parts[1]
                            else:
                                matched_len = 0
                                for k in range(1, min(len(pending_tag_buffer) + 1, 8)):
                                    if "</think>".startswith(pending_tag_buffer[-k:]):
                                        matched_len = k
                                if matched_len > 0:
                                    emit_part = pending_tag_buffer[:-matched_len]
                                    pending_tag_buffer = pending_tag_buffer[-matched_len:]
                                    if emit_part:
                                        thinking_buffer += emit_part
                                        if on_chunk:
                                            on_chunk({"type": "thinking", "token": emit_part})
                                    break
                                else:
                                    thinking_buffer += pending_tag_buffer
                                    if on_chunk:
                                        on_chunk({"type": "thinking", "token": pending_tag_buffer})
                                    pending_tag_buffer = ""

                # Stream termination & performance metrics
                if chunk.get("done"):
                    completed = True

                    # Flush any lingering text from pending_tag_buffer
                    if pending_tag_buffer:
                        if in_thinking_block:
                            thinking_buffer += pending_tag_buffer
                            if on_chunk:
                                on_chunk({"type": "thinking", "token": pending_tag_buffer})
                        else:
                            content_buffer += pending_tag_buffer
                            if on_chunk:
                                on_chunk({"type": "content", "token": pending_tag_buffer})
                        pending_tag_buffer = ""

                    eval_count = chunk.get("eval_count", 0)
                    eval_duration_ns = chunk.get("eval_duration", 0)
                    prompt_eval_count = chunk.get("prompt_eval_count", 0)
                    prompt_eval_duration_ns = chunk.get("prompt_eval_duration", 0)
                    total_duration_ns = chunk.get("total_duration", 0)

                    eval_secs = eval_duration_ns / 1e9 if eval_duration_ns else 0
                    tokens_per_sec = eval_count / eval_secs if eval_secs > 0 else 0
                    
                    prompt_secs = prompt_eval_duration_ns / 1e9 if prompt_eval_duration_ns else 0
                    prompt_tps = prompt_eval_count / prompt_secs if prompt_secs > 0 else 0

                    ttft = (first_token_time - start_wall_time) if first_token_time else 0

                    context_length = self.get_model_context_length(model)
                    total_tokens = prompt_eval_count + eval_count
                    context_used_pct = round((total_tokens / context_length) * 100, 1) if context_length > 0 else 0

                    metrics = {
                        "eval_count": eval_count,
                        "eval_duration_secs": round(eval_secs, 2),
                        "tokens_per_second": round(tokens_per_sec, 2),
                        "prompt_eval_count": prompt_eval_count,
                        "total_tokens": total_tokens,
                        "context_length": context_length,
                        "context_used_pct": context_used_pct,
                        "prompt_tokens_per_second": round(prompt_tps, 2),
                        "time_to_first_token_secs": round(ttft, 2),
                        "total_duration_secs": round(total_duration_ns / 1e9, 2),
                        "has_thinking": len(thinking_buffer.strip()) > 0
                    }

                    if on_complete:
                        on_complete(metrics)
                    break

            # If stopped early before 'done' arrived, finalize cleanly exactly once
            if stopped_early and not completed and on_complete:
                completed = True
                if pending_tag_buffer:
                    if in_thinking_block:
                        thinking_buffer += pending_tag_buffer
                    else:
                        content_buffer += pending_tag_buffer
                    pending_tag_buffer = ""

                elapsed = time.time() - start_wall_time
                metrics = {
                    "eval_count": len(content_buffer.split()),
                    "eval_duration_secs": round(elapsed, 2),
                    "tokens_per_second": 0,
                    "prompt_eval_count": 0,
                    "prompt_tokens_per_second": 0,
                    "time_to_first_token_secs": round((first_token_time - start_wall_time) if first_token_time else 0, 2),
                    "total_duration_secs": round(elapsed, 2),
                    "has_thinking": len(thinking_buffer.strip()) > 0,
                    "stopped": True
                }
                on_complete(metrics)

        except Exception as e:
            if on_error:
                on_error(str(e))
