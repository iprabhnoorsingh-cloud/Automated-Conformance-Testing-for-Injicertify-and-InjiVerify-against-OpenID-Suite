"""Persistence abstraction for Test Run Configurations.

Routes depend only on this Protocol, not on any concrete storage mechanism,
so the JSON-file implementation used in this milestone can be swapped for a
database-backed one later without touching the API layer.
"""

from __future__ import annotations

from typing import Protocol

from app.schemas import TestRunConfig


class TestRunRepository(Protocol):
    def create(self, run: TestRunConfig) -> TestRunConfig: ...

    def list_all(self) -> list[TestRunConfig]: ...

    def get(self, run_id: str) -> TestRunConfig | None: ...

    def delete(self, run_id: str) -> bool: ...
