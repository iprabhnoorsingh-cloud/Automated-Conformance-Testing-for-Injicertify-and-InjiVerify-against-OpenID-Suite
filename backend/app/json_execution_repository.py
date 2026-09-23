"""JSON-file-backed implementation of ExecutionRepository.

Same MVP persistence approach as JsonFileTestRunRepository (see
app/json_repository.py): a threading.Lock serializes access within this
process, and writes go through a temp-file-then-replace step. Not safe for
concurrent access from multiple processes.

"Latest execution for a run" is determined by insertion order in the
underlying JSON object rather than by comparing timestamps, since dict/JSON
key order is preserved on both write and read and is immune to clock
resolution ties that repeated fast executions could otherwise trigger.
"""

import json
import threading
from pathlib import Path
from typing import Optional

from app.orchestration import Execution


class JsonFileExecutionRepository:
    def __init__(self, file_path: Path):
        self._file_path = file_path
        self._lock = threading.Lock()
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> dict:
        if not self._file_path.exists():
            return {}
        raw = self._file_path.read_text().strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _write_all(self, data: dict) -> None:
        tmp_path = self._file_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.replace(self._file_path)

    def create(self, execution: Execution) -> Execution:
        with self._lock:
            data = self._read_all()
            data[execution.id] = json.loads(execution.model_dump_json())
            self._write_all(data)
        return execution

    def update(self, execution: Execution) -> Execution:
        return self.create(execution)

    def get(self, execution_id: str) -> Optional[Execution]:
        with self._lock:
            data = self._read_all()
        raw = data.get(execution_id)
        return Execution.model_validate(raw) if raw is not None else None

    def get_latest_for_run(self, test_run_id: str) -> Optional[Execution]:
        with self._lock:
            data = self._read_all()
        matches = [v for v in data.values() if v.get("test_run_id") == test_run_id]
        if not matches:
            return None
        return Execution.model_validate(matches[-1])
