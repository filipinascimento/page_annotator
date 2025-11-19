from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Sequence

from .cli import discover_configs
from .pywebview_launcher import launch as launch_pywebview


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Page Annotator PyWebView launcher")
    parser.add_argument("--config", help="Path to the config file")
    parser.add_argument(
        "--config-dir",
        action="append",
        default=[],
        help="Additional directory to search for configs",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for the Flask server")
    parser.add_argument("--port", type=int, default=5000, help="Port for the Flask server")
    parser.add_argument("--viewer-width", type=int, default=1200, help="Width of the PyWebView windows")
    parser.add_argument("--viewer-height", type=int, default=680, help="Height of the top (page) window")
    parser.add_argument("--panel-height", type=int, default=360, help="Height of the bottom annotation window")
    parser.add_argument("--offset-x", type=int, default=160, help="X position for the windows")
    parser.add_argument("--offset-y", type=int, default=80, help="Y position for the top window")
    parser.add_argument("--vertical-gap", type=int, default=12, help="Gap between viewer and panel windows")
    parser.add_argument("--gui", help="PyWebView GUI backend (qt, cocoa, gtk, etc.)")
    parser.add_argument("--debug", action="store_true", help="Enable PyWebView debug logging")
    parser.add_argument("--list-configs", action="store_true", help="List discovered configs and exit")
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    extra_dirs = [Path(item).expanduser().resolve() for item in args.config_dir]
    configs = discover_configs(extra_dirs)

    if args.list_configs:
        if not configs:
            print("No configs found.")
        else:
            for path in configs:
                print(path)
        return

    if args.config:
        config_path = Path(args.config).expanduser().resolve()
        if not config_path.exists():
            parser.error(f"Config file '{config_path}' not found")
    else:
        if not configs:
            parser.error("No configuration files found. Provide --config explicitly.")
        config_path = configs[0]

    launch_pywebview(
        config=str(config_path),
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
    main(sys.argv[1:])
