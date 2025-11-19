from __future__ import annotations

import argparse
import json
import threading
import time
import webbrowser
from typing import Dict, Optional

import requests
import webview
from werkzeug.serving import make_server

from page_annotator.app import create_app

webview.settings['ALLOW_DOWNLOADS'] = True

class FlaskServerThread(threading.Thread):
    """Run the Flask app in a background thread so PyWebView can host the UI."""

    def __init__(self, config_path: str, host: str, port: int):
        super().__init__(daemon=True)
        overrides: Dict[str, Dict[str, bool]] = {"viewer": {"detached_window": True}}
        app = create_app(config_path, overrides=overrides)
        self._server = make_server(host, port, app)
        self._ctx = app.app_context()
        self._ctx.push()

    def run(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._ctx.pop()


class ViewerBridge:
    """Bridge exposed to the annotation window to control the viewer pane."""

    def __init__(self, viewer_window: webview.Window):
        self.viewer_window = viewer_window
        self.default_title = "Page Viewer"

    def show_entry(self, payload: Dict[str, str] | None = None) -> bool:
        if not payload:
            return False
        target = payload.get("url")
        title = payload.get("title") or payload.get("originalUrl") or payload.get("original_url")
        return self._load_url(target, title)

    def open_url(self, url: str, title: str | None = None) -> bool:
        return self._load_url(url, title)

    def browser_back(self) -> bool:
        return self._evaluate_js("history.back();")

    def browser_forward(self) -> bool:
        return self._evaluate_js("history.forward();")

    def reload_page(self) -> bool:
        return self._evaluate_js("history.go(0);")

    def open_external(self, url: str) -> bool:
        if not url:
            return False
        try:
            webbrowser.open(url)
            return True
        except Exception:
            return False

    def search_page(self, term: str, forward: bool = True) -> bool:
        if not term:
            return False
        try:
            query = json.dumps(term)
        except Exception:
            query = json.dumps(str(term))
        backwards = "true" if not forward else "false"
        script = f"""
(function() {{
  try {{
    var term = {query};
    if (!term) return false;
    var backwards = {backwards};
    var found = window.find(term, false, backwards, true, false, true, false);
    if (!found) return false;
    var styleId = "__annotator-search-style";
    if (!document.getElementById(styleId)) {{
      var style = document.createElement("style");
      style.id = styleId;
      style.textContent = "mark.__annotator-search-hit {{ background:#f97316; color:#fff; padding:0 2px; border-radius:2px; }}";
      document.head && document.head.appendChild(style);
    }}
    var selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return true;
    var activeRange = selection.getRangeAt(0).cloneRange();
    var mark = document.createElement("mark");
    mark.className = "__annotator-search-hit";
    mark.textContent = activeRange.toString();
    activeRange.deleteContents();
    activeRange.insertNode(mark);
    mark.scrollIntoView({{behavior: "smooth", block: "center"}});
    window.setTimeout(function() {{
      if (mark && mark.parentNode) {{
        var textNode = document.createTextNode(mark.textContent);
        mark.parentNode.replaceChild(textNode, mark);
      }}
    }}, 1500);
    return true;
  }} catch (err) {{
    return false;
  }}
}})();
"""
        return self._evaluate_js(script)

    def search_page(self, term: str, forward: bool = True) -> bool:
        if not term:
            return False
        try:
            query = json.dumps(term)
        except Exception:
            query = json.dumps(str(term))
        backwards = "false" if forward else "true"
        script = f"window.find({query}, false, {backwards}, true, false, true, false);"
        return self._evaluate_js(script)

    def _load_url(self, url: str | None, title: str | None) -> bool:
        if not url:
            return False
        try:
            self.viewer_window.load_url(url)
            page_title = title or url
            if page_title:
                self.viewer_window.set_title(f"{self.default_title} — {page_title}")
            return True
        except Exception:
            return False

    def _evaluate_js(self, script: str) -> bool:
        try:
            self.viewer_window.evaluate_js(script)
            return True
        except Exception:
            return False


def wait_for_server(base_url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    probe_url = f"{base_url.rstrip('/')}/api/state"
    while time.time() < deadline:
        try:
            resp = requests.get(probe_url, timeout=2)
            if resp.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.3)
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the Page Annotator UI inside PyWebView.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML config file.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the Flask backend.")
    parser.add_argument("--port", type=int, default=5000, help="Port for the Flask backend.")
    parser.add_argument("--viewer-width", type=int, default=1200, help="Width of each PyWebView window.")
    parser.add_argument("--viewer-height", type=int, default=680, help="Height of the top viewer window.")
    parser.add_argument("--panel-height", type=int, default=360, help="Height of the annotation window.")
    parser.add_argument("--offset-x", type=int, default=160, help="X position for the paired windows.")
    parser.add_argument("--offset-y", type=int, default=80, help="Y position for the viewer window.")
    parser.add_argument("--vertical-gap", type=int, default=12, help="Gap between viewer and annotation windows.")
    parser.add_argument("--gui", help="Explicit PyWebView GUI backend (qt, cocoa, gtk, etc.).")
    parser.add_argument("--debug", action="store_true", help="Enable PyWebView debug logging.")
    return parser.parse_args()


def compute_window_layout(params: Dict[str, int]) -> Dict[str, int]:
    screen = webview.screens[0] if getattr(webview, "screens", None) else None
    width = params["viewer_width"]
    viewer_height = params["viewer_height"]
    panel_height = params["panel_height"]
    gap = params["vertical_gap"]
    offset_x = params["offset_x"]
    offset_y = params["offset_y"]

    if screen:
        safe_margin = 80
        available_width = max(600, screen.width - 40)
        available_height = max(400, screen.height - safe_margin)
        if width > available_width:
            width = available_width
        total_height = viewer_height + gap + panel_height
        if total_height > available_height:
            scale = available_height / total_height
            viewer_height = max(320, int(viewer_height * scale))
            panel_height = max(260, int(panel_height * scale))
            gap = max(6, int(gap * scale))
            total_height = viewer_height + gap + panel_height
        min_x = screen.x + 20
        max_x = screen.x + screen.width - width - 20
        offset_x = max(min_x, min(offset_x, max_x))
        min_y = screen.y + 20
        max_y = screen.y + screen.height - total_height - 20
        if max_y < min_y:
            max_y = min_y
        offset_y = max(min_y, min(offset_y, max_y))

    return {
        "width": width,
        "viewer_height": viewer_height,
        "panel_height": panel_height,
        "gap": gap,
        "offset_x": offset_x,
        "viewer_y": offset_y,
        "panel_y": offset_y + viewer_height + gap,
    }


def arrange_windows(viewer: webview.Window, annotator: webview.Window, layout: Dict[str, int]) -> None:
    width = layout["width"]
    viewer_height = layout["viewer_height"]
    panel_height = layout["panel_height"]
    offset_x = layout["offset_x"]
    viewer_y = layout["viewer_y"]
    panel_y = layout["panel_y"]
    viewer.resize(width, viewer_height)
    viewer.move(offset_x, viewer_y)
    annotator.resize(width, panel_height)
    annotator.move(offset_x, panel_y)


def launch(
    config: str = "config.yaml",
    host: str = "127.0.0.1",
    port: int = 5000,
    viewer_width: int = 1200,
    viewer_height: int = 680,
    panel_height: int = 360,
    offset_x: int = 160,
    offset_y: int = 80,
    vertical_gap: int = 12,
    gui: Optional[str] = None,
    debug: bool = False,
) -> None:
    params = {
        "viewer_width": viewer_width,
        "viewer_height": viewer_height,
        "panel_height": panel_height,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "vertical_gap": vertical_gap,
    }
    layout = compute_window_layout(params)
    server = FlaskServerThread(config, host, port)
    server.start()
    base_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    base_url = f"http://{base_host}:{port}"

    if not wait_for_server(base_url):
        server.shutdown()
        raise SystemExit("The Flask backend did not start in time.")

    viewer_window = webview.create_window(
        "Page Viewer",
        url="about:blank",
        width=layout["width"],
        height=layout["viewer_height"],
        x=layout["offset_x"],
        y=layout["viewer_y"],
        resizable=True,
        text_select=True,
        min_size=(480, 320),
    )
    bridge = ViewerBridge(viewer_window)
    annotator_window = webview.create_window(
        "Page Annotator",
        url=base_url,
        width=layout["width"],
        height=layout["panel_height"],
        x=layout["offset_x"],
        y=layout["panel_y"],
        resizable=True,
        on_top=True,
        min_size=(480, 240),
        js_api=bridge,
    )

    def on_startup():
        arrange_windows(viewer_window, annotator_window, layout)

    try:
        webview.start(on_startup, gui=gui, debug=debug, user_agent=None)
    finally:
        server.shutdown()


def main() -> None:
    args = parse_args()
    launch(
        config=args.config,
        host=args.host,
        port=args.port,
        viewer_width=args.viewer_width,
        viewer_height=args.viewer_height,
        panel_height=args.panel_height,
        offset_x=args.offset_x,
        offset_y=args.offset_y,
        vertical_gap=args.vertical_gap,
        gui=args.gui,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
