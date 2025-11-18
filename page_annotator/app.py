from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Tuple

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, jsonify, render_template, request
from urllib.parse import quote, urljoin, urlparse

from .configuration import AppConfig
from .data_store import AnnotationDataStore

BLOCKING_XFO = {"deny", "sameorigin"}
DEFAULT_USER_AGENT = "PageAnnotator/1.0"


class AppState:
    def __init__(self, config_path: Path | str):
        self.config_path = Path(config_path)
        self.config = AppConfig.load(self.config_path)
        self.data_store = AnnotationDataStore(self.config)

    def refresh(self) -> None:
        """Reload configuration and data from disk."""
        self.config = AppConfig.load(self.config_path)
        self.data_store = AnnotationDataStore(self.config)


def create_app(config_path: Path | str = "config.yaml") -> Flask:
    state = AppState(config_path)
    base_dir = Path(__file__).parent
    app = Flask(
        __name__,
        static_folder=str(base_dir / "static"),
        template_folder=str(base_dir / "templates"),
    )

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.route("/api/state")
    def api_state() -> Response:
        payload: Dict[str, Any] = {
            "config": state.config.serialize_for_client(),
            "entries": state.data_store.formatted_entries(),
            "annotations": state.data_store.annotations_for_client(),
            "annotators": state.data_store.annotators_for_client(),
        }
        return jsonify(payload)

    @app.route("/api/annotation/<int:entry_id>", methods=["GET", "POST"])
    def annotation(entry_id: int):
        if request.method == "GET":
            annotation_values = state.data_store.annotations.get(entry_id, {})
            annotator_value = state.data_store.annotators.get(entry_id, "")
            return jsonify({"values": annotation_values, "annotator": annotator_value})

        payload = request.get_json(silent=True) or {}
        values = payload.get("values") if isinstance(payload, dict) else None
        if values is None:
            return jsonify({"error": "Missing annotation values"}), 400
        annotator_name = ""
        if isinstance(payload, dict):
            annotator = payload.get("annotator")
            if annotator is not None:
                annotator_name = str(annotator).strip()
        try:
            saved = state.data_store.save_annotation(entry_id, values, annotator=annotator_name)
        except KeyError:
            return jsonify({"error": "Invalid entry id"}), 404
        return jsonify({"values": saved, "annotator": annotator_name})

    @app.route("/api/proxy/<int:entry_id>")
    def proxy(entry_id: int):
        try:
            entry = state.data_store.get_entry(entry_id)
        except KeyError:
            return Response("Unknown entry", status=404)
        target_url = entry["url"]
        upstream_headers = _build_upstream_headers()
        try:
            resp = requests.get(target_url, timeout=15, headers=upstream_headers)
        except requests.RequestException as exc:  # pragma: no cover - network timing errors
            return Response(f"Unable to load proxied content: {exc}", status=502)

        content_type = resp.headers.get("Content-Type", "text/html")
        body = resp.content
        resolved_url = resp.url or target_url
        if "text/html" in content_type:
            rewritten = _rewrite_html(resolved_url, resp)
            if rewritten is not None:
                body = rewritten

        proxied = Response(body, status=resp.status_code)
        proxied.headers["Content-Type"] = content_type
        proxied.headers["X-Frame-Options"] = "SAMEORIGIN"
        return proxied

    @app.route("/api/proxy/resource")
    def proxy_resource():
        target = request.args.get("url")
        if not target:
            return Response("Missing 'url' parameter", status=400)
        if not _is_allowed_url(target):
            return Response("Unsupported URL scheme", status=400)
        upstream_headers = _build_upstream_headers()
        try:
            resp = requests.get(target, timeout=20, headers=upstream_headers, stream=True)
        except requests.RequestException as exc:  # pragma: no cover - network timing errors
            return Response(f"Unable to load resource: {exc}", status=502)

        proxied = Response(resp.content, status=resp.status_code)
        proxied.headers["Content-Type"] = resp.headers.get("Content-Type", "application/octet-stream")
        return proxied

    @app.route("/api/frame-check/<int:entry_id>")
    def frame_check(entry_id: int):
        try:
            entry = state.data_store.get_entry(entry_id)
        except KeyError:
            return jsonify({"error": "Unknown entry"}), 404
        target_url = entry["url"]
        try:
            resp = _fetch_headers(target_url, headers=_build_upstream_headers())
        except requests.RequestException as exc:  # pragma: no cover - network timing errors
            return jsonify({"error": f"Failed to inspect headers: {exc}"}), 502
        blocked, reason = _frame_blocked(resp.headers)
        resp.close()
        payload = {"blocked": blocked}
        if reason:
            payload["reason"] = reason
        return jsonify(payload)

    return app


def _fetch_headers(url: str, headers: Dict[str, str] | None = None) -> requests.Response:
    """Try HEAD first and fall back to GET to read headers."""
    resp = requests.head(url, timeout=10, allow_redirects=True, headers=headers)
    if resp.status_code in {405, 501} or resp.status_code >= 400:
        resp.close()
        resp = requests.get(url, timeout=10, allow_redirects=True, stream=True, headers=headers)
    return resp


def _frame_blocked(headers: Dict[str, str]) -> Tuple[bool, str | None]:
    xfo = headers.get("X-Frame-Options", "")
    if xfo:
        normalized = xfo.split(",")[0].strip().lower()
        if normalized in BLOCKING_XFO:
            return True, f"xfo:{normalized}"
    csp = headers.get("Content-Security-Policy", "")
    if not csp:
        return False, None
    directives = [chunk.strip() for chunk in csp.split(";") if chunk.strip()]
    for directive in directives:
        if not directive.lower().startswith("frame-ancestors"):
            continue
        tokens = directive.split()[1:]
        lowered = [token.lower() for token in tokens]
        if "'none'" in lowered:
            return True, "csp:frame-ancestors-none"
        if "'self'" in lowered:
            return True, "csp:frame-ancestors-self"
        # If directive exists but doesn't explicitly allow us, assume blocked.
        return True, "csp:frame-ancestors-other"
    return False, None


def _build_upstream_headers() -> Dict[str, str]:
    user_agent = request.headers.get("User-Agent") if request else None
    return {"User-Agent": user_agent or DEFAULT_USER_AGENT}


RESOURCE_ATTRS = {
    "a": ["href"],
    "img": ["src", "srcset"],
    "script": ["src"],
    "link": ["href"],
    "iframe": ["src"],
    "source": ["src", "srcset"],
    "video": ["poster", "src"],
    "audio": ["src"],
    "form": ["action"],
}


def _rewrite_html(base_url: str, response: requests.Response) -> bytes | None:
    try:
        encoding = response.encoding or "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
    except Exception:
        return None

    _ensure_base_tag(soup, base_url)

    for tag_name, attributes in RESOURCE_ATTRS.items():
        for tag in soup.find_all(tag_name):
            for attr in attributes:
                if attr not in tag.attrs:
                    continue
                value = tag.attrs.get(attr)
                if not value:
                    continue
                if attr == "srcset":
                    tag[attr] = _rewrite_srcset(value, base_url)
                else:
                    absolute = urljoin(base_url, value)
                    if tag_name == "a" and attr == "href" and _should_proxy_download(absolute):
                        tag[attr] = f"/api/proxy/resource?url={quote(absolute, safe='')}"
                    else:
                        tag[attr] = absolute

    html = soup.encode(encoding)
    return html


def _ensure_base_tag(soup: BeautifulSoup, base_url: str) -> None:
    try:
        head = soup.head
    except AttributeError:
        return
    if not head:
        return
    base_tag = head.find("base")
    if base_tag is None:
        base_tag = soup.new_tag("base", href=base_url)
        head.insert(0, base_tag)
    else:
        base_tag["href"] = base_url


def _rewrite_srcset(value: str, base_url: str) -> str:
    candidates = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        segments = part.split()
        if not segments:
            continue
        url = urljoin(base_url, segments[0])
        descriptor = " ".join(segments[1:])
        if descriptor:
            candidates.append(f"{url} {descriptor}")
        else:
            candidates.append(url)
    return ", ".join(candidates)


def _should_proxy_download(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if not path:
        return False
    return path.endswith(".pdf")


def _is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Page annotation tool")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the YAML config file (default: config.yaml)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
    args = parser.parse_args()

    run_server(args.config, host=args.host, port=args.port, debug=args.debug)


def run_server(config_path: str, host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> None:
    app = create_app(config_path)
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
