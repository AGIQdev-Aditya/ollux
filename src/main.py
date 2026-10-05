"""
ollux — Native Linux Desktop Client for Ollama
Main entry point and window manager.
"""

import os
import sys
import signal

# Ensure clean termination on SIGINT (Ctrl+C)
signal.signal(signal.SIGINT, signal.SIG_DFL)

# Critical stability fix for WebKitWebProcess on Linux hybrid Intel/NVIDIA Wayland systems
# Disables DMABUF renderer sharing that causes SIGABRT on NVIDIA proprietary drivers
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
import logging
import webview

# Configure WebKit2 and GTK3 environment
try:
    import gi
    try:
        gi.require_version("WebKit2", "4.1")
    except ValueError:
        try:
            gi.require_version("WebKit2", "4.0")
        except ValueError:
            pass
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    # Enforce dark theme for GTK window title bar across GNOME, KDE, XFCE
    gtk_settings = Gtk.Settings.get_default()
    if gtk_settings:
        gtk_settings.set_property("gtk-application-prefer-dark-theme", True)
except Exception:
    pass

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import Database
from src.ollama_client import OllamaClient
from src.api import OlluxAPI
from src.dnd_handler import install_gtk_dnd


def is_composited_environment() -> bool:
    """Detect if current Linux display screen supports native RGBA window compositing."""
    try:
        from gi.repository import Gdk
        screen = Gdk.Screen.get_default()
        if screen is None:
            return False
        return bool(screen.is_composited() and screen.get_rgba_visual())
    except Exception:
        return False


def main():
    # Initialize Core Engines
    db = Database()
    client = OllamaClient()
    api = OlluxAPI(db, client)

    ui_index_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "ui", "index.html"))

    icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "ollux.png"))

    # Detect Compositor (Wayland, GNOME, KDE, Hyprland, Sway, picom vs non-composited X11/i3/XFCE)
    composited = is_composited_environment()

    # Install GTK transparency style provider for seamless compositor diffusion if supported
    if composited:
        try:
            from gi.repository import Gtk, Gdk
            provider = Gtk.CssProvider()
            provider.load_from_data(b"""
                window, GtkWindow, .background, scrolledwindow, GtkScrolledWindow {
                    background-color: transparent;
                    background-image: none;
                }
            """)
            screen = Gdk.Screen.get_default()
            if screen:
                Gtk.StyleContext.add_provider_for_screen(
                    screen,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10
                )
        except Exception:
            pass

    # Create Native WebKit2GTK Window with native RGBA transparency on composited environments,
    # or solid opaque dark surface on non-composited X11 (XFCE, Openbox, i3 without picom, VMs).
    target_url = f"file://{ui_index_path}" if composited else f"file://{ui_index_path}?composited=0"
    window = webview.create_window(
        title="ollux",
        url=target_url,
        js_api=api,
        width=1120,
        height=760,
        min_size=(740, 520),
        transparent=composited,
        background_color="#0f121a",
        text_select=True
    )
    api.set_window(window)

    # Attach Native Wayland GTK Drag-and-Drop Handler
    install_gtk_dnd(window)

    def _on_closed():
        """Ensure all background threads and processes exit cleanly on window close."""
        try:
            api.stop_generation()
        except Exception:
            pass
        os._exit(0)

    window.events.closed += _on_closed

    # Start PyWebView with GTK backend (Wayland native)
    webview.start(
        gui="gtk",
        debug=("--debug" in sys.argv),
        icon=icon_path if os.path.exists(icon_path) else None
    )


if __name__ == "__main__":
    main()
