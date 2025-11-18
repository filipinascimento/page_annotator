#!/usr/bin/env python3
"""Open a Chrome window with relaxed security flags for the annotator."""

import os
import subprocess
import sys
from pathlib import Path

CHROME_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
]

FLAGS = [
    "--disable-web-security",
    "--disable-site-isolation-trials",
    "--disable-features=IsolateOrigins,site-per-process",
    "--allow-running-insecure-content",
    "--user-data-dir=/tmp/page-annotator-chrome",
]

ANNOTATOR_URL = "http://127.0.0.1:5000"


def main() -> None:
    chrome = None
    for candidate in CHROME_PATHS:
        if Path(candidate).exists():
            chrome = candidate
            break
    if chrome is None:
        print("Could not find Chrome binary. Please install Chrome or update launch_browser.py.")
        sys.exit(1)

    cmd = [chrome, *FLAGS, ANNOTATOR_URL]
    env = os.environ.copy()
    try:
        subprocess.Popen(cmd, env=env)
        print("Launched Chrome with custom flags. Close the browser when finished.")
    except OSError as exc:
        print(f"Failed to launch Chrome: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
