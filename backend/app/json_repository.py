"""JSON-file-backed implementation of TestRunRepository.

This is an MVP persistence mechanism suited to a single-process hackathon
deployment: a threading.Lock serializes access within this process, and
writes go through a temp-file-then-replace step so a crash mid-write can't
leave a truncated file. It is not safe for concurrent access from multiple
processes — replace with a database-backed TestRunRepository before that's
needed.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from app.schemas import TestRunConfig


class JsonFileTestRunRepository:
    def __init__(self, file_path: Path):
        self._file_path = file_path
        self._lock = threading.Lock()
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> dict[str, dict]:
        if not self._file_path.exists():
            return {}
        raw = self._file_path.read_text().strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _write_all(self, data: dict[str, dict]) -> None:
        tmp_path = self._file_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.replace(self._file_path)

    def create(self, run: TestRunConfig) -> TestRunConfig:
        with self._lock:
            data = self._read_all()
            data[run.id] = json.loads(run.model_dump_json())
            self._write_all(data)
        return run

    def update(self, run: TestRunConfig) -> TestRunConfig:
        return self.create(run)

    def list_all(self) -> list[TestRunConfig]:
        with self._lock:
            data = self._read_all()
        return [TestRunConfig.model_validate(v) for v in data.values()]

    def get(self, run_id: str) -> TestRunConfig | None:
        with self._lock:
            data = self._read_all()
        raw = data.get(run_id)
        return TestRunConfig.model_validate(raw) if raw is not None else None

    def delete(self, run_id: str) -> bool:
        with self._lock:
            data = self._read_all()
            if run_id not in data:
                return False
            del data[run_id]
            self._write_all(data)
        return True
