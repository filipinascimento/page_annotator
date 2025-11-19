from __future__ import annotations

import argparse
import queue
import threading
import time
import webbrowser
from typing import Dict, Optional

import webview
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from page_annotator.app import create_app


class FlaskServerThread(threading.Thread):
    """Run the Flask app in a background thread so Playwright can host the viewer."""

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


def parse_args() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PyWebView annotation window with a Playwright-driven page viewer."
    )
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML config file.")
    parser.add_argument("--host", default="127.0.0.1", help="Host for the Flask backend.")
    parser.add_argument("--port", type=int, default=5000, help="Port for the Flask backend.")
    parser.add_argument("--viewer-width", type=int, default=1200, help="Width of the viewer window.")
    parser.add_argument("--viewer-height", type=int, default=760, help="Height of the viewer window.")
    parser.add_argument("--panel-height", type=int, default=360, help="Height of the annotation window.")
    parser.add_argument("--offset-x", type=int, default=200, help="X coordinate for both windows.")
    parser.add_argument("--offset-y", type=int, default=80, help="Y coordinate for the viewer window.")
    parser.add_argument("--vertical-gap", type=int, default=20, help="Gap between viewer and annotation windows.")
    parser.add_argument("--chromium-path", help="Optional path to a Chromium/Chrome executable.")
    parser.add_argument(
        "--extra-browser-arg",
        action="append",
        default=[],
        help="Additional Chromium argument (repeatable).",
    )
    parser.add_argument("--debug", action="store_true", help="Enable PyWebView debug logging.")
    return parser


def compute_layout(
    viewer_width: int,
    viewer_height: int,
    panel_height: int,
    offset_x: int,
    offset_y: int,
    gap: int,
) -> Dict[str, int]:
    return {
        "viewer_width": viewer_width,
        "viewer_height": viewer_height,
        "panel_height": panel_height,
        "viewer_x": offset_x,
        "viewer_y": offset_y,
        "panel_x": offset_x,
        "panel_y": offset_y + viewer_height + gap,
    }


class PlaywrightController:
    def __init__(self, page):
        self.page = page

    def show_entry(self, payload: Dict[str, str]) -> bool:
        url = payload.get("url") or payload.get("proxyUrl") or payload.get("originalUrl")
        if not url:
            return False
        try:
            self.page.goto(url, wait_until="domcontentloaded")
            return True
        except Exception:
            return False

    def browser_back(self) -> bool:
        try:
            resp = self.page.go_back(wait_until="domcontentloaded")
            return resp is not None
        except Exception:
            return False

    def browser_forward(self) -> bool:
        try:
            resp = self.page.go_forward(wait_until="domcontentloaded")
            return resp is not None
        except Exception:
            return False

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
        script = """
        (term, forward) => {
          try {
            if (!term) return false;
            const backwards = !forward;
            if (!window.find(term, false, backwards, true, false, true, false)) {
              return false;
            }
            const styleId = "__playwright-search-highlight";
            if (!document.getElementById(styleId)) {
              const style = document.createElement("style");
              style.id = styleId;
              style.textContent = "mark.__playwright-search-hit { background:#f97316; color:#fff; padding:0 2px; border-radius:2px; }";
              document.head && document.head.appendChild(style);
            }
            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0) {
              return true;
            }
            const range = selection.getRangeAt(0).cloneRange();
            const mark = document.createElement("mark");
            mark.className = "__playwright-search-hit";
            mark.textContent = range.toString();
            range.deleteContents();
            range.insertNode(mark);
            mark.scrollIntoView({behavior: "smooth", block: "center"});
            setTimeout(() => {
              if (mark && mark.parentNode) {
                const textNode = document.createTextNode(mark.textContent);
                mark.parentNode.replaceChild(textNode, mark);
              }
            }, 1500);
            return true;
          } catch (err) {
            return false;
          }
        }
        """
        try:
            return bool(self.page.evaluate(script, term, forward))
        except Exception:
            return False


class PlaywrightWorker(threading.Thread):
    def __init__(
        self,
        layout: Dict[str, int],
        chromium_path: Optional[str],
        extra_args: Optional[list[str]],
    ):
        super().__init__(daemon=True)
        self.layout = layout
        self.chromium_path = chromium_path
        self.extra_args = extra_args or []
        self.queue: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.stopped = threading.Event()

    def run(self) -> None:
        viewer_args = [
            f"--window-size={self.layout['viewer_width']},{self.layout['viewer_height']}",
            f"--window-position={self.layout['viewer_x']},{self.layout['viewer_y']}",
            "--disable-web-security",
            "--disable-site-isolation-trials",
            "--allow-insecure-localhost",
        ]
        viewer_args.extend(self.extra_args)
        with sync_playwright() as playwright:
            browser_kwargs = {"headless": False, "args": viewer_args}
            if self.chromium_path:
                browser_kwargs["executable_path"] = self.chromium_path
            browser = playwright.chromium.launch(**browser_kwargs)
            page = browser.new_page()
            controller = PlaywrightController(page)
            self.ready.set()
            while True:
                command, args, response = self.queue.get()
                if command == "__quit__":
                    response.put(True)
                    break
                try:
                    result = getattr(controller, command)(*args)
                except Exception:
                    result = False
                response.put(result)
            browser.close()
        self.stopped.set()

    def call(self, method: str, *args):
        if not self.ready.wait(timeout=10):
            return False
        response: queue.Queue = queue.Queue()
        self.queue.put((method, args, response))
        return response.get()

    def stop(self) -> None:
        response: queue.Queue = queue.Queue()
        self.queue.put(("__quit__", (), response))
        response.get()
        self.join(timeout=5)


class PlaywrightBridge:
    """Forward PyWebView JS API calls to the Playwright worker."""

    def __init__(self, worker: PlaywrightWorker):
        self.worker = worker

    def show_entry(self, payload: Dict[str, str]) -> bool:
        return self.worker.call("show_entry", payload)

    def browser_back(self) -> bool:
        return self.worker.call("browser_back")

    def browser_forward(self) -> bool:
        return self.worker.call("browser_forward")

    def open_external(self, url: str) -> bool:
        return self.worker.call("open_external", url)

    def search_page(self, term: str, forward: bool = True) -> bool:
        return self.worker.call("search_page", term, forward)


def wait_for_server(base_url: str, timeout: float = 15.0) -> bool:
    import requests

    deadline = time.time() + timeout
    probe = f"{base_url.rstrip('/')}/api/state"
    while time.time() < deadline:
        try:
            resp = requests.get(probe, timeout=2)
            if resp.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.3)
    return False


def launch(
    config: str = "config.yaml",
    host: str = "127.0.0.1",
    port: int = 5000,
    viewer_width: int = 1200,
    viewer_height: int = 760,
    panel_height: int = 360,
    offset_x: int = 200,
    offset_y: int = 80,
    vertical_gap: int = 20,
    chromium_path: Optional[str] = None,
    extra_browser_args: Optional[list[str]] = None,
    debug: bool = False,
) -> None:
    layout = compute_layout(viewer_width, viewer_height, panel_height, offset_x, offset_y, vertical_gap)
    server = FlaskServerThread(config, host, port)
    server.start()
    base_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    base_url = f"http://{base_host}:{port}"
    if not wait_for_server(base_url):
        server.shutdown()
        raise SystemExit("The Flask backend did not start in time.")

    try:
        worker = PlaywrightWorker(layout, chromium_path, extra_browser_args)
        worker.start()
        if not worker.ready.wait(timeout=10):
            raise RuntimeError("Playwright viewer failed to start")

        bridge = PlaywrightBridge(worker)

        webview.create_window(
            "Page Annotator",
            url=base_url,
            width=layout["viewer_width"],
            height=layout["panel_height"],
            x=layout["panel_x"],
            y=layout["panel_y"],
            resizable=True,
            min_size=(600, 320),
            js_api=bridge,
        )

        try:
            webview.start(debug=debug)
        finally:
            worker.stop()
    finally:
        server.shutdown()


def main() -> None:
    parser = parse_args()
    args = parser.parse_args()
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
        chromium_path=args.chromium_path,
        extra_browser_args=args.extra_browser_arg,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
