"""
ollux — Native Ollama Client Engine
Handles communication with the local Ollama API (localhost:11434).
Streaming, reasoning separation, model lifecycle, and live inference benchmarking.
"""

import json
import time
import requests
from typing import Dict, Any, Generator, Optional, Callable


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
        """Delete an existing model."""
        try:
            r = requests.delete(
                f"{self.host}/api/delete",
                json={"name": model_name},
                timeout=10
            )
            return {"success": r.status_code == 200}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def stream_chat(
        self,
        model: str,
        messages: list,
        thinking_level: str = "med",
        on_chunk: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None
    ):
        """
        Stream a chat response from Ollama.
        Dynamically filters <think>...</think> reasoning tokens from output.
        Calculates real-time tokens/sec performance metrics on completion.
        """
        # Map thinking level to sampling parameters
        params = {
            "low": {"temperature": 0.2, "top_p": 0.5},
            "med": {"temperature": 0.6, "top_p": 0.8},
            "high": {"temperature": 0.85, "top_p": 0.95}
        }.get(thinking_level.lower(), {"temperature": 0.6, "top_p": 0.8})

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": params
        }

        try:
            start_wall_time = time.time()
            r = requests.post(f"{self.host}/api/chat", json=payload, stream=True, timeout=300)
            
            if r.status_code != 200:
                if on_error:
                    on_error(f"Ollama API returned HTTP {r.status_code}: {r.text}")
                return

            in_thinking_block = False
            thinking_buffer = ""
            content_buffer = ""
            first_token_time = None

            for line in r.iter_lines():
                if not line:
                    continue
                
                chunk = json.loads(line)
                if first_token_time is None:
                    first_token_time = time.time()

                msg = chunk.get("message", {})
                token = msg.get("content", "")

                # Handle reasoning / thinking tag splitting
                if "<think>" in token:
                    in_thinking_block = True
                    parts = token.split("<think>", 1)
                    if parts[0] and on_chunk:
                        content_buffer += parts[0]
                        on_chunk({"type": "content", "token": parts[0]})
                    token = parts[1]

                if "</think>" in token:
                    parts = token.split("</think>", 1)
                    thinking_part = parts[0]
                    rest = parts[1]
                    thinking_buffer += thinking_part
                    if on_chunk:
                        on_chunk({"type": "thinking", "token": thinking_part})
                    in_thinking_block = False
                    if rest and on_chunk:
                        content_buffer += rest
                        on_chunk({"type": "content", "token": rest})
                    continue

                if in_thinking_block:
                    thinking_buffer += token
                    if on_chunk:
                        on_chunk({"type": "thinking", "token": token})
                else:
                    content_buffer += token
                    if on_chunk:
                        on_chunk({"type": "content", "token": token})

                # Stream termination & performance metrics
                if chunk.get("done"):
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

                    metrics = {
                        "eval_count": eval_count,
                        "eval_duration_secs": round(eval_secs, 2),
                        "tokens_per_second": round(tokens_per_sec, 2),
                        "prompt_eval_count": prompt_eval_count,
                        "prompt_tokens_per_second": round(prompt_tps, 2),
                        "time_to_first_token_secs": round(ttft, 2),
                        "total_duration_secs": round(total_duration_ns / 1e9, 2),
                        "has_thinking": len(thinking_buffer.strip()) > 0
                    }

                    if on_complete:
                        on_complete(metrics)
                    break

        except Exception as e:
            if on_error:
                on_error(str(e))
