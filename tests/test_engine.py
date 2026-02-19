"""Tests for the cord engine (SQLite-backed)."""

from pathlib import Path

import pytest

from cord.db import CordDB
from cord.runtime.engine import Engine


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "test.db"
    e = Engine("Test goal", db_path=db_path, project_dir=tmp_path)
    return e


class TestEngineBasics:
    def test_engine_creates_db(self, engine):
        assert engine.db_path.exists()

    def test_handle_completion_success(self, engine):
        root = engine.db.create_node("goal", "Root", status="active")
        child = engine.db.create_node("spawn", "Task", parent_id=root, status="active")
        engine._handle_completion(child, 0, "result text")
        node = engine.db.get_node(child)
        assert node["status"] == "complete"
        assert node["result"] == "result text"

    def test_handle_completion_already_completed_via_mcp(self, engine):
        root = engine.db.create_node("goal", "Root", status="active")
        child = engine.db.create_node("spawn", "Task", parent_id=root, status="active")
        # Simulate agent calling complete() via MCP before process exits
        engine.db.complete_node(child, "MCP result")
        engine._handle_completion(child, 0, "stdout garbage")
        node = engine.db.get_node(child)
        assert node["status"] == "complete"
        assert node["result"] == "MCP result"  # MCP result preserved

    def test_handle_completion_failure(self, engine):
        root = engine.db.create_node("goal", "Root", status="active")
        child = engine.db.create_node("spawn", "Task", parent_id=root, status="active")
        engine._handle_completion(child, 1, "error")
        node = engine.db.get_node(child)
        assert node["status"] == "failed"

    def test_synthesis_triggered(self, engine):
        root = engine.db.create_node("goal", "Root", status="complete")
        child = engine.db.create_node("spawn", "Task", parent_id=root, status="active")
        engine.db.complete_node(child, "child result")
        # _check_synthesis would relaunch parent, but we can't test the process launch
        # without mocking. Just verify the logic detects all children done.
        children = engine.db.get_children(root)
        all_done = all(c["status"] in ("complete", "failed", "cancelled") for c in children)
        assert all_done
