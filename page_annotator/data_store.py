from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

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

        self._load_entries()
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
        return [
            {
                "id": entry["id"],
                "url": entry["url"],
                "data": entry["data"],
            }
            for entry in self.entries
        ]

    def save_annotation(
        self, entry_id: int, payload: Dict[str, Any], annotator: Optional[str] = None
    ) -> Dict[str, Any]:
        _ = self.get_entry(entry_id)
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
        return {str(key): value for key, value in self.annotations.items()}

    def annotators_for_client(self) -> Dict[str, str]:
        return {str(key): value for key, value in self.annotators.items()}
