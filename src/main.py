"""
ollux — Native Linux Desktop Client for Ollama
Main entry point and window manager.
"""

import os
import sys

# Critical stability fix for WebKitWebProcess on Linux hybrid Intel/NVIDIA Wayland systems
# Disables DMABUF renderer sharing that causes SIGABRT on NVIDIA proprietary drivers
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
import logging
import webview

# Suppress benign PyWebView GTK teardown warnings when window is closed
class PyWebViewExitFilter(logging.Filter):
    def filter(self, record):
        return "window.native" not in record.getMessage()

logging.getLogger("pywebview").addFilter(PyWebViewExitFilter())

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import Database
from src.ollama_client import OllamaClient
from src.api import OlluxAPI
from src.dnd_handler import install_gtk_dnd


def main():
    # Initialize Core Engines
    db = Database()
    client = OllamaClient()
    api = OlluxAPI(db, client)

    ui_index_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "ui", "index.html"))

    # Create Native WebKit2GTK Window
    window = webview.create_window(
        title="ollux",
        url=f"file://{ui_index_path}",
        js_api=api,
        width=1120,
        height=760,
        min_size=(740, 520),
        background_color="#0a0e14",
        text_select=True
    )
    api.set_window(window)

    # Attach Native Wayland GTK Drag-and-Drop Handler
    install_gtk_dnd(window)

    # Start PyWebView with GTK backend (Wayland native)
    webview.start(gui="gtk", debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
