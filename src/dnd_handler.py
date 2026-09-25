"""
ollux — Native Linux GTK3/WebKit2GTK Wayland Drag-and-Drop Handler
Provides Wayland protocol-compliant file dropping from Nautilus, Dolphin, Thunar, etc.
Zero deadlock, Gtk.drag_finish compliant, and cross-desktop environment compatible.
"""

import os
import json
import logging
import urllib.parse
from typing import List, Optional, Callable

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

logger = logging.getLogger("ollux.dnd")


def parse_uri_or_path(raw: str) -> Optional[str]:
    """
    Convert a URI (file:///..., file://localhost/...) or raw path into a canonical
    absolute filesystem path. Handles percent-encoding (%20, %23, etc.) and GNOME/GIO standards.
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return None

    # 1. Native GLib filename conversion (GNOME/GTK standard)
    if raw.startswith("file://"):
        try:
            filename, _ = GLib.filename_from_uri(raw)
            if filename:
                return filename
        except Exception:
            pass

        # Fallback to urllib.parse
        try:
            parsed = urllib.parse.urlparse(raw)
            path = urllib.parse.unquote(parsed.path)
            if parsed.netloc and parsed.netloc != "localhost":
                path = f"//{parsed.netloc}{path}"
            return path
        except Exception:
            pass

    # 2. Raw filesystem path
    if raw.startswith("/"):
        return raw

    return None


def extract_paths_from_selection(selection_data: Gtk.SelectionData) -> List[str]:
    """Extract and validate existing filesystem paths from Gtk.SelectionData."""
    paths: List[str] = []

    # 1. Native PyGObject selection_data.get_uris()
    try:
        uris = selection_data.get_uris()
        if uris:
            for uri in uris:
                path = parse_uri_or_path(uri)
                if path and os.path.exists(path) and path not in paths:
                    paths.append(path)
    except Exception as e:
        logger.debug(f"Failed to get_uris from selection data: {e}")

    # 2. Fallback to get_text() for plain-text drops
    if not paths:
        try:
            text = selection_data.get_text()
            if text:
                for line in text.splitlines():
                    path = parse_uri_or_path(line)
                    if path and os.path.exists(path) and path not in paths:
                        paths.append(path)
        except Exception as e:
            logger.debug(f"Failed to get_text from selection data: {e}")

    # 3. Fallback to raw bytes decode
    if not paths:
        try:
            data = selection_data.get_data()
            if data:
                text = data.decode("utf-8", errors="ignore")
                for line in text.splitlines():
                    path = parse_uri_or_path(line)
                    if path and os.path.exists(path) and path not in paths:
                        paths.append(path)
        except Exception as e:
            logger.debug(f"Failed to decode raw selection data: {e}")

    return paths


def find_webview_widget(widget: Gtk.Widget) -> Optional[Gtk.Widget]:
    """Recursively search GTK widget hierarchy for WebKit2.WebView."""
    if widget is None:
        return None
    if "WebView" in type(widget).__name__:
        return widget
    if hasattr(widget, "get_children"):
        for child in widget.get_children():
            res = find_webview_widget(child)
            if res is not None:
                return res
    elif hasattr(widget, "get_child"):
        child = widget.get_child()
        if child is not None:
            res = find_webview_widget(child)
            if res is not None:
                return res
    return None


class WaylandDnDHandler:
    """Manages native GTK3 drag-and-drop integration for PyWebView on Linux Wayland."""

    def __init__(
        self,
        pywebview_window,
        on_files_dropped: Optional[Callable[[List[str]], None]] = None
    ):
        self.pywebview_window = pywebview_window
        self.on_files_dropped = on_files_dropped
        self.webview_widget: Optional[Gtk.Widget] = None
        self.is_hovering: bool = False
        self._installed: bool = False

    def setup(self) -> bool:
        """
        Locate WebKit2.WebView and install GTK drag destination and signals.
        Must execute on the GTK main loop thread.
        """
        if self._installed:
            return True

        # Retrieve WebKit2.WebView instance
        # Method 1: PyWebView internal instances registry
        try:
            from webview.platforms.gtk import BrowserView
            instance = BrowserView.instances.get(self.pywebview_window.uid)
            if instance and hasattr(instance, "webview") and instance.webview is not None:
                self.webview_widget = instance.webview
        except Exception as e:
            logger.debug(f"Could not retrieve webview via BrowserView.instances: {e}")

        # Method 2: Traverse native GTK hierarchy from window.native
        if not self.webview_widget:
            native_win = getattr(self.pywebview_window, "native", None)
            if native_win:
                self.webview_widget = find_webview_widget(native_win)

        if not self.webview_widget:
            logger.error("Failed to locate WebKit2.WebView widget for Wayland DnD setup!")
            return False

        # Register acceptable DnD target entries (text/uri-list and text/plain)
        targets = [
            Gtk.TargetEntry.new("text/uri-list", 0, 0),
            Gtk.TargetEntry.new("text/plain", 0, 1),
        ]

        # Use Gtk.DestDefaults(0) for manual Wayland protocol control
        self.webview_widget.drag_dest_set(
            Gtk.DestDefaults(0),
            targets,
            Gdk.DragAction.COPY
        )

        # Connect GTK Drag-and-Drop signals
        self.webview_widget.connect("drag-motion", self._on_drag_motion)
        self.webview_widget.connect("drag-leave", self._on_drag_leave)
        self.webview_widget.connect("drag-drop", self._on_drag_drop)
        self.webview_widget.connect("drag-data-received", self._on_drag_data_received)

        self._installed = True
        logger.info("Native Wayland GTK3 drag-and-drop handler successfully installed.")
        return True

    def _eval_js_safe(self, script: str):
        """
        Execute JavaScript asynchronously without blocking the GTK MainThread.
        Directly calls WebKit2.WebView.evaluate_javascript to avoid PyWebView's
        GLib.idle_add + Semaphore deadlock on the GTK main loop.
        """
        try:
            if self.webview_widget and hasattr(self.webview_widget, "evaluate_javascript"):
                self.webview_widget.evaluate_javascript(
                    script, -1, None, None, None, None, None
                )
                return
        except Exception as e:
            logger.debug(f"Direct evaluate_javascript fallback: {e}")

        # Fallback: dispatch via thread to avoid blocking GTK event loop
        import threading
        threading.Thread(
            target=lambda: self.pywebview_window.evaluate_js(script),
            daemon=True
        ).start()

    def _notify_hover(self, active: bool):
        val = "true" if active else "false"
        script = f"if (window.setNativeDragActive) {{ window.setNativeDragActive({val}); }}"
        self._eval_js_safe(script)

    def _on_drag_motion(self, widget, context: Gdk.DragContext, x: int, y: int, time: int) -> bool:
        """Acknowledge drag action to the Wayland compositor."""
        target = widget.drag_dest_find_target(context, None)
        if target is not None:
            Gdk.drag_status(context, Gdk.DragAction.COPY, time)
            if not self.is_hovering:
                self.is_hovering = True
                self._notify_hover(True)
            return True
        Gdk.drag_status(context, 0, time)
        return False

    def _on_drag_leave(self, widget, context: Gdk.DragContext, time: int):
        """Reset visual overlay on drag exit or cancel."""
        if self.is_hovering:
            self.is_hovering = False
            self._notify_hover(False)

    def _on_drag_drop(self, widget, context: Gdk.DragContext, x: int, y: int, time: int) -> bool:
        """Acknowledge drop event and request data payload."""
        target = widget.drag_dest_find_target(context, None)
        if target is not None:
            widget.drag_get_data(context, target, time)
            return True
        return False

    def _on_drag_data_received(
        self,
        widget,
        context: Gdk.DragContext,
        x: int,
        y: int,
        selection_data: Gtk.SelectionData,
        info: int,
        time: int
    ):
        """Extract paths, notify UI, and complete the Wayland drop handshake."""
        # Stop propagation to PyWebView's default handler
        try:
            widget.stop_emission_by_name("drag-data-received")
        except Exception:
            pass

        if self.is_hovering:
            self.is_hovering = False
            self._notify_hover(False)

        success = False
        paths: List[str] = []
        try:
            paths = extract_paths_from_selection(selection_data)
            if paths:
                success = True
        except Exception as e:
            logger.error(f"Error processing dropped data: {e}", exc_info=True)
            success = False
        finally:
            # MANDATORY WAYLAND STEP: Complete handshake so file manager releases grab
            Gtk.drag_finish(context, success, False, time)

        if success and paths:
            logger.info(f"Wayland drop received {len(paths)} file(s): {paths}")
            paths_json = json.dumps(paths)
            script = f"if (window.onNativeFilesDropped) {{ window.onNativeFilesDropped({paths_json}); }}"
            self._eval_js_safe(script)
            if self.on_files_dropped:
                try:
                    self.on_files_dropped(paths)
                except Exception as e:
                    logger.error(f"Callback error: {e}", exc_info=True)


def install_gtk_dnd(
    window,
    on_files_dropped: Optional[Callable[[List[str]], None]] = None
) -> WaylandDnDHandler:
    """
    Install Wayland-compatible GTK3 drag-and-drop on a PyWebView window.
    Schedules initialization on the GTK main loop thread via GLib.idle_add
    once the window's 'shown' event fires.
    """
    handler = WaylandDnDHandler(window, on_files_dropped=on_files_dropped)

    def _on_shown():
        GLib.idle_add(handler.setup)

    window.events.shown += _on_shown
    return handler
