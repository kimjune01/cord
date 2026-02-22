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
        child = engine.db.create_node("task", "Task", parent_id=root, status="active")
        engine._handle_completion(child, 0, "result text")
        node = engine.db.get_node(child)
        assert node["status"] == "complete"
        assert node["result"] == "result text"

    def test_handle_completion_already_completed_via_mcp(self, engine):
        root = engine.db.create_node("goal", "Root", status="active")
        child = engine.db.create_node("task", "Task", parent_id=root, status="active")
        # Simulate agent calling complete() via MCP before process exits
        engine.db.complete_node(child, "MCP result")
        engine._handle_completion(child, 0, "stdout garbage")
        node = engine.db.get_node(child)
        assert node["status"] == "complete"
        assert node["result"] == "MCP result"  # MCP result preserved

    def test_handle_completion_failure(self, engine):
        root = engine.db.create_node("goal", "Root", status="active")
        child = engine.db.create_node("task", "Task", parent_id=root, status="active")
        engine._handle_completion(child, 1, "error")
        node = engine.db.get_node(child)
        assert node["status"] == "failed"

    def test_synthesis_triggered(self, engine):
        root = engine.db.create_node("goal", "Root", status="complete")
        child = engine.db.create_node("task", "Task", parent_id=root, status="active")
        engine.db.complete_node(child, "child result")
        children = engine.db.get_children(root)
        all_done = all(c["status"] in ("complete", "failed", "cancelled") for c in children)
        assert all_done

    def test_handle_ask(self, engine, monkeypatch):
        root = engine.db.create_node("goal", "Root", status="active")
        ask_node = engine.db.create_node(
            "ask", "Partial or full migration?",
            parent_id=root,
            prompt="Partial or full migration?\nOptions: partial, full\nDefault: partial",
        )
        node = engine.db.get_node(ask_node)
        monkeypatch.setattr("builtins.input", lambda _: "partial")
        engine._handle_ask(node)
        result = engine.db.get_node(ask_node)
        assert result["status"] == "complete"
        assert result["result"] == "partial"

    def test_handle_ask_default(self, engine, monkeypatch):
        root = engine.db.create_node("goal", "Root", status="active")
        ask_node = engine.db.create_node(
            "ask", "Continue?",
            parent_id=root,
            prompt="Continue?\nDefault: yes",
        )
        node = engine.db.get_node(ask_node)
        monkeypatch.setattr("builtins.input", lambda _: "")
        engine._handle_ask(node)
        result = engine.db.get_node(ask_node)
        assert result["status"] == "complete"
        assert result["result"] == "yes"

    def test_ask_nodes_not_launched_as_agents(self, engine):
        """Ask nodes should be handled by the engine, not launched as agent processes."""
        root = engine.db.create_node("goal", "Root", status="active")
        engine.db.create_node("ask", "Question?", parent_id=root)
        ready = engine.db.find_ready_nodes()
        ask_nodes = [n for n in ready if n["node_type"] == "ask"]
        agent_nodes = [n for n in ready if n["node_type"] != "ask"]
        assert len(ask_nodes) == 1
        assert len(agent_nodes) == 0
