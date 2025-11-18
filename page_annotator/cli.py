from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

from .app import run_server

DEFAULT_CONFIG_LOCATIONS = ["config.yaml", "config.yml"]
DEFAULT_CONFIG_DIRS = [Path.cwd(), Path.cwd() / "examples"]
SUPPORTED_EXTENSIONS = (".yaml", ".yml")


def discover_configs(extra_dirs: Sequence[Path] | None = None) -> List[Path]:
    candidates: List[Path] = []
    search_dirs: List[Path] = []
    for default in DEFAULT_CONFIG_DIRS:
        search_dirs.append(default)
    if extra_dirs:
        search_dirs.extend(extra_dirs)

    for location in DEFAULT_CONFIG_LOCATIONS:
        path = Path(location)
        if path.exists():
            candidates.append(path.resolve())

    seen = {p.resolve() for p in candidates}

    for directory in search_dirs:
        if not directory.exists():
            continue
        for ext in SUPPORTED_EXTENSIONS:
            for path in directory.glob(f"*{ext}"):
                resolved = path.resolve()
                if resolved not in seen:
                    candidates.append(resolved)
                    seen.add(resolved)
    return candidates


def prompt_for_config(configs: Sequence[Path]) -> Path:
    if not configs:
        raise SystemExit("No configuration files found. Provide --config explicitly.")
    print("Select a configuration file:\n")
    for idx, path in enumerate(configs, start=1):
        try:
            rel = path.relative_to(Path.cwd())
        except ValueError:
            rel = path
        print(f"  {idx}) {rel}")
    print("")
    while True:
        choice = input("Enter number: ").strip()
        if not choice:
            continue
        if not choice.isdigit():
            print("Please enter a number from the list.")
            continue
        idx = int(choice)
        if 1 <= idx <= len(configs):
            return configs[idx - 1]
        print("Invalid selection; try again.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Page Annotator CLI")
    parser.add_argument("--config", help="Path to the config file")
    parser.add_argument(
        "--config-dir",
        action="append",
        default=[],
        help="Additional directory to search for configs",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for the Flask server")
    parser.add_argument("--port", type=int, default=5000, help="Port for the Flask server")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")
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

    config_path: Path
    if args.config:
        config_path = Path(args.config).expanduser().resolve()
        if not config_path.exists():
            parser.error(f"Config file '{config_path}' not found")
    else:
        config_path = prompt_for_config(configs)

    run_server(str(config_path), host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main(sys.argv[1:])
