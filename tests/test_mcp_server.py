"""Tests for the MCP server (SQLite-backed)."""

import json
import pytest
from cord.db import CordDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    return CordDB(db_path)


@pytest.fixture
def setup_server(db, tmp_path):
    """Set up the MCP server module globals."""
    import cord.mcp.server as server
    server.db_path = str(tmp_path / "test.db")
    root_id = db.create_node("goal", "Test goal", status="active")
    server.agent_id = root_id
    return server, root_id


class TestReadTree:
    def test_returns_json(self, setup_server, db):
        server, root_id = setup_server
        db.create_node("spawn", "Research", parent_id=root_id)
        db.create_node("spawn", "Writing", parent_id=root_id)
        data = json.loads(server.read_tree())
        assert data["id"] == root_id
        assert data["status"] == "active"
        assert len(data["children"]) == 2


class TestReadNode:
    def test_existing(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "Research", parent_id=root_id)
        data = json.loads(server.read_node(child))
        assert data["id"] == child
        assert data["goal"] == "Research"

    def test_missing(self, setup_server):
        server, _ = setup_server
        data = json.loads(server.read_node("#999"))
        assert "error" in data


class TestSpawn:
    def test_creates_child(self, setup_server, db):
        server, root_id = setup_server
        result = json.loads(server.spawn("New task", "Do stuff", "text"))
        assert "created" in result
        child = db.get_node(result["created"])
        assert child["goal"] == "New task"
        assert child["parent_id"] == root_id

    def test_blocked_by(self, setup_server, db):
        server, root_id = setup_server
        a = json.loads(server.spawn("A"))["created"]
        b = json.loads(server.spawn("B", blocked_by=[a]))["created"]
        node = db.get_node(b)
        assert a in node["blocked_by"]


class TestFork:
    def test_creates_fork(self, setup_server, db):
        server, root_id = setup_server
        dep = json.loads(server.spawn("Dep task"))["created"]
        result = json.loads(server.fork("Analysis", "Analyze", "structured", [dep]))
        child = db.get_node(result["created"])
        assert child["node_type"] == "fork"


class TestStop:
    def test_stop_node(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id)
        result = json.loads(server.stop(child))
        assert result["cancelled"] == child
        assert db.get_node(child)["status"] == "cancelled"

    def test_stop_nonexistent(self, setup_server):
        server, _ = setup_server
        result = json.loads(server.stop("#999"))
        assert "error" in result


class TestComplete:
    def test_complete(self, setup_server, db):
        server, root_id = setup_server
        result = json.loads(server.complete('["Stripe"]'))
        assert result["completed"] == root_id
        node = db.get_node(root_id)
        assert node["status"] == "complete"
        assert node["result"] == '["Stripe"]'
