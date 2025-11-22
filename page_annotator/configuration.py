from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class ViewerConfig:
    url_column: str
    prefer_proxy: bool = False
    allow_proxy_toggle: bool = True
    open_original_in_new_tab: bool = True
    auto_proxy_on_block: bool = True
    detached_window: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ViewerConfig":
        if not data:
            raise ValueError("viewer section is missing from the configuration file")
        if "url_column" not in data:
            raise ValueError("viewer.url_column must be provided in the configuration file")
        return cls(
            url_column=data["url_column"],
            prefer_proxy=bool(data.get("prefer_proxy", False)),
            allow_proxy_toggle=bool(data.get("allow_proxy_toggle", True)),
            open_original_in_new_tab=bool(data.get("open_original_in_new_tab", True)),
            auto_proxy_on_block=bool(data.get("auto_proxy_on_block", True)),
            detached_window=bool(data.get("detached_window", False)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PanelConfig:
    initial_height: int = 360
    resizable: bool = False
    min_height: int = 220
    max_height: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PanelConfig":
        if not data:
            return cls()
        initial_height = int(data.get("initial_height", 360))
        min_height = int(data.get("min_height", 180))
        max_height = data.get("max_height")
        max_height_val = int(max_height) if max_height is not None else None
        return cls(
            initial_height=initial_height,
            resizable=bool(data.get("resizable", False)),
            min_height=min_height,
            max_height=max_height_val,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AutosaveConfig:
    enabled: bool = True
    interval_seconds: int = 6

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutosaveConfig":
        if not data:
            return cls()
        interval = int(data.get("interval_seconds", 6))
        if interval < 2:
            interval = 2
        return cls(enabled=bool(data.get("enabled", True)), interval_seconds=interval)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DisplayFieldConfig:
    column: str
    label: str
    type: str = "text"
    separator: Optional[str] = None
    placeholder: Optional[str] = None
    help_text: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DisplayFieldConfig":
        if "column" not in data or "label" not in data:
            raise ValueError("Display fields must include both 'column' and 'label'.")
        return cls(
            column=data["column"],
            label=data["label"],
            type=data.get("type", "text"),
            separator=data.get("separator"),
            placeholder=data.get("placeholder"),
            help_text=data.get("help"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnnotationFieldConfig:
    name: str
    label: str
    type: str = "text"
    options: Optional[List[str]] = None
    required: bool = False
    placeholder: Optional[str] = None
    default: Optional[Any] = None
    separator: Optional[str] = None
    help: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnnotationFieldConfig":
        if "name" not in data or "label" not in data:
            raise ValueError("Annotation fields must include both 'name' and 'label'.")
        options = data.get("options")
        if options is not None and not isinstance(options, list):
            raise ValueError("Annotation field options must be a list when provided.")
        return cls(
            name=data["name"],
            label=data["label"],
            type=data.get("type", "text"),
            options=options,
            required=bool(data.get("required", False)),
            placeholder=data.get("placeholder"),
            default=data.get("default"),
            separator=data.get("separator"),
            help=data.get("help"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AppConfig:
    root_dir: Path
    data_file: Path
    annotation_output: Path
    annotator_column: Optional[str]
    annotator_filter: Optional[List[str]]
    viewer: ViewerConfig
    display_fields: List[DisplayFieldConfig]
    annotation_fields: List[AnnotationFieldConfig]
    panel: PanelConfig
    autosave: AutosaveConfig
    default_list_separator: str = ";"

    @classmethod
    def load(cls, config_path: Path | str) -> "AppConfig":
        path = Path(config_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Config file {path} does not exist")
        with path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        data_file = raw.get("data_file")
        if not data_file:
            raise ValueError("data_file is required in the configuration")
        annotation_output = raw.get("annotation_output")
        if not annotation_output:
            raise ValueError("annotation_output is required in the configuration")

        root_dir = path.parent
        data_path = (root_dir / data_file).expanduser().resolve()
        annotation_output_path = (root_dir / annotation_output).expanduser().resolve()

        viewer_cfg = ViewerConfig.from_dict(raw.get("viewer", {}))
        panel_cfg = PanelConfig.from_dict(raw.get("panel", {}))
        autosave_cfg = AutosaveConfig.from_dict(raw.get("autosave", {}))

        display_fields_raw = raw.get("display_fields", [])
        display_fields = [DisplayFieldConfig.from_dict(item) for item in display_fields_raw]

        annotation_fields_raw = raw.get("annotation_fields", [])
        if not annotation_fields_raw:
            raise ValueError("At least one annotation field is required in the configuration")
        annotation_fields = [AnnotationFieldConfig.from_dict(item) for item in annotation_fields_raw]

        default_list_separator = raw.get("default_list_separator", ";")
        annotator_column = raw.get("annotator_column")
        if annotator_column:
            annotator_column = str(annotator_column).strip()
            if not annotator_column:
                annotator_column = None
        annotator_filter_raw = raw.get("annotator_filter")
        annotator_filter: Optional[List[str]] = None
        if annotator_filter_raw is not None:
            if isinstance(annotator_filter_raw, str):
                filter_values = [annotator_filter_raw]
            elif isinstance(annotator_filter_raw, list):
                filter_values = annotator_filter_raw
            else:
                raise ValueError("annotator_filter must be a string or list of strings.")
            normalized: List[str] = []
            for value in filter_values:
                text = str(value).strip()
                if text:
                    normalized.append(text)
            if normalized:
                if not annotator_column:
                    raise ValueError("annotator_filter requires annotator_column to be set.")
                annotator_filter = normalized

        return cls(
            root_dir=root_dir,
            data_file=data_path,
            annotation_output=annotation_output_path,
            annotator_column=annotator_column,
            annotator_filter=annotator_filter,
            viewer=viewer_cfg,
            display_fields=display_fields,
            annotation_fields=annotation_fields,
            panel=panel_cfg,
            autosave=autosave_cfg,
            default_list_separator=default_list_separator,
        )

    def serialize_for_client(self) -> Dict[str, Any]:
        return {
            "viewer": self.viewer.to_dict(),
            "displayFields": [field.to_dict() for field in self.display_fields],
            "annotationFields": [field.to_dict() for field in self.annotation_fields],
            "defaultListSeparator": self.default_list_separator,
            "panel": self.panel.to_dict(),
            "autosave": self.autosave.to_dict(),
            "annotatorColumn": self.annotator_column,
            "annotatorFilter": self.annotator_filter,
        }

    def annotation_field_names(self) -> List[str]:
        return [field.name for field in self.annotation_fields]
