# Page Annotator

A lightweight Python/Flask application that helps annotate a list of web pages that are stored in a CSV file. The UI dedicates most of the window to the current page and keeps a fixed bar at the bottom for document context and annotation controls.

## Features
- Reads a CSV containing the URLs and metadata you want to review.
- YAML configuration controls which metadata columns are shown and which annotation fields are collected (text, textarea, select, checkbox, list, etc.).
- Displays each target page inside the viewer with previous/next navigation and persistent annotations.
- Supports fields that should be rendered as lists (using your preferred separator) for both context and inputs.
- Detects when pages block `iframe` embedding by inspecting response headers / iframe behavior and automatically falls back to a proxied copy (clearly labeled) that reuses the reviewer’s browser User-Agent so upstream sites serve the same experience; proxied HTML is rewritten with absolute asset links so CSS/images/scripts load correctly.
- Saves annotations (together with the source row) into the file defined in the config so you can resume work at any time.
- Bottom annotation bar can start at your preferred height and, if enabled, can be resized by dragging the divider.
- Remembers the annotator's name (prompted on first load), records it in the output CSV, and auto-saves progress so each reviewer can resume right where they left off.

## Project layout
```
page_annotator/
├── config.yaml                      # Default configuration
├── data/
│   ├── sample_documents.csv         # Sample dataset
│   └── funder_evaluation.csv        # Dataset for funder example
├── examples/
│   ├── basic.yml                    # Basic article reviewer config
│   ├── landscape_review.yml         # Scoring-focused config
│   └── funder_evaluation.yml        # Funder evaluation config (see below)
├── page_annotator/
│   ├── app.py                       # Flask app factory + routes
│   ├── configuration.py             # YAML/config parsing helpers
│   ├── data_store.py                # CSV + annotation persistence
│   ├── static/
│   │   ├── app.js                   # Front-end logic
│   │   └── styles.css               # Layout/styling
│   └── templates/index.html         # Viewer/annotation shell
├── requirements.txt
└── README.md
```

The `examples/` folder contains ready-to-use configs that showcase different workflows. For instance `examples/funder_evaluation.yml` is paired with `data/funder_evaluation.csv` and adds numeric checks for Total/Correct/Wrong funders while showing field variations via horizontal scrolling and clickable OA URLs.

## Configuration
Edit `config.yaml` (or point the app to a different file) to describe your dataset:

```yaml
data_file: data/sample_documents.csv
annotation_output: data/sample_annotations.csv
annotator_column: annotator

viewer:
  url_column: url
  prefer_proxy: false
  auto_proxy_on_block: true
  allow_proxy_toggle: true
  open_original_in_new_tab: true
  detached_window: false  # set true to pop the page into its own browser window

autosave:
  enabled: true
  interval_seconds: 8

# CSV columns shown in the info column
display_fields:
  - column: title
    label: Title
    type: text
  - column: authors
    label: Authors
    type: list
    separator: ";"

# Fields collected from the annotator
annotation_fields:
  - name: relevance
    label: Relevance
    type: select
    options: [High, Medium, Low]
    required: true
  - name: flagged_topics
    label: Flagged topics
    type: list
    separator: ";"

# Fallback separator for list fields when not specified above
default_list_separator: ";"

panel:
  initial_height: 360
  resizable: true
  min_height: 240
  max_height: 520
```

Supported annotation field types: `text`, `textarea`, `number`, `select`, `multiselect`, `checkbox`, and `list`. Display fields accept `text`, `textarea`, `list`, and the richer `link_list` (renders clickable links) and `scroll_list` (shows horizontally scrollable pills—used by the funder evaluation example to inspect `display_names`).

If you run into pages that refuse to render inside an iframe even after enabling the proxy, set `viewer.detached_window: true`. The viewer area will display a message while the actual page opens in a separate browser window that follows you as you navigate entries.

## Running the app
1. (Recommended) create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv # optional but recommended if you are not using conda
   source .venv/bin/activate # optional but recommended if you are not using conda
   pip install -e .
   ```
   Installing in editable mode exposes the `page-annotator` CLI.
2. Launch the server with either a direct path or an interactive picker:
   ```bash
   page-annotator --config config.yaml --host 0.0.0.0 --port 5000
   ```
   Omit `--config` to see a numbered list of discovered configs (including those under `examples/`).
3. Visit `http://localhost:5000` in your browser. Use the bottom bar to review the metadata, fill the annotation form, and navigate with *Prev/Next*. An explicit *Save* button is also provided.

### Optional: launch a Chrome window with relaxed security
Some publishers forbid embedding and block script/CSS loads even through the proxy. You can open a dedicated Chrome instance that disables site isolation with `launch_browser.py`:

```bash
python launch_browser.py
```

The script tries common macOS Chrome paths and starts a fresh profile under `/tmp/page-annotator-chrome` with `--disable-web-security` and related flags, allowing the annotator site to render pages without iframe restrictions. Close the window when finished.

The annotation CSV specified in the config is rewritten every time you save so you can resume later with your previous answers already filled in.

## Handling pages that refuse `iframe`s
Some sites block embedding via headers such as `X-Frame-Options`. When `viewer.auto_proxy_on_block` is enabled (default), the client watches iframe load events and switches to the proxied endpoint whenever a page refuses to render, surfacing a `Proxy mode (blocked)` badge so annotators know what's happening. You can still toggle back manually (if allowed) or disable the behavior by setting `auto_proxy_on_block: false`. Keep in mind that the proxied version cannot rewrite every resource, so relative assets like scripts might still fail. The *Open original* button always launches the URL in a separate browser tab.

## Autosave + annotator identity
On the first visit, the UI asks for the annotator's name and stores it in `localStorage` (and in the annotation CSV via the `annotator_column`). When that reviewer returns and enters/keeps the same name, the app jumps to the first entry they haven't finished yet so they can resume quickly. Autosave is enabled by default (every 8 seconds in the example config) and can be tuned or disabled via the `autosave` block.

## Next steps
- Plug your real CSV/config into `config.yaml`.
- Extend `app.js` or `config.yaml` with additional field types (e.g., radio buttons) if needed.
- Deploy behind a reverse proxy (Gunicorn + nginx) when you are ready to share the tool with teammates.
