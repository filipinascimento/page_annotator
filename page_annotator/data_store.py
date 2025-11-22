from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .configuration import AppConfig

ENTRY_ID_COLUMN = "entry_id"


class AnnotationDataStore:
    """Loads dataset rows and keeps track of annotations."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.entries: List[Dict[str, Any]] = []
        self._entry_map: Dict[int, Dict[str, Any]] = {}
        self.annotations: Dict[int, Dict[str, Any]] = {}
        self.annotators: Dict[int, str] = {}
        self.csv_fieldnames: List[str] = []
        self._visible_entry_ids: Optional[List[int]] = None
        self._visible_entry_id_set: Optional[Set[int]] = None
        self._allowed_annotators: Optional[Set[str]] = (
            {value.lower() for value in config.annotator_filter} if config.annotator_filter else None
        )

        self._load_entries()
        self._apply_visibility_filter()
        self._seed_annotations_from_source()
        self._load_existing_annotations()

    def _load_entries(self) -> None:
        data_path = self.config.data_file
        if not data_path.exists():
            raise FileNotFoundError(f"Data file {data_path} was not found")
        with data_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise ValueError("The provided CSV file does not contain a header row")
            self.csv_fieldnames = reader.fieldnames
            if (
                self.config.annotator_filter
                and self.config.annotator_column
                and self.config.annotator_column not in self.csv_fieldnames
            ):
                raise ValueError(
                    f"annotator_column '{self.config.annotator_column}' was not found in {data_path} "
                    "but annotator_filter is enabled."
                )
            for idx, row in enumerate(reader):
                url_value = row.get(self.config.viewer.url_column)
                if not url_value:
                    raise ValueError(
                        f"Row {idx + 1} is missing the URL column '{self.config.viewer.url_column}'"
                    )
                entry = {
                    "id": idx,
                    "url": url_value,
                    "data": row,
                }
                self.entries.append(entry)
                self._entry_map[idx] = entry
        if not self.entries:
            raise ValueError("No rows were loaded from the data CSV")

    def _apply_visibility_filter(self) -> None:
        if not self._allowed_annotators or not self.config.annotator_column:
            return
        visible_ids: List[int] = []
        for entry in self.entries:
            assigned = entry["data"].get(self.config.annotator_column, "")
            if self._annotator_matches_filter(assigned):
                visible_ids.append(entry["id"])
        self._visible_entry_ids = visible_ids
        self._visible_entry_id_set = set(visible_ids)

    def _annotator_matches_filter(self, raw_value: Any) -> bool:
        if not self._allowed_annotators:
            return True
        for token in self._split_annotator_values(raw_value):
            if token.lower() in self._allowed_annotators:
                return True
        return False

    def _split_annotator_values(self, value: Any) -> List[str]:
        if value is None:
            return []
        text = str(value).strip()
        if not text:
            return []
        if any(delim in text for delim in (";", ",", "|", "\n")):
            tokens = re.split(r"[;,|\n]+", text)
        else:
            tokens = [text]
        return [token.strip() for token in tokens if token and token.strip()]

    def _seed_annotations_from_source(self) -> None:
        for entry in self.entries:
            row = entry["data"]
            prefilled: Dict[str, Any] = {}
            for field in self.config.annotation_fields:
                if field.name not in row:
                    continue
                raw_value = row.get(field.name)
                if raw_value is None:
                    continue
                value = raw_value.strip() if isinstance(raw_value, str) else raw_value
                if value == "":
                    continue
                prefilled[field.name] = value
            if prefilled:
                self.annotations[entry["id"]] = prefilled
            if self.config.annotator_column:
                annotator_value = row.get(self.config.annotator_column)
                if annotator_value is None:
                    continue
                cleaned = annotator_value.strip() if isinstance(annotator_value, str) else annotator_value
                if cleaned:
                    self.annotators[entry["id"]] = str(cleaned)

    def _load_existing_annotations(self) -> None:
        output_path = self.config.annotation_output
        if not output_path.exists():
            return
        with output_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or ENTRY_ID_COLUMN not in reader.fieldnames:
                return
            for row in reader:
                try:
                    entry_id = int(row.get(ENTRY_ID_COLUMN, "").strip())
                except ValueError:
                    continue
                annotation_values = {
                    field.name: row.get(field.name, "")
                    for field in self.config.annotation_fields
                }
                self.annotations[entry_id] = annotation_values
                if self.config.annotator_column:
                    self.annotators[entry_id] = row.get(self.config.annotator_column, "")

    def get_entry(self, entry_id: int) -> Dict[str, Any]:
        if entry_id not in self._entry_map:
            raise KeyError(f"Invalid entry id {entry_id}")
        return self._entry_map[entry_id]

    def formatted_entries(self) -> List[Dict[str, Any]]:
        entries = (
            self.entries
            if self._visible_entry_ids is None
            else [self._entry_map[i] for i in self._visible_entry_ids if i in self._entry_map]
        )
        return [
            {
                "id": entry["id"],
                "url": entry["url"],
                "data": entry["data"],
            }
            for entry in entries
        ]

    def save_annotation(
        self, entry_id: int, payload: Dict[str, Any], annotator: Optional[str] = None
    ) -> Dict[str, Any]:
        _ = self.get_entry(entry_id)
        if not self._is_entry_visible(entry_id):
            raise KeyError(f"Entry {entry_id} is not accessible in this configuration")
        prepared: Dict[str, Any] = {}
        for field in self.config.annotation_fields:
            value = payload.get(field.name)
            if isinstance(value, list):
                prepared[field.name] = self._join_list(field, value)
            else:
                prepared[field.name] = value if value is not None else ""
        self.annotations[entry_id] = prepared
        if self.config.annotator_column is not None:
            self.annotators[entry_id] = annotator or ""
        self._persist_annotations()
        return prepared

    def _join_list(self, field, values: List[str]) -> str:
        separator = field.separator or self.config.default_list_separator
        cleaned = [v.strip() for v in values if v.strip()]
        return separator.join(cleaned)

    def _persist_annotations(self) -> None:
        output_path = self.config.annotation_output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        annotation_field_names = self.config.annotation_field_names()
        header = [ENTRY_ID_COLUMN] + self.csv_fieldnames + annotation_field_names
        if self.config.annotator_column:
            header.append(self.config.annotator_column)

        with output_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=header)
            writer.writeheader()
            for entry in self.entries:
                row = {ENTRY_ID_COLUMN: entry["id"]}
                row.update(entry["data"])
                if entry["id"] in self.annotations:
                    row.update(self.annotations[entry["id"]])
                if self.config.annotator_column:
                    row[self.config.annotator_column] = self.annotators.get(entry["id"], "")
                writer.writerow(row)

    def annotations_for_client(self) -> Dict[str, Dict[str, Any]]:
        if self._visible_entry_id_set is None:
            return {str(key): value for key, value in self.annotations.items()}
        return {
            str(key): value
            for key, value in self.annotations.items()
            if key in self._visible_entry_id_set
        }

    def annotators_for_client(self) -> Dict[str, str]:
        if self._visible_entry_id_set is None:
            return {str(key): value for key, value in self.annotators.items()}
        return {
            str(key): value
            for key, value in self.annotators.items()
            if key in self._visible_entry_id_set
        }

    def is_entry_visible(self, entry_id: int) -> bool:
        return self._is_entry_visible(entry_id)

    def _is_entry_visible(self, entry_id: int) -> bool:
        if self._visible_entry_id_set is None:
            return True
        return entry_id in self._visible_entry_id_set
